import json
import os

import pytest

from autoelective.desktop.adapters.config_store import ConfigStore, RevisionConflict
from autoelective.desktop.adapters.credentials import CredentialStore
from autoelective.desktop.adapters.ini_codec import export_ini, import_ini
from autoelective.desktop.adapters.portable import PortablePaths
from autoelective.desktop.domain.config import AppConfig, CourseConfig


def test_save_revision_conflict_and_bounded_backups(tmp_path):
    paths = PortablePaths(tmp_path)
    store = ConfigStore(paths)
    config = store.load()
    old = AppConfig.from_dict(config.to_dict())
    for _ in range(5):
        config = store.save(config)
    assert config.revision == 5
    assert len(list(paths.data.glob('settings.json.bak.*'))) == 3
    with pytest.raises(RevisionConflict):
        store.save(old)
    assert store.load().revision == 5


def test_failed_replace_does_not_destroy_saved_configuration(tmp_path, monkeypatch):
    store = ConfigStore(PortablePaths(tmp_path))
    config = store.save(AppConfig())
    original = store.paths.settings.read_bytes()
    def reject(src, dst):
        raise PermissionError('denied')
    monkeypatch.setattr(os, 'replace', reject)
    with pytest.raises(PermissionError):
        store.save(config)
    assert store.paths.settings.read_bytes() == original


def test_future_version_never_overwritten(tmp_path):
    paths = PortablePaths(tmp_path)
    paths.initialize_environment()
    paths.settings.write_text('{"schema_version":99}', encoding='utf8')
    store = ConfigStore(paths)
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.save(AppConfig())
    assert json.loads(paths.settings.read_text(encoding='utf-8'))['schema_version'] == 99


def test_invalid_saved_field_is_reported_before_ui_and_not_overwritten(tmp_path):
    paths = PortablePaths(tmp_path)
    paths.data.mkdir()
    raw = '{"client":{"refresh_interval":"not a number"}}'
    paths.settings.write_text(raw, encoding='utf8')
    store = ConfigStore(paths)
    with pytest.raises(ValueError, match='数字'):
        store.load()
    with pytest.raises(ValueError):
        store.save(AppConfig())
    assert paths.settings.read_text(encoding='utf8') == raw


def test_manual_file_edit_with_same_revision_is_conflict(tmp_path):
    paths = PortablePaths(tmp_path)
    store = ConfigStore(paths)
    config = store.save(AppConfig())
    data = json.loads(paths.settings.read_text(encoding='utf8'))
    data['user']['student_id'] = 'external edit'
    paths.settings.write_text(json.dumps(data), encoding='utf8')
    with pytest.raises(RevisionConflict):
        store.save(config)
    assert json.loads(paths.settings.read_text(encoding='utf-8'))['user']['student_id'] == 'external edit'


def test_ini_preserves_unknown_fields_and_password_requires_explicit_export(tmp_path):
    source = tmp_path / 'source.ini'
    source.write_text('[user]\nstudent_id=123\npassword=100%secret\n[client]\nrefresh_interval=9\ncustom=hello\n[plugin]\noption=value\n[course:a]\nname=数学\nclass=2\nschool=数院\ncustom=keep\n', encoding='utf8')
    config, password = import_ini(source)
    assert password == '100%secret'
    assert config.courses[0].class_no == 2
    target = tmp_path / 'export.ini'
    export_ini(config, target)
    content = target.read_text(encoding='utf8')
    assert '100%secret' not in content
    assert 'custom = keep' in content and 'option = value' in content
    restored, _ = import_ini(target)
    assert restored.courses == config.courses


@pytest.mark.skipif(os.name == 'nt', reason='non-Windows memory-only policy')
def test_non_windows_password_is_memory_only(tmp_path):
    paths = PortablePaths(tmp_path)
    store = CredentialStore(paths)
    store.save('secret')
    assert store.load() == 'secret'
    assert CredentialStore(paths).load() == ''
    with pytest.raises(RuntimeError, match='Windows'):
        store.save('secret', remember=True)
    assert not paths.credentials.exists()
    store.clear()
    assert store.load() == ''


@pytest.mark.skipif(os.name != 'nt', reason='real Windows DPAPI integrity')
def test_windows_dpapi_unicode_and_tampered_ciphertext(tmp_path):
    paths = PortablePaths(tmp_path)
    paths.data.mkdir()
    password = 'Windows 离线测试🔒\x00end'
    CredentialStore(paths).save(password, remember=True)
    encrypted = paths.credentials.read_bytes()
    assert password.encode('utf-8') not in encrypted
    assert CredentialStore(paths).load() == password
    damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    paths.credentials.write_bytes(damaged)
    with pytest.raises(OSError, match='重新输入'):
        CredentialStore(paths).load()
    assert paths.credentials.read_bytes() == damaged


@pytest.mark.skipif(os.name != 'nt', reason='real Windows junction containment')
def test_windows_external_data_junction_is_rejected(tmp_path):
    import subprocess
    root, outside = tmp_path / 'portable', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    junction = root / 'data'
    subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
                   check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match='外部链接'):
            PortablePaths(root).initialize_environment()
        assert list(outside.iterdir()) == []
    finally:
        junction.rmdir()  # Remove the junction itself, never its target.


def test_ini_page_overrides_and_legacy_parser_roundtrip(tmp_path):
    from autoelective.config import AutoElectiveConfig
    from autoelective.desktop.adapters.ini_codec import to_parser
    source = tmp_path / 'pages.ini'
    source.write_text('[client]\nsupply_cancel_page=3\n[course:a]\nname=数学\nclass=1\nschool=数院\n[course:b]\nname=物理\nclass=2\nschool=物院\npage=5\n', encoding='utf8')
    config, _ = import_ini(source)
    assert [c.page for c in config.courses] == [3, 5]
    parser = to_parser(config)
    assert parser.getint('course:a', 'page') == 3
    assert parser.getint('course:b', 'page') == 5
    legacy = object.__new__(AutoElectiveConfig)
    legacy._config = parser
    assert dict(legacy.course_pages) == {'a': 3, 'b': 5}
    assert legacy.page_pool_size == 1
    parser.set('course:a', 'page', '3')
    parser.set('client', 'supply_cancel_page', 'invalid hidden compatibility value')
    assert dict(legacy.course_pages) == {'a': 3, 'b': 5}
    parser.set('client', 'supply_cancel_page', '3')
    assert list(legacy.courses) == ['a', 'b']
    parser.remove_option('course:a', 'page')
    parser.remove_option('client', 'page_pool_size')
    assert legacy.course_pages['a'] == 3
    assert legacy.page_pool_size == 1
