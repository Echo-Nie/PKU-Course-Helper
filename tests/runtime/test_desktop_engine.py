from collections import Counter
from types import SimpleNamespace
import threading

import pytest

from autoelective.desktop.domain.config import AppConfig, CourseConfig
from autoelective.desktop.runtime.engine import DesktopEngine
from autoelective.desktop.runtime.school_session import RetryTurn, IdentityUnavailable
from autoelective.exceptions import AccessLimitedError


class FastBudget:
    def wait(self):
        pass
    def cancel(self):
        pass


def test_slow_or_failed_page_does_not_block_other_identity_and_stop_joins_every_lease():
    config = AppConfig(courses=[CourseConfig(id='a', name='a', school='院', page=1),
                                CourseConfig(id='b', name='b', school='院', identity='bfx', page=2)])
    blocked, minor_progress, release = threading.Event(), threading.Event(), threading.Event()
    visited, closed = Counter(), []
    class Session:
        ready = True
        def __init__(self, slot): self.slot = slot
        def ensure_login(self, identity, budget): self.identity = identity; return True
        def fetch(self, page, budget):
            visited[(self.identity, page)] += 1
            if self.identity == 'bzx':
                blocked.set()
                assert release.wait(3)
                raise RetryTurn('offline')
            minor_progress.set()
            return [config.courses[1]], []
        def close(self): closed.append(self.slot)
    engine = DesktopEngine(config, '', threading.Event(), session_factory=Session,
                           query_budget=FastBudget(), login_budget=FastBudget())
    thread = threading.Thread(target=engine.run)
    thread.start()
    try:
        assert blocked.wait(1) and minor_progress.wait(1)
        assert engine.snapshot()['courses'][1]['status'] == 'elected'
        engine.cancel()
        release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert all(not slot.busy for slot in engine.dispatcher.slots)
    finally:
        release.set()
        engine.cancel()
        thread.join(3)
        engine.close()
    assert set(closed) == {1, 2, 3, 4}


def test_unavailable_minor_fails_only_minor_and_primary_finishes():
    config = AppConfig(courses=[CourseConfig(id='a', name='a', school='院'),
                                CourseConfig(id='b', name='b', school='院', identity='bfx')])
    class Session:
        ready = True
        def __init__(self, slot): pass
        def ensure_login(self, identity, budget):
            if identity == 'bfx': raise IdentityUnavailable('没有辅修入口')
            return True
        def fetch(self, page, budget): return [config.courses[0]], []
        def close(self): pass
    engine = DesktopEngine(config, '', threading.Event(), session_factory=Session,
                           query_budget=FastBudget(), login_budget=FastBudget())
    engine.run()
    assert [r['status'] for r in engine.snapshot()['courses']] == ['elected', 'identity_unavailable']
    engine.close()


def test_explicit_access_restriction_cancels_whole_pool_without_retry():
    config = AppConfig(courses=[CourseConfig(name='a', school='院')])
    queries = []
    class Session:
        ready = True
        def __init__(self, slot): pass
        def ensure_login(self, identity, budget): return True
        def fetch(self, page, budget):
            queries.append(page)
            raise AccessLimitedError()
        def close(self): pass
    engine = DesktopEngine(config, '', threading.Event(), session_factory=Session,
                           query_budget=FastBudget(), login_budget=FastBudget())
    with pytest.raises(AccessLimitedError):
        engine.run()
    assert queries == [1]
    assert engine.stop_event.is_set()
    assert all(not slot.busy for slot in engine.dispatcher.slots)
    engine.close()


def test_captcha_failure_does_not_leave_mutex_reservation_or_invent_a_submission():
    config = AppConfig(courses=[CourseConfig(id='a', name='a', school='院')])
    entered = threading.Event()
    writes = []
    class Session:
        ready = True
        def __init__(self, slot): pass
        def ensure_login(self, identity, budget): return True
        def fetch(self, page, budget):
            return [], [SimpleNamespace(name='a', school='院', class_no=1, status=(10, 9))]
        def prepare(self): entered.set(); raise RetryTurn('captcha failed')
        def submit(self, course): writes.append(course)
        def close(self): pass
    engine = DesktopEngine(config, '', threading.Event(), session_factory=Session,
                           query_budget=FastBudget(), login_budget=FastBudget())
    thread = threading.Thread(target=engine.run)
    thread.start()
    assert entered.wait(1)
    engine.cancel()
    thread.join(2)
    assert not thread.is_alive()
    assert not engine.book.reserved and not engine.book.pending and not writes
    engine.close()
