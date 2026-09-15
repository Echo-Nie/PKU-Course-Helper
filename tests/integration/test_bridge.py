from autoelective.desktop.bridge import DesktopBridge
from autoelective.desktop.adapters.portable import PortablePaths
from autoelective.desktop.runtime.supervisor import Signal


class FakeSupervisor:
    def __init__(self):
        self.state_changed, self.snapshot_received, self.log_received = Signal(), Signal(), Signal()
        self.is_active = False
        self.started = []
    def start(self, config, password):
        self.started.append((config, password))
        self.is_active = True
        self.state_changed.emit('running')
    def stop(self):
        self.is_active = False
        self.state_changed.emit('stopped')
    def shutdown(self, timeout_ms=5000):
        self.stop()
        return True


def test_desktop_password_is_session_only_even_for_old_remember_calls_and_after_clear(tmp_path):
    bridge = DesktopBridge(PortablePaths(tmp_path), FakeSupervisor())
    for _ in range(2):
        config = bridge.bootstrap()['config']
        result = bridge.save(config, 'memory-only-secret', True)
        assert result['ok'] and result['remembered'] is False
        assert not list((tmp_path / 'data').glob('*.dpapi'))
        restarted = DesktopBridge(PortablePaths(tmp_path), FakeSupervisor())
        assert restarted._service.password_for(restarted._service.load()) == ''
        assert bridge.clear_data()['ok']


def test_bridge_metadata_hides_automatic_and_fixed_fields(tmp_path):
    result = DesktopBridge(PortablePaths(tmp_path), FakeSupervisor()).bootstrap()
    assert result['config']['user'] == {'student_id': ''}
    keys = {field['key'] for field in result['fields']}
    assert not keys.intersection({'page_pool_size', 'print_mutex_rules', 'supply_cancel_page'})
    assert result['config']['client']['elective_client_pool_size'] == 4


def test_invalid_config_never_starts_worker(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    config = bridge.bootstrap()['config']
    result = bridge.start(config, '', False)
    assert not result['ok']
    assert result['issues'][0]['field_path'] == 'user.student_id'
    assert not worker.started


def test_password_not_returned_or_written_and_account_changes_clear_it(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    config = bridge.bootstrap()['config']
    config['user']['student_id'] = 'test-account'
    config['courses'] = [dict(id='a',name='图论',school='数学',class_no=1)]
    result = bridge.start(config, 'TEST-SECRET', False)
    assert result['ok']
    assert 'TEST-SECRET' not in repr(result)
    assert worker.started[0][1] == 'TEST-SECRET'
    assert 'TEST-SECRET' not in (tmp_path / 'data/settings.json').read_text(encoding='utf-8')
    bridge.stop()
    updated = result['config']
    updated['user']['student_id'] = 'different-account'
    result = bridge.start(updated, '', False)
    assert not result['ok']


def test_clear_rejected_during_run_then_removes_owned_data(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    bridge.bootstrap()
    worker.is_active = True
    assert not bridge.clear_data()['ok']
    worker.is_active = False
    assert bridge.clear_data()['ok']
    assert bridge.poll()['logs'] == []


def test_clear_recreates_portable_tmp_and_reports_deferred_profile(tmp_path, monkeypatch):
    import os
    import tempfile
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setattr(tempfile, 'tempdir', None)
    paths = PortablePaths(tmp_path).initialize_environment()
    bridge = DesktopBridge(paths, FakeSupervisor())
    bridge._window = object()
    (paths.tmp / 'old.tmp').write_text('old', encoding='utf-8')
    result = bridge.clear_data()
    assert result['ok'] and result['cache_pending_exit']
    assert not (paths.tmp / 'old.tmp').exists()
    with tempfile.NamedTemporaryFile() as handle:
        assert paths.tmp == __import__('pathlib').Path(handle.name).parent


def test_shutdown_blocks_late_mutations_and_reports_termination_failure(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    config = bridge.bootstrap()['config']
    worker.shutdown = lambda **kw: False
    assert bridge._shutdown() is False
    assert bridge.save(config)['ok']  # Closing was canceled, editing remains possible.
    assert bridge.stop()['ok']
    worker.shutdown = lambda **kw: True
    assert bridge._shutdown() is True
    assert not bridge.start(config)['ok']
    assert not bridge.save(config)['ok']
    assert not bridge.clear_data()['ok']
    assert not worker.started


def test_launch_failure_returns_committed_revision_for_retry(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    config = bridge.bootstrap()['config']
    config['user']['student_id'] = 'test-account'
    config['courses'] = [dict(id='a', name='图论', school='数学', class_no=1, page=2)]
    def fail_start(*args):
        raise OSError('simulated process launch failure')
    worker.start = fail_start
    result = bridge.start(config, 'TEST-SECRET', False)
    assert result['ok'] is False
    assert result['committed'] is True
    assert result['config']['revision'] == config['revision'] + 1
    assert result['remembered'] is False
    assert 'TEST-SECRET' not in repr(result)
    retry = bridge.save(result['config'], 'TEST-SECRET', False)
    assert retry['ok'] is True
    assert retry['config']['revision'] == result['config']['revision'] + 1


def test_rejected_start_does_not_claim_configuration_was_committed(tmp_path):
    worker = FakeSupervisor()
    bridge = DesktopBridge(PortablePaths(tmp_path), worker)
    config = bridge.bootstrap()['config']
    worker.is_active = True
    result = bridge.start(config)
    assert result['ok'] is False
    assert not result.get('committed')
    assert 'config' not in result
    assert not (tmp_path / 'data/settings.json').exists()
