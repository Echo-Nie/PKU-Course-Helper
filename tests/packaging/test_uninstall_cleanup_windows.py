"""Native cleanup helper checks using our own copied cmd.exe, never Inno globbing."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell and process identity required')
ROOT = Path(__file__).resolve().parents[2]


def helper_command(pid, image, ready):
    return [str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
            '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT / 'packaging/uninstall_cleanup.ps1'),
            '-UninstallerPid', str(pid), '-ImagePath', str(image), '-ReadyPath', str(ready)]


@pytest.fixture
def cleanup_paths():
    suffix = uuid.uuid4().hex
    temp = Path(os.environ['TEMP']).resolve()
    copy = temp / f'is-{suffix}-uninstall.tmp'
    handshake = temp / f'is-{suffix}.tmp'
    copy.mkdir()
    handshake.mkdir()
    image = copy / '_unins.tmp'
    ready = handshake / 'pku-cleanup-ready.txt'
    shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/cmd.exe', image)
    try:
        yield image, ready
    finally:
        # Only known files in these freshly created, exact fixture directories.
        for path in (image, copy / '_unins-done.tmp', ready):
            path.unlink(missing_ok=True)
        for path in (copy, handshake):
            if path.exists():
                path.rmdir()


def test_cleanup_waits_for_exact_process_then_removes_only_its_copy(cleanup_paths):
    image, ready = cleanup_paths
    child = subprocess.Popen([str(image), '/d', '/q'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             cwd=os.environ['SystemRoot'], creationflags=subprocess.CREATE_NO_WINDOW)
    helper = subprocess.Popen(helper_command(child.pid, image, ready), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 45
        while not ready.exists() and helper.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():
            if helper.poll() is not None:
                _, error = helper.communicate()
                pytest.fail('Cleanup handshake failed: ' + error.decode('utf-8', errors='replace'))
            pytest.fail('Cleanup handshake exceeded 45 seconds')
        assert child.poll() is None
        assert image.is_file(), 'A running executable must not be deleted'
        (image.parent / '_unins-done.tmp').write_bytes(b'')
        child.communicate(b'exit\r\n', timeout=15)
        _, error = helper.communicate(timeout=20)
        assert helper.returncode == 0, error.decode('utf-8', errors='replace')
        assert not image.parent.exists()
        assert ready.is_file(), 'Inno owns its separate handshake directory, not the helper'
    finally:
        for process in (child, helper):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_cleanup_rejects_process_identity_mismatch(cleanup_paths):
    image, ready = cleanup_paths
    original = image.read_bytes()
    result = subprocess.run(helper_command(os.getpid(), image, ready), capture_output=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode != 0
    assert not ready.exists()
    assert image.read_bytes() == original


def test_cleanup_rejects_unrelated_directory(tmp_path):
    image, ready = tmp_path / '_unins.tmp', tmp_path / 'pku-cleanup-ready.txt'
    image.write_bytes(b'Unrelated data must survive')
    result = subprocess.run(helper_command(os.getpid(), image, ready), capture_output=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode != 0
    assert image.read_bytes() == b'Unrelated data must survive'
    assert not ready.exists()
