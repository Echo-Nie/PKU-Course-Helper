"""Reproduce Explorer's MOTW DLL blocking and exercise the shipped EXE config."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != 'nt', reason='Windows NTFS and .NET Framework required')
def test_internet_marked_webview_dlls_load_without_unblocking_or_system_changes(tmp_path):
    import webview

    # A private copy of the existing interpreter hosts .NET. Its executable has
    # exactly the shipping name; no installed Python configuration is changed.
    base = Path(sys._base_executable)
    fixed_host = tmp_path / 'PKUCourseHelper.exe'
    plain_host = tmp_path / 'unconfigured.exe'
    shutil.copyfile(base, fixed_host)
    shutil.copyfile(base, plain_host)
    for dependency in base.parent.glob('*.dll'):
        shutil.copyfile(dependency, tmp_path / dependency.name)
    shutil.copyfile(ROOT / 'packaging/PKUCourseHelper.exe.config',
                    tmp_path / 'PKUCourseHelper.exe.config')
    marked = []
    for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll'):
        destination = tmp_path / name
        shutil.copyfile(Path(webview.__file__).parent / 'lib' / name, destination)
        # Add the download mark in a new test directory. Never remove one from
        # a user's download, modify the registry, or alter Machine.config.
        Path(str(destination) + ':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n', encoding='ascii')
        marked.append(destination)
    code = '''import json, sys
import clr
try:
    for dll in sys.argv[1:]:
        clr.AddReference(dll)
except Exception as error:
    print(json.dumps({'loaded': False, 'hresult': hex(int(getattr(error, 'HResult', 0)) & 0xffffffff)}))
    sys.exit(1)
print(json.dumps({'loaded': True}))
'''
    env = dict(os.environ, PYTHONHOME=sys.base_prefix, PYTHONPATH=os.pathsep.join(sys.path),
               PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               TEMP=str(tmp_path), TMP=str(tmp_path), TMPDIR=str(tmp_path))
    def probe(host):
        return subprocess.run([str(host), '-c', code, *(str(path) for path in marked)],
                              env=env, cwd=tmp_path, capture_output=True, text=True,
                              encoding='utf-8', timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    baseline = probe(plain_host)
    assert baseline.returncode == 1, baseline.stderr
    assert json.loads(baseline.stdout)['hresult'] == '0x80131515'
    fixed = probe(fixed_host)
    assert fixed.returncode == 0, fixed.stderr
    assert json.loads(fixed.stdout)['loaded'] is True
    for path in marked:
        assert 'ZoneId=3' in Path(str(path) + ':Zone.Identifier').read_text(encoding='ascii')
