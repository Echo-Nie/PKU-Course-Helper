"""Isolated legacy engine adapter. Import this before importing legacy config."""
import io
import os
import sys
import threading
import time

from .protocol import MAX_LINE_BYTES, PROTOCOL_VERSION, decode, encode
from .stdio import bootstrap_stdio
from ..platform.power import SleepProtection


REASONS = {
    "Elected": ("elected", "已确认选上"),
    "Repeated": ("ignored", "重复选课，需核对已选列表"),
    "Mutex rules": ("ignored", "互斥规则"),
    "Time conflict": ("ignored", "上课时间冲突"),
    "Exam time conflict": ("ignored", "考试时间冲突"),
    "Permission required": ("ignored", "不符合选课权限"),
    "Credits limited": ("ignored", "学分限制"),
    "Mutual exclusive": ("ignored", "学校互斥规则"),
    "Multi English course": ("ignored", "英语课程数量限制"),
    "Multi PE course": ("ignored", "体育课程数量限制"),
}

ERROR_MESSAGES = {
    "AccessLimitedError": "学校系统已限制访问，任务已停止。请稍后手动重试。",
    "IAAAIncorrectPasswordError": "账号或密码不正确，请重新输入。",
    "IAAAForbiddenError": "账号登录暂时受限，请稍后重试。",
    "CaughtCheatingError": "学校系统已限制本次访问，任务已停止。",
    "NotAgreedToSelectionAgreement": "请先在学校选课系统阅读并同意选课协议，再手动启动。",
    "UserInputException": "课程或策略与学校选课计划不一致，请核对配置。",
    "FileNotFoundError": "程序资源缺失，请重新解压完整的软件包。",
    "ModuleNotFoundError": "程序组件缺失，请重新解压完整的软件包。",
    "PermissionError": "软件目录无法读写，请移到可写目录后重试。",
}


def safe_error(error):
    name = type(error).__name__
    if name == 'IAAAIncorrectPasswordError':
        # Only classify explicit school wording; never echo credential-bearing
        # exception details or guess which field is wrong from the E01 code.
        detail = str(getattr(error, 'detail', ''))
        if any(text in detail for text in ('账号不存在', '学号不存在', '用户名不存在', '用户不存在')):
            return '账号不存在，请核对统一认证学号后重新开始。'
        if '账号或密码' not in detail and '用户名或密码' not in detail and any(text in detail for text in ('密码错误', '密码不正确')):
            return '密码不正确，请重新输入统一认证密码后开始。'
    if name == 'AccessLimitedError':
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        if status in (403, 429):
            return 'HTTP %d：学校系统已限制访问，任务已停止；不自动重试或绕过限制。' % status
    return ERROR_MESSAGES.get(name, "未知错误警告：选课引擎发生异常（%s），已安全停止；请核对运行记录和学校已选列表。" % name)


def make_snapshot(environ, config):
    courses = []
    with environ.state_lock:
        ignored = dict(environ.ignored)
        details = dict(environ.course_details)
        pending = set(environ.pending_courses)
        blocked = set(getattr(environ, "blocked_by_pending", set()))
        errors = dict(environ.errors)
        observed = dict(getattr(environ, "page_last_seen", {}))
    page_map = getattr(config, "course_pages", {})
    for course_id, course in config.courses.items():
        raw_reason = ignored.get(course)
        quota = details.get(course)
        if quota is None:
            status, reason = "unknown", "尚未查询"
        elif quota[0] > quota[1]:
            status, reason = "pending", "有剩余名额，等待处理"
        else:
            status, reason = "waiting", "等待名额"
        status, reason = REASONS.get(raw_reason, (status, reason))
        if raw_reason and raw_reason not in REASONS:
            status, reason = "ignored", "已忽略"
        if course in pending:
            status, reason = "unconfirmed", "已提交，结果待确认"
        elif course in blocked:
            status, reason = "pending", "等待互斥课程的提交结果确认"
        courses.append({"id": course_id, "name": course.name, "class_no": course.class_no,
                        "school": course.school, "status": status, "reason": reason,
                        "page": page_map.get(course_id, 1), "observed_at": observed.get(page_map.get(course_id, 1)),
                        "capacity": quota[0] if quota else None,
                        "enrolled": quota[1] if quota else None,
                        "remaining": quota[0] - quota[1] if quota else None})
    return {"iaaa_loop": environ.iaaa_loop, "elective_loop": environ.elective_loop,
            "error_count": sum(errors.values()), "errors": errors, "courses": courses,
            "page_allocations": {str(page): list(slots) for page, slots in getattr(environ, "page_allocations", {}).items()},
            "unconfirmed_count": sum(c["status"] == "unconfirmed" for c in courses)}


