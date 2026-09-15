import os
from pathlib import Path
import sys
import time

import pytest

from autoelective.desktop.runtime.protocol import EventValidator, decode, encode, MAX_LINE_BYTES
from autoelective.desktop.runtime.supervisor import EngineSupervisor


@pytest.fixture(scope="module")
def app():
    return None


def pump(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def supervisor(tmp_path, mode="cooperative", **kwargs):
    return EngineSupervisor(tmp_path, command=[sys.executable, str(Path(__file__).with_name("fake_worker.py")), mode], **kwargs)


def test_protocol_rejects_stale_run_duplicate_and_bad_payload():
    validator = EventValidator("current")
    message = dict(version=1, run_id="current", seq=1, type="state", state="running")
    assert validator.accept(message)
    assert not validator.accept(message)
    assert not validator.accept(dict(message, run_id="stale", seq=2))
    assert not validator.accept(dict(message, seq=2, state="bogus"))
    assert decode(encode({"中文": "课程"})) == {"中文": "课程"}
    with pytest.raises(ValueError):
        decode(b"x" * (MAX_LINE_BYTES + 1))


def test_stop_waits_for_exit_and_restart_is_fresh(app, tmp_path):
    engine = supervisor(tmp_path)
    snapshots = []
    engine.snapshot_received.connect(snapshots.append)
    try:
        for _ in range(2):
            engine.start({}, "private-password-for-test")
            pump(app, lambda: engine.state == "running")
            with pytest.raises(RuntimeError):
                engine.start({}, "private-password-for-test")
            engine.stop()
            assert engine.state == "stopping"
            assert engine.is_active
            pump(app, lambda: not engine.is_active)
            assert engine.state == "stopped"
        assert len(snapshots) == 2
        assert list(tmp_path.iterdir()) == []  # Credentials never persisted.
    finally:
        engine.shutdown()


@pytest.mark.parametrize("mode,terminal", [("complete", "completed"), ("crash", "failed"), ("malformed", "failed")])
def test_terminal_state_tracks_real_process_exit(app, tmp_path, mode, terminal):
    engine = supervisor(tmp_path, mode)
    try:
        engine.start({}, "private-password-for-test")
        pump(app, lambda: not engine.is_active)
        assert engine.state == terminal
    finally:
        engine.shutdown()


def test_hung_child_is_killed_within_deadline(app, tmp_path):
    engine = supervisor(tmp_path, "stubborn", stop_timeout=0.1)
    logs = []
    engine.log_received.connect(logs.append)
    engine.start({}, "private-password-for-test")
    pump(app, lambda: engine.state == "running")
    engine.stop()
    pump(app, lambda: not engine.is_active)
    assert engine.state == "stopped"
    assert any("强制停止" in line for line in logs)


def test_window_shutdown_is_bounded(app, tmp_path):
    engine = supervisor(tmp_path, "stubborn")
    engine.start({}, "private-password-for-test")
    pump(app, lambda: engine.state == "running")
    started = time.monotonic()
    assert engine.shutdown(timeout_ms=100)
    assert time.monotonic() - started < 2


def test_missing_heartbeat_and_stalled_session_are_fail_closed(app, tmp_path):
    for mode in ('cooperative', 'stalled'):
        engine = supervisor(tmp_path, mode, stop_timeout=0.1)
        logs = []
        engine.log_received.connect(logs.append)
        try:
            engine.start({}, 'offline-private')
            if mode == 'cooperative':
                pump(app, lambda: engine.state == 'running')
                with engine._lock:
                    engine._last_event_at = engine._clock() - 91
            pump(app, lambda: not engine.is_active)
            assert engine.state == 'failed'
            assert any('心跳' in line or '长时间无响应' in line for line in logs)
        finally:
            engine.shutdown()


def test_ignored_courses_are_not_counted_as_elected():
    from types import SimpleNamespace
    from threading import RLock
    from autoelective.course import Course
    from autoelective.desktop.runtime.worker import make_snapshot
    elected = Course("A", 1, "S")
    ignored = Course("B", 2, "S")
    pending = Course("C", 3, "S")
    state = SimpleNamespace(state_lock=RLock(), ignored={elected: "Elected", ignored: "Mutex rules"},
                            pending_courses={pending}, course_details={pending: (10, 9)}, errors={},
                            iaaa_loop=2, elective_loop=3)
    snapshot = make_snapshot(state, SimpleNamespace(courses={"a": elected, "b": ignored, "c": pending}))
    assert [c["status"] for c in snapshot["courses"]] == ["elected", "ignored", "unconfirmed"]
    assert snapshot["courses"][2]["remaining"] == 1
    assert snapshot["unconfirmed_count"] == 1


def test_cancel_interrupts_empty_queue_and_prevents_http():
    from queue import Queue
    from autoelective.environ import Environ, EngineCancelled, interruptible_get
    from autoelective.client import BaseClient
    environment = Environ()
    environment.stop_event.set()
    try:
        with pytest.raises(EngineCancelled):
            interruptible_get(Queue())

        class Client(BaseClient):
            pass

        with pytest.raises(EngineCancelled):
            Client()._get("https://example.invalid")
    finally:
        environment.stop_event.clear()


def test_course_snapshot_does_not_claim_quota_before_first_query():
    from types import SimpleNamespace
    from threading import RLock
    from autoelective.course import Course
    from autoelective.desktop.runtime.worker import make_snapshot
    unknown = Course("A", 1, "S")
    available = Course("B", 2, "S")
    full = Course("C", 3, "S")
    state = SimpleNamespace(state_lock=RLock(), ignored={}, pending_courses=set(),
                            course_details={available: (10, 9), full: (10, 10)}, errors={},
                            iaaa_loop=0, elective_loop=0)
    snapshot = make_snapshot(state, SimpleNamespace(courses={"a": unknown, "b": available, "c": full}))
    assert [c["status"] for c in snapshot["courses"]] == ["unknown", "pending", "waiting"]
    assert snapshot["courses"][0]["remaining"] is None


def test_lifecycle_readers_wait_until_cleanup_and_terminal_state_are_atomic(tmp_path):
    import threading
    engine = supervisor(tmp_path)
    engine._process = object()
    engine._state = 'running'
    entered, observed = threading.Event(), threading.Event()
    result = []

    def observe():
        entered.set()
        result.append((engine.is_active, engine.state))
        observed.set()

    thread = threading.Thread(target=observe, daemon=True)
    try:
        with engine._lock:
            # The polling thread has cleaned up but not yet published terminal.
            engine._process = None
            thread.start()
            assert entered.wait(1)
            assert not observed.wait(0.1)
            engine._state = 'failed'
        thread.join(timeout=1)
        assert result == [(False, 'failed')]
    finally:
        thread.join(timeout=1)


class TestPowerLease:
    __test__ = False
    def __init__(self):
        self.events = []
        self.ready, self.error = False, ''
    def acquire(self): self.events.append('acquire'); self.ready = True
    def ensure(self): self.events.append('ensure')
    def close(self): self.events.append('close'); self.ready = False


@pytest.mark.parametrize('mode', ['cooperative', 'complete', 'crash', 'malformed', 'stubborn'])
def test_parent_releases_power_after_normal_or_forced_worker_exit(tmp_path, mode):
    lease = TestPowerLease()
    engine = supervisor(tmp_path, mode, stop_timeout=0.1, power_factory=lambda path: lease)
    snapshots = []
    engine.snapshot_received.connect(snapshots.append)
    try:
        engine.start({}, 'fixture-power-test')
        pump(None, lambda: bool(snapshots) or not engine.is_active)
        if mode in ('cooperative', 'stubborn'):
            engine.stop()
        pump(None, lambda: not engine.is_active)
        assert lease.events[0] == 'acquire' and lease.events[-1] == 'close'
        assert not lease.ready
        assert all(row['power']['lid_protected'] for row in snapshots)
    finally:
        engine.shutdown()


def test_power_setup_failure_never_launches_a_school_worker(tmp_path, monkeypatch):
    lease = TestPowerLease()
    def fail(): raise RuntimeError('电源设置被拒绝')
    lease.acquire = fail
    def forbidden(*args, **kwargs): raise AssertionError('Worker must not launch')
    monkeypatch.setattr('autoelective.desktop.runtime.supervisor.subprocess.Popen', forbidden)
    engine = supervisor(tmp_path, power_factory=lambda path: lease)
    with pytest.raises(RuntimeError, match='电源设置被拒绝'):
        engine.start({}, 'fixture')
    assert not engine.is_active and engine.state == 'failed'
    assert lease.events == ['close']


def test_long_suspend_does_not_expire_supervisor_heartbeat(tmp_path, monkeypatch):
    awake = [10]
    engine = supervisor(tmp_path, clock=lambda: awake[0])
    try:
        engine.start({}, 'fixture')
        pump(None, lambda: engine.state == 'running')
        # A wall/performance clock jump must not become 90 seconds of worker silence.
        monkeypatch.setattr('autoelective.desktop.runtime.supervisor.time.monotonic', lambda: 999999)
        engine._poll()
        assert engine.state == 'running' and engine._stop_deadline is None
    finally:
        engine.shutdown()
