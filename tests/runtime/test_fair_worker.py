import json
import os
from pathlib import Path
import sys
import pytest

from autoelective.desktop.domain.config import AppConfig, CourseConfig, MutexRule
from autoelective.desktop.runtime.protocol import encode


def launch(tmp_path, mode, factory, executable=None):
    config = AppConfig(courses=[CourseConfig(id='a', name='同名课程', school='院', page=2),
                                CourseConfig(id='b', name='同名课程', school='院', identity='bfx')])
    if mode in ('wait', 'unknown-tips'):
        config.mutexes = [MutexRule(courses=['a', 'b'])]
    config.user['student_id'] = 'offline'
    child = factory([executable or sys.executable, str(Path(__file__).with_name('fair_worker_harness.py')), mode],
                    env=dict(os.environ, PKU_AUTOELECTIVE_DATA_DIR=str(tmp_path)))
    child.send(encode(dict(type='start', version=1, run_id='fair', config=config.to_dict(), password='private-pipe-only')))
    return child


@pytest.mark.parametrize('windowless', [False, True])
def test_real_fair_worker_completes_both_identities_and_reports_bounded_pool(tmp_path, worker_factory, windowless):
    executable = Path(sys.executable).with_name('pythonw.exe') if windowless else Path(sys.executable)
    if not executable.exists():
        pytest.skip('Windows windowless interpreter unavailable')
    child = launch(tmp_path, 'complete', worker_factory, str(executable))
    messages = []
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'finished': break
    assert child.wait(3) == 0
    assert messages[-1]['state'] == 'completed'
    final = [m['data'] for m in messages if m['type'] == 'snapshot'][-1]
    assert [c['status'] for c in final['courses']] == ['elected', 'elected']
    assert [c['identity'] for c in final['courses']] == ['bzx', 'bfx']
    assert final['session_limit'] == 4 and len(final['sessions']) == 4
    assert not final['power']['active']
    if os.name == 'nt':
        assert any('系统、显示和进程持续运行请求已启用' in m.get('message', '') for m in messages)
        assert any('已释放本任务' in m.get('message', '') for m in messages)
    assert 'private-pipe-only' not in json.dumps(messages)


def test_real_fair_worker_preserves_uncertainty_on_stop_and_never_writes_mutex_peer(tmp_path, worker_factory):
    child = launch(tmp_path, 'wait', worker_factory)
    messages = []
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'snapshot' and event['data']['unconfirmed_count']:
            break
    child.send(encode({'type': 'stop'}))
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'finished': break
    assert child.wait(3) == 0 and messages[-1]['state'] == 'stopped'
    assert sum(m.get('message') == 'offline-write-count' for m in messages) == 1
    final = [m['data'] for m in messages if m['type'] == 'snapshot'][-1]
    assert sum(c['status'] == 'unconfirmed' for c in final['courses']) == 1
    assert not any(s['busy'] for s in final['sessions'])
    assert not final['power']['active']
    assert 'private-timeout' not in json.dumps(messages)


def test_real_fair_worker_access_restriction_stops_without_secret_output(tmp_path, worker_factory):
    child = launch(tmp_path, 'restricted', worker_factory)
    messages = []
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'finished': break
    assert child.wait(3) == 1 and messages[-1]['state'] == 'failed'
    assert 'private-exception' not in json.dumps(messages)
    assert any('限制访问' in m.get('message', '') for m in messages)
    assert not [m['data'] for m in messages if m['type'] == 'snapshot'][-1]['power']['active']


def test_initialization_failure_releases_power_request_before_failed_exit(tmp_path, worker_factory):
    child = launch(tmp_path, 'initialization-failure', worker_factory)
    messages = []
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'finished': break
    assert child.wait(3) == 1
    assert messages[-1]['state'] == 'failed'
    if os.name == 'nt':
        assert any('已释放本任务' in m.get('message', '') for m in messages)
    assert 'private-initialization-error' not in json.dumps(messages)


def test_unknown_school_tips_reach_real_worker_ipc_without_secrets_or_replayed_write(tmp_path, worker_factory):
    child = launch(tmp_path, 'unknown-tips', worker_factory)
    messages = []
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'snapshot' and event['data']['unconfirmed_count']:
            break
    child.send(encode({'type': 'stop'}))
    while True:
        event = child.receive()
        messages.append(event)
        if event['type'] == 'finished': break
    assert child.wait(3) == 0 and messages[-1]['state'] == 'stopped'
    assert any('未知错误警告' in m.get('message', '') and '新的学校反馈' in m['message'] for m in messages)
    assert sum(m.get('message') == 'offline-write-count' for m in messages) == 1
    assert 'private-pipe-only' not in json.dumps(messages) and 'private-school-token' not in json.dumps(messages)
