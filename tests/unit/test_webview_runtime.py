from pathlib import Path

import pytest

from autoelective.desktop.adapters.webview_runtime import private_runtime


MARKER = Path(__file__).resolve().parents[2] / 'packaging/install-layout.ini'


def install_fixture(root):
    (root / 'install-layout.ini').write_bytes(MARKER.read_bytes())
    runtime = root / 'runtime/webview2'
    runtime.mkdir(parents=True)
    (runtime / 'msedgewebview2.exe').write_bytes(b'offline fixture, not an executable')
    return runtime


def test_portable_build_uses_existing_system_runtime(tmp_path):
    assert private_runtime(tmp_path) is None


def test_installed_build_selects_owned_runtime(tmp_path):
    expected = install_fixture(tmp_path)
    assert private_runtime(tmp_path) == expected


def test_private_portable_selects_its_runtime_and_rejects_missing_files(tmp_path):
    expected = install_fixture(tmp_path)
    marker = MARKER.with_name('portable-layout.ini')
    (tmp_path / 'install-layout.ini').write_bytes(marker.read_bytes())
    assert private_runtime(tmp_path) == expected
    (expected / 'msedgewebview2.exe').unlink()
    with pytest.raises(RuntimeError, match='重新解压'):
        private_runtime(tmp_path)


def test_installed_build_never_silently_falls_back(tmp_path):
    runtime = install_fixture(tmp_path)
    (runtime / 'msedgewebview2.exe').unlink()
    with pytest.raises(RuntimeError, match='私有 WebView2'):
        private_runtime(tmp_path)


def test_unknown_marker_and_unowned_runtime_are_rejected(tmp_path):
    install_fixture(tmp_path)
    (tmp_path / 'install-layout.ini').write_text('[Installation]\nProductId=other\n', encoding='utf-8')
    with pytest.raises(RuntimeError):
        private_runtime(tmp_path)
    (tmp_path / 'install-layout.ini').unlink()
    with pytest.raises(RuntimeError, match='安装信息缺失'):
        private_runtime(tmp_path)


def test_runtime_link_outside_owned_root_is_rejected(tmp_path):
    root, outside = tmp_path / 'app', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (root / 'install-layout.ini').write_bytes(MARKER.read_bytes())
    try:
        (root / 'runtime').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink privilege is unavailable; native junction test is separate')
    with pytest.raises(RuntimeError):
        private_runtime(root)
    assert list(outside.iterdir()) == []
