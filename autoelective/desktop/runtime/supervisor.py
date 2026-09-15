"""Framework-neutral supervisor with serialized lifecycle and background events."""
from collections import deque
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from functools import wraps

from ..platform.process_tree import spawn_owned_process
from ..platform.clock import active_time
from .protocol import MAX_LINE_BYTES, PROTOCOL_VERSION, EventValidator, decode, encode


class Signal:
    """Callbacks run on the emitting thread; UI adapters marshal where necessary."""
    def __init__(self):
        self._callbacks = []
        self._lock = threading.RLock()

    def connect(self, callback):
        with self._lock:
            self._callbacks.append(callback)

    def emit(self, value):
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(value)
            except Exception:
                # A renderer failure must never orphan the school worker.
                continue


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class EngineSupervisor:

    def __init__(self, data_root, parent=None, command=None, stop_timeout=5.0, power_factory=None, clock=active_time):
        self._lock = threading.RLock()
        self.state_changed = Signal()
        self.snapshot_received = Signal()
        self.log_received = Signal()
        self.data_root = Path(data_root).resolve()
        self._command = command
        self._stop_timeout = stop_timeout
        self._clock = clock
        self._process = None
        self._tree = None
        self._state = "stopped"
        self._stop_deadline = None
        self._terminal = None
        self._events = deque(maxlen=256)
        self._events_lock = threading.Lock()
        self._lost_events = 0
        self._poll_stop = threading.Event()
        self._last_event_at = None
        # Custom commands are used by offline harnesses. Never change the host's
        # power plan just because a unit test launches a fake worker.
        if power_factory is None and command is None and os.name == 'nt':
            from ..platform.power_plan import PowerPlanLease
            power_factory = PowerPlanLease
        self._power_factory = power_factory
        self._power_plan = None
        self._next_power_check = 0

    @serialized
    def recover_power(self):
        if self._power_factory and not self.is_active:
            self._power_factory(self.data_root).recover()

    @property
    @serialized
    def state(self):
        return self._state

    @property
    @serialized
    def is_active(self):
        return self._process is not None

    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    @serialized
    def start(self, config_dict, password):
        if self.is_active:
            raise RuntimeError("请先停止当前任务。")
        run_id = uuid.uuid4().hex
        payload = encode({"version": PROTOCOL_VERSION, "type": "start", "run_id": run_id,
                          "config": config_dict, "password": password})
        self.data_root.mkdir(parents=True, exist_ok=True)
        command = self._command or ([sys.executable, "--worker"] if getattr(sys, "frozen", False)
                                    else [sys.executable, str(Path(__file__).resolve().parents[3] / "desktop.py"), "--worker"])
        environment = os.environ.copy()
        environment["PKU_AUTOELECTIVE_DATA_DIR"] = str(self.data_root)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        self._events = deque(maxlen=256)
        self._lost_events = 0
        self._validator = EventValidator(run_id)
        self._terminal = None
        self._stop_deadline = None
        self._forced = False
        self._fault = False
        self._last_event_at = self._clock()
        self._set_state("starting")
        try:
            if self._power_factory:
                self._power_plan = self._power_factory(self.data_root)
                self._power_plan.acquire()
                self._next_power_check = time.monotonic() + 5
                self.log_received.emit('[信息] 已核验接电/电池下的合盖、睡眠按钮、待机、休眠和显示保护；每 5 秒复查，结束任务后恢复原电源方案。')
            process, self._tree = spawn_owned_process(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, cwd=str(self.data_root), env=environment,
                                       start_new_session=os.name != "nt",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self._process = process
            process.stdin.write(payload)
            process.stdin.flush()
            payload = None
            events = self._events

            def read_events():
                try:
                    while True:
                        line = process.stdout.readline(MAX_LINE_BYTES + 1)
                        if not line:
                            return
                        try:
                            event = decode(line)
                            with self._events_lock:
                                if len(events) == events.maxlen:
                                    self._lost_events += 1
                                events.append(event)
                        except (ValueError, UnicodeError):
                            with self._events_lock:
                                events.append({"_invalid": True})
                            return
                except (OSError, ValueError):
                    return

            self._reader = threading.Thread(target=read_events, daemon=True, name="EngineEvents")
            self._reader.start()
            self._poll_stop = threading.Event()
            poll_stop = self._poll_stop

            def poll_events():
                while not poll_stop.wait(0.05):
                    self._poll()

            self._poller = threading.Thread(target=poll_events, daemon=True, name="EngineSupervisor")
            self._poller.start()
        except Exception:
            if self._process is not None:
                if self._tree:
                    self._tree.kill()
                else:
                    self._process.kill()
                self._process.wait(timeout=2)
            self._cleanup()
            self._set_state("failed")
            self.log_received.emit("无法启动选课引擎；请按界面错误提示检查电源保护、程序文件或目录权限。")
            raise

    @serialized
    def stop(self):
        if not self.is_active or self._stop_deadline is not None:
            return
        self._set_state("stopping")
        self._stop_deadline = self._clock() + self._stop_timeout
        try:
            self._process.stdin.write(encode({"type": "stop"}))
            self._process.stdin.flush()
            self._process.stdin.close()
        except (OSError, ValueError):
            pass

    @serialized
    def _poll(self):
        if self._process is None:
            return
        if self._power_plan and time.monotonic() >= self._next_power_check:
            old_error = self._power_plan.error
            try:
                self._power_plan.ensure()
            except Exception:
                pass  # Keep monitoring; do not replay or discard school requests.
            if self._power_plan.error != old_error:
                self.log_received.emit('[警告] ' + self._power_plan.error if self._power_plan.error
                                       else '[信息] 合盖持续运行保护已恢复。')
            self._next_power_check = time.monotonic() + 5
        with self._events_lock:
            lost, self._lost_events = self._lost_events, 0
        if lost:
            self.log_received.emit('[警告] 引擎日志突发，通信缓冲已丢弃 %d 条较早事件；保留最新状态，后续心跳继续同步。' % lost)
        for _ in range(256):
            try:
                with self._events_lock:
                    event = self._events.popleft()
            except IndexError:
                break
            if event.get("_invalid"):
                self._fault = True
                self.log_received.emit("引擎通信异常，任务已停止。")
                self.stop()
                self._tree.kill()
                break
            if not self._validator.accept(event):
                continue
            self._last_event_at = self._clock()
            kind = event["type"]
            if kind == "state" and self._state != "stopping":
                self._set_state(event["state"])
            elif kind == "snapshot":
                if self._state == 'starting':
                    self._set_state('running')
                if self._power_plan:
                    power = event['data'].setdefault('power', {})
                    power['lid_protected'] = self._power_plan.ready
                    power['plan_error'] = self._power_plan.error
                self.snapshot_received.emit(event["data"])
                if event['data'].get('stalled') and not self._fault:
                    self._fault = True
                    self.log_received.emit('[错误] 会话长时间无响应，已触发安全停止。请核对学校已选列表，不会自动重放提交。')
                    self.stop()
            elif kind == "log":
                self.log_received.emit(event["message"][:4000])
            elif kind == "finished":
                self._terminal = event["state"]
        if (self._last_event_at is not None and self._clock() - self._last_event_at > 90
                and self._stop_deadline is None and self._process.poll() is None):
            self._fault = True
            self.log_received.emit('[错误] 选课引擎超过 90 秒没有心跳，已安全停止；请检查运行记录并核对已选课程。')
            self.stop()
        if self._stop_deadline is not None and self._clock() >= self._stop_deadline and self._process.poll() is None:
            self._forced = True
            self._tree.kill()
        returncode = self._process.poll()
        if returncode is not None:
            # A child may close just before its last messages reach the reader.
            self._reader.join(timeout=0.1)
            if self._events:
                return
            terminal = ("failed" if self._fault else "stopped" if self._stop_deadline is not None
                        else self._terminal if self._terminal and returncode == 0 else "failed")
            if self._forced:
                self.log_received.emit("引擎已强制停止；已提交课程的结果请在学校已选列表核对。")
            elif terminal == "failed" and self._terminal is None:
                self.log_received.emit("引擎意外退出，请检查运行记录后重新启动。")
            self._cleanup()
            self._set_state(terminal)

    def _cleanup(self):
        self._poll_stop.set()
        if self._tree:
            self._tree.kill()  # Include any descendants surviving a normal worker exit.
            self._tree.close()
            self._tree = None
        if self._process:
            for pipe in (self._process.stdin, self._process.stdout):
                if pipe and not pipe.closed:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        self._process = None
        if self._power_plan:
            try:
                self._power_plan.close()
                self._power_plan = None
                self.log_received.emit('[信息] 已恢复原电源方案并移除临时选课方案。')
            except Exception as error:
                self.log_received.emit('[警告] ' + str(error))

    @serialized
    def shutdown(self, timeout_ms=5000):
        if not self.is_active:
            if self._power_plan:
                self._cleanup()
            return True
        self.stop()
        try:
            self._process.wait(timeout=max(0, timeout_ms / 1000))
        except subprocess.TimeoutExpired:
            self._forced = True
            self._tree.kill()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                return False
        self._poll()
        if self._process is not None:
            self._poll()
        return not self.is_active
