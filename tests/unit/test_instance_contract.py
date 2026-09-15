"""API call-order/error tests; real Windows mutex tests live in tests/runtime."""
import ctypes
from types import SimpleNamespace

import pytest

from autoelective.desktop.platform.instance import acquire_instance


class Call:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


@pytest.mark.parametrize('maintenance,code,blocked', [(None, 2, False), (None, 5, True), (84, 0, True)])
def test_maintenance_absence_must_be_confirmed(monkeypatch, maintenance, code, blocked):
    calls = []
    kernel = SimpleNamespace(
        CreateMutexW=Call(lambda *args: calls.append('create_app') or 42),
        OpenMutexW=Call(lambda *args: calls.append('check_maintenance') or maintenance),
        CloseHandle=Call(lambda handle: calls.append(('close', handle))),
    )
    errors = iter([0, code])
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: next(errors), raising=False)
    if blocked:
        with pytest.raises(RuntimeError):
            acquire_instance()
        assert calls[-1] == ('close', 42)
        if maintenance:
            assert ('close', maintenance) in calls
    else:
        assert acquire_instance() == (42, kernel)
        assert len(calls) == 2
    assert calls[:2] == ['create_app', 'check_maintenance']
