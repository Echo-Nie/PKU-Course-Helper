"""Development uses production validation/IPC; never contact the school in QA."""
import json

from desktop_dev import DevelopmentBridge
from autoelective.desktop.adapters.portable import PortablePaths
from autoelective.desktop.runtime.supervisor import Signal


class Supervisor:
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

    def shutdown(self, timeout_ms):
        self.stop()
        return True


def configured(bridge):
    raw = bridge.bootstrap()['config']
    raw['user']['student_id'] = 'offline-test-account'
    raw['courses'] = [dict(id='test-a', name='测试课程', school='测试院', class_no=1)]
    return raw


def test_live_development_uses_production_start_and_stop_without_password_on_disk(tmp_path):
    supervisor = Supervisor()
    bridge = DevelopmentBridge(PortablePaths(tmp_path), supervisor, live=True)
    info = bridge.bootstrap()
    assert info['live'] and info['development'] and not info['preview']
    assert not info['config']['courses'] and not supervisor.started
    result = bridge.start(configured(bridge), 'memory-only-test-secret', True)
    assert result['ok'] and not result['remembered']
    assert len(supervisor.started) == 1
    assert supervisor.started[0][1] == 'memory-only-test-secret'
    assert 'memory-only-test-secret' not in (tmp_path / 'data/settings.json').read_text(encoding='utf-8')
    assert not list(tmp_path.rglob('*.dpapi'))
    assert bridge.stop()['ok'] and bridge.poll()['state'] == 'stopped'


def test_hot_reload_bootstrap_recovers_running_state_without_restarting_or_mutating_run(tmp_path):
    supervisor = Supervisor()
    bridge = DevelopmentBridge(PortablePaths(tmp_path), supervisor, live=True)
    result = bridge.start(configured(bridge), 'test-secret')
    supervisor.snapshot_received.emit({'courses': [{'id': 'test-a', 'status': 'waiting'}]})
    supervisor.log_received.emit('模拟运行日志')
    edited = result['config']
    edited['courses'][0]['name'] = '下次运行课程'
    assert bridge.save(edited)['ok']
    for _ in range(3):
        reloaded = bridge.bootstrap()
        assert reloaded['runtime']['state'] == 'running'
        assert reloaded['runtime']['snapshot']['courses'][0]['status'] == 'waiting'
        assert len(reloaded['runtime']['logs']) == 1
        assert 'test-secret' not in json.dumps(reloaded)
    assert len(supervisor.started) == 1
    assert supervisor.started[0][0]['courses'][0]['name'] == '测试课程'
    assert not bridge.start(reloaded['config'])['ok']
    assert bridge._shutdown()


def test_offline_mode_remains_blocked_and_live_validates_before_start(tmp_path):
    supervisor = Supervisor()
    bridge = DevelopmentBridge(PortablePaths(tmp_path), supervisor)
    assert bridge.bootstrap()['preview'] and not bridge.bootstrap()['live']
    assert not bridge.start(configured(bridge), 'test-secret')['ok']
    assert not supervisor.started
    live = DevelopmentBridge(PortablePaths(tmp_path / 'live'), supervisor, live=True)
    assert not live.start(live.bootstrap()['config'])['ok']
    assert not supervisor.started
