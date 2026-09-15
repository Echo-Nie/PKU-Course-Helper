"""Real kernel mutex checks; these do not substitute for installer UI testing."""
import ctypes
import os
import uuid

import pytest

from autoelective.desktop.platform.instance import acquire_instance, MAINTENANCE_MUTEX


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Native Windows mutexes required')


@pytest.fixture(autouse=True)
def isolated_mutexes(monkeypatch):
    # Exercise real kernel semantics without acquiring the user's live app or
    # maintenance lease while a real course test is in progress.
    from autoelective.desktop.platform import instance
    suffix = uuid.uuid4().hex
    monkeypatch.setattr(instance, 'APP_MUTEX', 'Local\\PKUAutoElectiveTest-' + suffix)
    maintenance = 'Local\\PKUAutoElectiveMaintenanceTest-' + suffix
    monkeypatch.setattr(instance, 'MAINTENANCE_MUTEX', maintenance)
    monkeypatch.setitem(globals(), 'MAINTENANCE_MUTEX', maintenance)


def test_single_instance_lease_is_released():
    handle, kernel = acquire_instance()
    assert handle
    try:
        duplicate, _ = acquire_instance()
        assert duplicate is None
    finally:
        kernel.CloseHandle(handle)
    handle, kernel = acquire_instance()
    assert handle
    kernel.CloseHandle(handle)


def test_maintenance_blocks_startup_without_leaking_application_lease():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    maintenance = kernel.CreateMutexW(None, False, MAINTENANCE_MUTEX)
    assert maintenance
    try:
        with pytest.raises(RuntimeError, match='安装或卸载正在进行'):
            acquire_instance()
    finally:
        kernel.CloseHandle(maintenance)
    handle, kernel = acquire_instance()
    assert handle
    kernel.CloseHandle(handle)
