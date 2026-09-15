from collections import Counter
import threading
import time
from types import SimpleNamespace

from autoelective.desktop.domain.config import AppConfig, CourseConfig
from autoelective.desktop.runtime.engine import DesktopEngine
from autoelective.desktop.runtime.journal import RollingLogWriter
from autoelective.desktop.runtime.scheduler import FairDispatcher
from autoelective.desktop.runtime.school_session import SchoolSession


def test_fixed_workers_are_reused_for_thousands_of_turns_without_live_thread_growth():
    config = AppConfig(courses=[CourseConfig(id=str(i), name=str(i), school='院', page=i+1) for i in range(4)])
    stop, lock = threading.Event(), threading.Lock()
    identities = set()
    count = [0]
    class Session:
        ready = True
        def __init__(self, sid): self.sid = sid
        def ensure_login(self, identity, budget): return False
        def fetch(self, page, budget):
            with lock:
                identities.add(threading.get_ident())
                count[0] += 1
                if count[0] >= 5000: stop.set()
            c = config.courses[page-1]
            return [], [SimpleNamespace(name=c.name, school=c.school, class_no=1, status=(10, 10))]
        def close(self): pass
    engine = DesktopEngine(config, '', stop, session_factory=Session)
    engine.run()
    assert count[0] >= 5000
    assert len(engine.workers) == 4 and len(identities) <= 4
    assert all(not worker.is_alive() for worker in engine.workers)
    assert not engine.tasks and all(not s.busy for s in engine.dispatcher.slots)
    assert len(engine.book.rows) == 4 and len(engine.notices) <= 4
    engine.close()


def test_250_hour_virtual_scheduler_fairness_and_bounded_route_state():
    dispatcher = FairDispatcher([('bzx', page) for page in range(1, 14)] + [('bfx', 1), ('bfx', 2)], 4)
    counts, slots, last = Counter(), Counter(), {}
    largest_gap = 0
    now = 0
    for turn in range(150_000):
        key, sid = dispatcher.lease(now)
        if key in last: largest_gap = max(largest_gap, turn - last[key])
        last[key] = turn
        counts[key] += 1
        slots[sid] += 1
        dispatcher.finish(key, sid, now, failed=(turn % 113 == 0))
        now += 6
    assert now / 3600 == 250
    assert min(counts.values()) > 5000 and largest_gap < 60
    assert set(slots) == {1, 2, 3, 4}
    assert len(dispatcher.routes) == 15 and len(dispatcher.slots) == 4


def test_slow_disk_uses_bounded_queue_without_blocking_the_caller(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Handler:
        def __init__(self, *a, **kw): pass
        def emit(self, record): entered.set(); release.wait(2)
        def close(self): pass
    writer = RollingLogWriter(tmp_path, Handler)
    writer.submit('first')
    assert entered.wait(1)
    for _ in range(2000): writer.submit('bounded')
    assert writer.status()['queued'] == writer.LIMIT
    assert writer.status()['dropped'] >= 1400
    assert not writer.close(timeout=0.001)
    release.set()
    assert writer.close()


def test_disk_full_is_reported_without_crashing_or_endless_disk_retries(tmp_path):
    attempted = []
    class Handler:
        def __init__(self, *a, **kw): pass
        def emit(self, record): attempted.append(1); raise OSError('not enough disk')
        def close(self): pass
    writer = RollingLogWriter(tmp_path, Handler)
    for _ in range(20): writer.submit('test')
    assert writer.close()
    assert len(attempted) == 1
    assert writer.status()['error'] and writer.status()['dropped'] == 20


def test_session_lifetime_does_not_follow_wall_clock(monkeypatch):
    session = SchoolSession.__new__(SchoolSession)
    session.ready, session.identity, session.expires_at = True, 'bzx', 100
    monkeypatch.setattr(time, 'monotonic', lambda: 90)
    monkeypatch.setattr(time, 'time', lambda: -9_000_000)
    assert not session.ensure_login('bzx', None)
    monkeypatch.setattr(time, 'time', lambda: 9_000_000_000)
    assert not session.ensure_login('bzx', None)


def test_phase_watchdog_detects_stuck_turn_but_not_idle_waiting():
    now = [0]
    config = AppConfig(courses=[CourseConfig(name='课', school='院')])
    engine = DesktopEngine(config, '', threading.Event(), session_factory=lambda sid: SimpleNamespace(ready=True), clock=lambda: now[0])
    key, sid = engine.dispatcher.lease(0)
    engine._phase(sid, key, '提交选课', 30)
    now[0] = 31
    assert engine.snapshot()['stalled']
    engine.dispatcher.finish(key, sid, now[0])
    assert not engine.snapshot()['stalled']


def test_identity_affinity_does_not_relogin_on_every_short_idle_gap():
    dispatcher = FairDispatcher([('bzx', p) for p in range(1, 8)] + [('bfx', 1), ('bfx', 2)], 4)
    leases = [dispatcher.lease(0) for _ in range(4)]
    minor = next((key, sid) for key, sid in leases if key[0] == 'bfx')
    dispatcher.finish(*minor, 0)
    dispatcher.identity_turn['bfx'] = 100  # Primary is oldest, but has no idle own slot.
    next_key, sid = dispatcher.lease(0)
    assert next_key[0] == 'bfx' and sid == minor[1]


def test_client_releases_response_when_a_hook_raises(monkeypatch):
    import autoelective.client as module
    closed = []
    class Client(module.BaseClient): pass
    client = Client()
    failure = RuntimeError('private-response-must-not-be-logged')
    failure.response = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(module, 'checkpoint', lambda: None)
    def fail(*a, **kw): raise failure
    monkeypatch.setattr(client._session, 'send', fail)
    import pytest
    with pytest.raises(RuntimeError) as caught:
        client._get('https://offline.invalid/')
    assert caught.value is failure and closed == [True]
    client._session.close()
