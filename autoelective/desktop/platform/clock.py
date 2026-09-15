"""Watchdog time excludes suspend/hibernate on Windows; wall time remains for logs."""
import os
import time


if os.name == 'nt':
    import ctypes
    _query = ctypes.WinDLL('kernel32', use_last_error=True).QueryUnbiasedInterruptTime
    _query.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    _query.restype = ctypes.c_int

    def active_time():
        value = ctypes.c_ulonglong()
        if not _query(ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value / 10_000_000
else:
    active_time = time.monotonic
