"""Restore inherited worker pipes in a PyInstaller windowed executable."""
import io
import os
import sys

# Keep wrappers alive when worker_main replaces sys.stdout/stderr with discarders.
_owned_streams = []


def _duplicate_windows_pipe(number):
    """GetStdHandle works even when a /SUBSYSTEM:WINDOWS CRT has no fd 0/1."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                      wintypes.BOOL, wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.GetStdHandle(wintypes.DWORD(-10 - number))
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise OSError("Worker standard pipe is not available")
    process = kernel.GetCurrentProcess()
    duplicate = wintypes.HANDLE()
    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        flags = (os.O_RDONLY if number == 0 else os.O_WRONLY) | os.O_BINARY
        return msvcrt.open_osfhandle(duplicate.value, flags)
    except BaseException:
        kernel.CloseHandle(duplicate)
        raise


def bootstrap_stdio():
    """Provide real binary stdin/stdout without closing inherited OS handles.

    Call only in a worker launched with redirected pipes. A missing output pipe
    fails before loading the model or making network requests.
    """
    for number, name in ((0, "stdin"), (1, "stdout")):
        current = getattr(sys, name)
        if current is not None and hasattr(current, "buffer") and not current.closed:
            continue
        fd = _duplicate_windows_pipe(number) if os.name == "nt" else os.dup(number)
        try:
            binary = io.FileIO(fd, "rb" if number == 0 else "wb", closefd=True)
        except BaseException:
            os.close(fd)
            raise
        stream = io.TextIOWrapper(binary, encoding="utf-8", errors="strict", write_through=True)
        _owned_streams.append(stream)
        setattr(sys, name, stream)
    # Incidental diagnostics are discarded by the worker; no error log handle is needed.
    if sys.stderr is None:
        sys.stderr = io.StringIO()
