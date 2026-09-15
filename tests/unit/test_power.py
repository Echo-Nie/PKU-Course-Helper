import os
import threading

import pytest

from autoelective.desktop.platform.power import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED, RUNNING_FLAGS, SleepProtection, execution_state_api


def test_unattended_request_is_thread_scoped_idempotent_and_holds_display():
    calls = []
    def api(flags):
        calls.append((threading.get_ident(), flags))
        return ES_CONTINUOUS
    protection = SleepProtection(lambda: api, supported=True, execution_factory=None)
    assert protection.acquire()['active']
    assert protection.acquire()['active']
    protection.close()
    protection.close()
    assert calls == [(threading.get_ident(), RUNNING_FLAGS),
                     (threading.get_ident(), ES_CONTINUOUS)]
    assert not protection.status()['active']


@pytest.mark.parametrize('failure', ['rejected', 'exception', 'unsupported'])
def test_request_failure_is_visible_without_changing_power_settings(failure):
    def factory():
        if failure == 'exception': raise OSError('private native details')
        return lambda flags: 0
    protection = SleepProtection(factory, supported=failure != 'unsupported', execution_factory=None)
    status = protection.acquire()
    assert not status['active'] and status['error']
    assert 'private' not in str(status)
    protection.close()


def test_existing_requirements_are_restored_and_release_failure_is_not_hidden():
    calls = []
    def api(flags):
        calls.append(flags)
        return (ES_CONTINUOUS | 2) if len(calls) == 1 else 0 if len(calls) == 2 else ES_CONTINUOUS
    protection = SleepProtection(lambda: api, supported=True, execution_factory=None)
    protection.acquire()
    protection.close()
    assert protection.active and protection.error
    assert calls[-1] == ES_CONTINUOUS | 2
    protection.close()
    assert not protection.active and not protection.error


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows execution-state request')
def test_native_windows_request_is_accepted_and_cleared_on_same_thread():
    api = execution_state_api()
    original = api(ES_CONTINUOUS)
    protection = SleepProtection()
    try:
        assert protection.acquire()['active']
        assert protection.status()['execution_required']
        request = protection.execution
        assert request.handle is not None
        requested = api(0)  # Read previous flags; only resets this thread's idle timer.
        assert requested & ES_SYSTEM_REQUIRED
        assert requested & ES_DISPLAY_REQUIRED
        assert not protection.status()['allows_display_sleep']
        protection.close()
        assert not protection.active
        assert request.handle is None and not protection.status()['execution_required']
        assert not api(0) & ES_SYSTEM_REQUIRED
    finally:
        protection.close()
        api(ES_CONTINUOUS | original)


def test_execution_request_failure_does_not_report_full_protection_and_releases_partial_request():
    calls = []
    def api(flags): calls.append(flags); return ES_CONTINUOUS
    def denied(): raise OSError('private request details')
    protection = SleepProtection(lambda: api, supported=True, execution_factory=denied)
    status = protection.acquire()
    assert not status['active'] and status['error']
    assert 'private' not in str(status)
    protection.close()
    assert calls == [RUNNING_FLAGS, ES_CONTINUOUS]


def test_execution_request_is_closed_once_on_the_owning_thread():
    closed = []
    class Request:
        def close(self): closed.append(threading.get_ident())
    protection = SleepProtection(lambda: lambda flags: ES_CONTINUOUS, supported=True, execution_factory=Request)
    assert protection.acquire()['execution_required']
    protection.close()
    protection.close()
    assert closed == [threading.get_ident()]


def test_renewal_over_many_days_does_not_leak_requests_or_lose_original_flags():
    live, closed, flags = set(), [], []
    class Request:
        def __init__(self):
            self.handle = object()
            live.add(self.handle)
        def close(self):
            live.remove(self.handle)
            closed.append(self.handle)
            self.handle = None
    def api(value):
        flags.append(value)
        return ES_CONTINUOUS | 2
    protection = SleepProtection(lambda: api, supported=True, execution_factory=Request)
    protection.acquire()
    for _ in range(2880):  # One day of 30-second renewals; no real-time wait.
        assert protection.refresh()['active']
        assert len(live) == 1
    protection.close()
    assert not live and len(closed) == 2881
    assert flags[-1] == ES_CONTINUOUS | 2


def test_failed_renewal_recovers_without_losing_thread_state():
    attempts = []
    def api(flags):
        attempts.append(flags)
        return 0 if len(attempts) == 2 else ES_CONTINUOUS
    protection = SleepProtection(lambda: api, supported=True, execution_factory=None)
    assert protection.acquire()['active']
    assert not protection.refresh()['active']
    assert protection.refresh()['active']
    protection.close()
    assert attempts[-1] == ES_CONTINUOUS