class _DiscardStream(io.TextIOBase):
    def write(self, text):
        return len(text)

    def flush(self):
        pass


def worker_main(data_root=None, engine_factory=None):
    """Read credentials through private stdin; supervise the fair desktop engine."""
    # Small serial captcha inference does not benefit from a BLAS thread per
    # CPU core. Configure only this child before importing NumPy/native DLLs.
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    try:
        bootstrap_stdio()
    except OSError:
        return 2
    # Unbuffered input avoids BufferedReader's daemon-thread shutdown lock.
    input_stream = io.FileIO(os.dup(sys.stdin.fileno()), "rb", closefd=True)
    output_stream = sys.stdout.buffer
    try:
        initial = decode(input_stream.readline(MAX_LINE_BYTES + 1))
        if initial.get("type") != "start" or initial.get("version") != PROTOCOL_VERSION:
            return 2
        run_id = initial["run_id"]
        if not isinstance(run_id, str) or len(run_id) > 80:
            return 2
    except (ValueError, KeyError, UnicodeError, OSError):
        return 2
    if data_root is not None:
        os.environ["PKU_AUTOELECTIVE_DATA_DIR"] = str(data_root)
    if not os.environ.get("PKU_AUTOELECTIVE_DATA_DIR"):
        return 2
    sys.stdout = _DiscardStream()
    sys.stderr = _DiscardStream()
    emit_lock = threading.Lock()
    sequence = 0

    def emit(kind, **payload):
        nonlocal sequence
        with emit_lock:
            sequence += 1
            try:
                output_stream.write(encode(dict(version=PROTOCOL_VERSION, run_id=run_id,
                                                seq=sequence, type=kind, **payload)))
                output_stream.flush()
            except (BrokenPipeError, OSError):
                os._exit(0)  # The parent is gone; no new school requests may be issued.

    power = SleepProtection()

    def release_power():
        was_active = power.active
        power.close()
        if was_active:
            emit('log', message=('[警告] ' + power.error if power.error else
                 '[信息] 已释放本任务的防自动睡眠请求，不再阻止 Windows 按原有设置自动睡眠。'))

    try:
        from ..domain.config import AppConfig, validate
        from ..adapters.ini_codec import to_parser
        app_config = AppConfig.from_dict(initial["config"])
        password = initial.pop("password", "")
        issues = validate(app_config, for_run=True, password=password)
        if issues:
            emit("log", message="配置校验未通过，请检查账号和课程。")
            emit("finished", state="failed")
            return 2
        protection = power.acquire()
        emit('log', message=('[信息] 系统、显示和进程持续运行请求已启用；合盖保护由工作台单独检查，运行期间屏幕可能保持点亮。'
                            if protection['active'] else '[警告] ' + protection['error']))
        os.makedirs(os.environ["PKU_AUTOELECTIVE_DATA_DIR"], exist_ok=True)
        from autoelective.environ import Environ, EngineCancelled
        from autoelective.config import AutoElectiveConfig
        environ = Environ()
        environ.config_parser = to_parser(app_config, password=password)
        environ.config_parser.set("client", "debug_print_request", "false")
        environ.config_parser.set("client", "debug_dump_request", "false")
        AutoElectiveConfig()
        initial.clear()
        # Windows native DLL initialization can hang while another thread is
        # blocked reading stdin (numpy/numpy#24290). Load native dependencies
        # before starting ControlPipe, not lazily inside either engine loop.
        # This is after validation, and performs no school network requests.
        # The supervisor still enforces its 5-second stop/parent-exit deadline
        # during initialization, before cooperative cancellation is available.
        import numpy
        import onnxruntime
        from PIL import Image
        requested_stop = threading.Event()
        engine = None

        def commands():
            while True:
                try:
                    line = input_stream.readline(MAX_LINE_BYTES + 1)
                except OSError:
                    os._exit(0)  # A broken control channel must fail closed.
                if not line:
                    os._exit(0)
                try:
                    command = decode(line)
                except (ValueError, UnicodeError):
                    command = {}
                if command.get("type") == "stop" or not command:
                    requested_stop.set()
                    environ.stop_event.set()
                    if engine is not None:
                        engine.cancel()
                    return

        threading.Thread(target=commands, daemon=True, name="ControlPipe").start()
        # Load the desktop scheduler only after legacy protocol hooks have an
        # in-memory config. Never run the legacy all-pages barrier in the GUI.
        if engine_factory is None:
            from .engine import DesktopEngine
            engine_factory = DesktopEngine
        engine = engine_factory(app_config, password, environ.stop_event,
                                lambda message: emit('log', message=message))
        password = None
        environ.config_parser.set('user', 'password', '')
        if requested_stop.is_set():
            engine.cancel()

        failures = []

        def guarded(target):
            try:
                target()
            except EngineCancelled:
                pass
            except BaseException as error:
                failures.append(type(error).__name__)
                emit("log", message=safe_error(error))
                environ.stop_event.set()

        thread = threading.Thread(target=guarded, args=(engine.run,), daemon=True, name='DesktopScheduler')
        emit("state", state="running")
        emit("log", message="选课引擎已启动。")
        thread.start()
        next_summary = time.monotonic()
        next_power_check = time.monotonic() + 30
        while thread.is_alive():
            if time.monotonic() >= next_power_check:
                previous_error = power.error
                power.refresh()
                if power.error != previous_error:
                    emit('log', message=('[警告] ' + power.error if power.error else '[信息] 持续运行请求已恢复。'))
                next_power_check = time.monotonic() + 30
            snapshot = engine.snapshot()
            snapshot['power'] = power.status()
            emit("snapshot", data=snapshot)
            current_loops = (snapshot["iaaa_loop"], snapshot["elective_loop"])
            if time.monotonic() >= next_summary:
                counts = {}
                for row in snapshot['courses']:
                    counts[row['status']] = counts.get(row['status'], 0) + 1
                emit("log", message="[统计] 已运行 %.1f 小时 · 登录 %d 次 · 页面查询 %d 次 · 已选 %d · 等待 %d · 不匹配 %d · 待核对 %d · 异常 %d。" %
                     (snapshot.get('uptime_seconds', 0) / 3600, *current_loops, counts.get('elected', 0),
                      counts.get('waiting', 0), counts.get('unmatched', 0), counts.get('unconfirmed', 0), snapshot['error_count']))
                next_summary = time.monotonic() + 60
            thread.join(timeout=1.0)  # Heartbeat independent of the renderer, no busy wait.
        final_snapshot = engine.snapshot()
        engine.close()
        release_power()
        final_snapshot['power'] = power.status()
        emit("snapshot", data=final_snapshot)
        terminal = "failed" if failures else "stopped" if requested_stop.is_set() else "completed"
        emit("finished", state=terminal)
        return 1 if failures else 0
    except BaseException as error:
        release_power()
        emit("log", message=safe_error(error))
        emit("finished", state="failed")
        return 1
    finally:
        power.close()  # All exits, including initialization/validation errors.
