"""Own a worker and its descendants for the lifetime of the desktop process."""
import os
import signal
import subprocess


def _resume_primary_thread(process):
    """Popen closes the primary thread handle; reopen it while still suspended."""
    import ctypes
    from ctypes import wintypes
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                    ('thread_id', wintypes.DWORD), ('process_id', wintypes.DWORD),
                    ('priority', wintypes.LONG), ('delta', wintypes.LONG), ('flags', wintypes.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ('Thread32First', 'Thread32Next'):
        getattr(kernel, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        getattr(kernel, name).restype = wintypes.BOOL
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry(size=ctypes.sizeof(ThreadEntry))
        found, thread_ids = kernel.Thread32First(snapshot, ctypes.byref(entry)), []
        while found:
            if entry.process_id == process.pid:
                thread_ids.append(entry.thread_id)
            entry.size = ctypes.sizeof(ThreadEntry)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        # No user code has run. Refuse an ambiguous thread instead of resuming
        # an unrelated/injected thread and leaving the worker hung at startup.
        if len(thread_ids) != 1:
            raise OSError('Unable to identify suspended worker primary thread')
        thread = kernel.OpenThread(2, False, thread_ids[0])  # THREAD_SUSPEND_RESUME
        if not thread:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.ResumeThread(thread) != 1:
                raise OSError('Unable to resume owned worker')
        finally:
            kernel.CloseHandle(thread)
    finally:
        kernel.CloseHandle(snapshot)


def spawn_owned_process(command, **kwargs):
    """Assign the job before a Windows launcher can create any descendants."""
    if os.name == 'nt':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 4  # CREATE_SUSPENDED
    process = subprocess.Popen(command, **kwargs)
    tree = None
    try:
        tree = ProcessTree(process)
        if os.name == 'nt':
            _resume_primary_thread(process)
        return process, tree
    except BaseException:
        if tree:
            tree.kill()
            tree.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        for name in ('stdin', 'stdout', 'stderr'):
            stream = getattr(process, name)
            if stream is not None:
                stream.close()
        raise


class ProcessTree:
    def __init__(self, process):
        self.process = process
        self._job = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class BASIC_LIMIT(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                            ("PerJobUserTimeLimit", ctypes.c_longlong),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in
                            ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                             "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class EXTENDED_LIMIT(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            job = kernel.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            self._kernel = kernel
            self._job = job
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def kill(self):
        if self._job:
            self._kernel.TerminateJobObject(self._job, 1)
        elif os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif self.process.poll() is None:
            self.process.kill()

    def close(self):
        if self._job:
            self._kernel.CloseHandle(self._job)
            self._job = None
