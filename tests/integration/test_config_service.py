import base64
import json

import pytest

from autoelective.desktop.adapters import config_service
from autoelective.desktop.adapters.config_service import ConfigService
from autoelective.desktop.adapters.portable import PortablePaths
from autoelective.desktop.domain.config import AppConfig


@pytest.fixture
def simulated_dpapi(monkeypatch):
    monkeypatch.setattr(config_service, '_can_remember', lambda: True)
    monkeypatch.setattr(config_service, '_protect', lambda data: b'cipher:' + base64.b64encode(data))
    monkeypatch.setattr(config_service, '_unprotect', lambda data: base64.b64decode(data.removeprefix(b'cipher:')))


def test_memory_password_cannot_follow_account_change(tmp_path):
    service = ConfigService(tmp_path)
    config = AppConfig()
    config.user['student_id'] = '123'
    config = service.save(config, password='secret')
    assert service.password_for(config) == 'secret'
    config.user['student_id'] = '456'
    assert service.password_for(config) == ''
    config = service.save(config)
    assert service.password_for(config) == ''


def test_remembered_password_bound_to_account_and_atomic_reference(tmp_path, simulated_dpapi):
    service = ConfigService(tmp_path)
    config = service.save(AppConfig(), password='secret', remember=True)
    assert 'secret' not in service.paths.settings.read_text(encoding='utf-8')
    ref = config.extra_json['credential_ref']
    assert (service.paths.data / ref).exists()
    restarted = ConfigService(tmp_path)
    loaded = restarted.load()
    assert restarted.password_for(loaded) == 'secret'
    loaded.user['student_id'] = 'different-account'
    assert restarted.password_for(loaded) == ''


def test_failed_config_commit_retains_previous_credentials(tmp_path, simulated_dpapi, monkeypatch):
    service = ConfigService(tmp_path)
    config = service.save(AppConfig(), password='old secret', remember=True)
    original = service.paths.settings.read_bytes()
    def fail(config):
        raise PermissionError('failed')
    monkeypatch.setattr(service.store, 'save', fail)
    with pytest.raises(PermissionError):
        service.save(config, password='new secret', remember=True)
    assert service.paths.settings.read_bytes() == original
    restored = ConfigService(tmp_path)
    assert restored.password_for(restored.load()) == 'old secret'
    assert len(list(service.paths.data.glob('credentials.*.dpapi'))) == 1


def test_forget_removes_all_owned_credentials_and_backup_references(tmp_path, simulated_dpapi):
    service = ConfigService(tmp_path)
    config = service.save(AppConfig(), password='secret', remember=True)
    config = service.save(config, remember=True)
    assert service.password_for(config) == 'secret'
    config = service.save(config, remember=False)
    assert not list(service.paths.data.glob('credentials.*.dpapi'))
    assert not service.remembers(config)
    for backup in service.paths.data.glob('settings.json.bak.*'):
        assert 'credential_ref' not in json.loads(backup.read_text(encoding='utf-8'))


def test_untrusted_credential_reference_cannot_read_outside_data(tmp_path):
    service = ConfigService(tmp_path)
    config = AppConfig()
    config.extra_json.update(credential_ref='../outside', remember_password=True)
    assert service.password_for(config) == ''


def test_restart_reclaims_interrupted_staging_but_keeps_live_ciphertext(tmp_path, simulated_dpapi):
    service = ConfigService(tmp_path)
    config = service.save(AppConfig(), password='secret', remember=True)
    orphan = service.paths.data / ('credentials.' + 'a' * 32 + '.dpapi')
    orphan.write_bytes(b'interrupted staging')
    restarted = ConfigService(tmp_path)
    loaded = restarted.load()
    assert not orphan.exists()
    assert restarted.password_for(loaded) == 'secret'


@pytest.mark.skipif(__import__('os').name != 'nt', reason='real Windows DPAPI integration')
def test_windows_dpapi_real_roundtrip(tmp_path):
    service = ConfigService(tmp_path)
    config = service.save(AppConfig(), password='Windows-only 秘密 123', remember=True)
    blob = service.paths.data / config.extra_json['credential_ref']
    assert b'Windows-only' not in blob.read_bytes()
    restarted = ConfigService(tmp_path)
    loaded = restarted.load()
    assert restarted.password_for(loaded) == 'Windows-only 秘密 123'
    restarted.forget_password(loaded)
    assert not blob.exists()
