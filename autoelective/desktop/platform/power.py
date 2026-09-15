"""Thread-scoped Windows idle-sleep protection; never edits a power plan."""
import os
import threading
import ctypes
from ctypes import wintypes
from functools import lru_cache


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
RUNNING_FLAGS = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED


def execution_state_api():
    function = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
    function.argtypes = [wintypes.DWORD]
    function.restype = wintypes.DWORD
    return function


# ctypes caches POINTER types globally. Define these once, not at each periodic
# renewal, or an unattended process accumulates native type objects forever.
class _DetailedReason(ctypes.Structure):
    _fields_ = [('module', wintypes.HMODULE), ('reason_id', wintypes.ULONG),
                ('count', wintypes.ULONG), ('strings', ctypes.POINTER(wintypes.LPWSTR))]


class _Reason(ctypes.Union):
    _fields_ = [('detailed', _DetailedReason), ('simple', wintypes.LPWSTR)]


class _ReasonContext(ctypes.Structure):
    _fields_ = [('version', wintypes.ULONG), ('flags', wintypes.DWORD), ('reason', _Reason)]


@lru_cache(maxsize=1)
def power_request_api():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.PowerCreateRequest.argtypes = [ctypes.POINTER(_ReasonContext)]
    kernel.PowerCreateRequest.restype = wintypes.HANDLE
    for name in ('PowerSetRequest', 'PowerClearRequest'):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.c_int]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


class ExecutionRequest:
    """Modern Standby process-lifetime request, one handle per active worker."""
    def __init__(self):
        self.kernel = power_request_api()
        context = _ReasonContext(version=0, flags=1)
        context.reason.simple = 'PKUCourseHelper正在查询和确认目标课程；任务结束后释放。'
        self.handle = self.kernel.PowerCreateRequest(ctypes.byref(context))
        self.enabled = []
        if not self.handle or self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise OSError('Power request creation failed')
        for kind in (0, 1, 3):  # Display, System AND Execution for unattended S3/S0 operation.
            if not self.kernel.PowerSetRequest(self.handle, kind):
                self.close()
                raise OSError('Power request failed')
            self.enabled.append(kind)

    def close(self):
        if self.handle is None:
            return
        cleared = True
        for kind in self.enabled:
            cleared = bool(self.kernel.PowerClearRequest(self.handle, kind)) and cleared
        closed = bool(self.kernel.CloseHandle(self.handle))
        if closed:
            self.handle, self.enabled = None, []
        if not cleared or not closed:
            raise OSError('Power request cleanup failed')


class SleepProtection:
    """Acquire/release on the worker's main thread; process exit also releases it.

    Requests complement the supervisor's verified scheme. Display is held too
    because unattended operation takes priority over display power saving.
    """
    def __init__(self, api_factory=execution_state_api, supported=None, execution_factory=ExecutionRequest):
        self.supported = os.name == 'nt' if supported is None else supported
        self.api_factory, self.api = api_factory, None
        self.active, self.error = False, ''
        self.owner, self.previous = None, ES_CONTINUOUS
        self.execution_factory, self.execution = execution_factory, None

    def acquire(self):
        if self.active and not self.error:
            return self.status()
        if not self.supported:
            self.error = '当前系统不支持此防自动睡眠功能；请保持电脑唤醒。'
            return self.status()
        try:
            self.api = self.api_factory()
            if not self.active:
                previous = self.api(RUNNING_FLAGS)
                if not previous:
                    raise OSError('Execution-state request rejected')
                self.previous, self.owner = previous, threading.get_ident()
            self.active, self.error = True, ''
            if self.execution_factory is not None and self.execution is None:
                self.execution = self.execution_factory()
        except Exception:
            self.error = '防自动睡眠申请失败；请检查电源策略并保持电脑唤醒，选课仍继续。'
        return self.status()

    def refresh(self):
        """Renew on the owning thread after resume and periodically, without counters growing."""
        if not self.active:
            return self.acquire()
        if threading.get_ident() != self.owner:
            raise RuntimeError('Sleep protection must be refreshed on its owning thread')
        try:
            if not self.api(RUNNING_FLAGS):
                raise OSError('Execution-state renewal rejected')
            if self.execution is not None:
                request = self.execution
                try:
                    request.close()
                except OSError:
                    if getattr(request, 'handle', None) is not None:
                        raise
                finally:
                    # A retired/expired request can fail ClearRequest but still
                    # close its handle. Do not retain a closed handle as active.
                    if getattr(request, 'handle', None) is None:
                        self.execution = None
            if self.execution_factory is not None:
                self.execution = self.execution_factory()
            self.error = ''
        except Exception:
            self.error = '持续运行请求续期失败，正在重试；请保持电脑唤醒。'
        return self.status()

    def close(self):
        if not self.active and self.execution is None:
            return
        if threading.get_ident() != self.owner:
            raise RuntimeError('Sleep protection must be released on its owning thread')
        cleanup_error = ''
        if self.execution is not None:
            try:
                self.execution.close()
                self.execution = None
            except Exception:
                cleanup_error = '进程持续运行请求未能主动释放；工作进程退出后由 Windows 回收。'
        try:
            # Restore only this thread's prior requirements, not other apps'.
            if not self.api(ES_CONTINUOUS | self.previous):
                raise OSError('Execution-state release rejected')
            self.active, self.error = False, ''
        except Exception:
            cleanup_error = '防自动睡眠请求未能主动释放；选课工作进程退出后由 Windows 回收。'
        self.error = cleanup_error

    def status(self):
        return {'active': self.active and not self.error, 'supported': self.supported, 'error': self.error,
                'execution_required': self.execution is not None,
                'allows_display_sleep': False}
