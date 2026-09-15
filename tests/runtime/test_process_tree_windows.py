"""Native Windows evidence: no simulated jobs or processes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows Job Object integration")


@pytest.mark.parametrize("crash_parent", [False, True], ids=["close-job", "parent-crash"])
def test_job_reclaims_worker_and_grandchild(crash_parent):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    unrelated = None
    parent = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("process_tree_harness.py")), "parent"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    handles = []
    messages = Queue()
    reader = threading.Thread(target=lambda: messages.put(parent.stdout.readline()), daemon=True)
    reader.start()
    try:
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            line = messages.get(timeout=30)
        except Empty:
            pytest.fail("Native job fixture did not become ready within 30 seconds")
        assert line, "Native job fixture exited before creating its descendants"
        pids = json.loads(line)
        for pid in pids.values():
            handle = kernel.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | TERMINATE
            assert handle, ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        if crash_parent:
            parent.kill()  # Windows must close the job handle without finally.
        else:
            parent.stdin.write("close\n")
            parent.stdin.flush()
        parent.wait(timeout=15)
        if not crash_parent:
            assert parent.returncode == 0, parent.stderr.read()
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 10_000) == 0, "Owned descendant survived"
        assert unrelated.poll() is None, "Job cleanup killed an unrelated Python process"
    finally:
        if unrelated is not None:
            if unrelated.poll() is None:
                unrelated.kill()
            unrelated.wait(timeout=10)
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) == 258:
                kernel.TerminateProcess(handle, 1)
                kernel.WaitForSingleObject(handle, 5_000)
            kernel.CloseHandle(handle)
        reader.join(timeout=2)
        for stream in (parent.stdin, parent.stdout, parent.stderr):
            stream.close()
