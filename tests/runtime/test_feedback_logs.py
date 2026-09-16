import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

from autoelective import exceptions as errors
from autoelective.desktop.domain.config import AppConfig, CourseConfig
from autoelective.desktop.runtime.engine import DesktopEngine


def test_actual_hooks_deliver_unknown_system_tips_and_pe_warning_to_desktop(tmp_path):
    cases = [('system', 'Token无效'), ('system', '[310] 您尚未登录或者会话超时，请重新登录。'),
             ('system', '新的系统反馈 token=private-token'), ('tips', '学校规定每学期只能修一门体育课。'),
             ('tips', '新的提示 fixture-password 学号=0000000000'), ('malformed', ''),
             ('empty', ''), ('auth-list', '')]
    result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('feedback_hook_harness.py'))],
                            input=json.dumps(cases), text=True, encoding='utf-8', capture_output=True, timeout=15,
                            env=dict(os.environ, PKU_AUTOELECTIVE_DATA_DIR=str(tmp_path)))
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert [r['kind'] for r in rows] == ['InvalidTokenError', 'SessionExpiredError', 'SystemException',
                                       'MultiPECourseError', 'TipsException', 'SystemException',
                                       'UnexpectedHTMLFormat', 'IAAANotSuccessError']
    assert all(r['response_retained'] for r in rows)
    assert '未知错误警告' in rows[2]['log'] and '未知错误警告' in rows[4]['log']
    for secret in ('fixture-password', '0000000000', 'private-token', 'do-not-log-whole-page'):
        assert secret not in result.stdout


def test_repeated_errors_are_merged_but_a_different_unknown_message_is_not_lost():
    now, message, logs = [0], ['新反馈一'], []
    config = AppConfig(courses=[CourseConfig(name='课', school='院')])
    class Session:
        ready = True
        def __init__(self, sid): pass
        def ensure_login(self, identity, budget): return False
        def fetch(self, page, budget): raise errors.SystemException(msg=message[0])
        def close(self): pass
    engine = DesktopEngine(config, '', threading.Event(), logs.append, session_factory=Session, clock=lambda: now[0])
    try:
        for _ in range(100): engine._turn(('bzx', 1), 1)
        assert len(logs) == 1 and '本段累计 1 次' in logs[0]
        now[0] = 60
        engine._turn(('bzx', 1), 1)
        assert len(logs) == 2 and '101 次' in logs[-1]
        message[0] = '新反馈二'
        engine._turn(('bzx', 1), 1)
        assert len(logs) == 3 and '新反馈二' in logs[-1]
        assert len(engine.notices) == 1
        assert '阶段：' in logs[-1] and '主修 · 第 1 页' in logs[-1]
    finally:
        engine.close()


def test_unknown_submission_feedback_is_logged_and_does_not_allow_replay():
    logs, writes = [], []
    config = AppConfig(courses=[CourseConfig(id='a', name='测试课', school='测试院')])
    config.user['student_id'] = '0000000000'
    class Session:
        ready = True
        def __init__(self, sid): pass
        def ensure_login(self, identity, budget): return False
        def fetch(self, page, budget): return [], [SimpleNamespace(name='测试课', school='测试院', class_no=1, status=(10, 9))]
        def prepare(self): pass
        def submit(self, course):
            writes.append(True)
            raise errors.TipsException(msg='新的未知反馈 fixture-secret token=server-token')
        def close(self): pass
    engine = DesktopEngine(config, 'fixture-secret', threading.Event(), logs.append, session_factory=Session)
    try:
        engine._turn(('bzx', 1), 1)
        assert engine.book.snapshot()[0]['status'] == 'unconfirmed'
        assert any('未知错误警告' in line and '测试课' in line and '提交选课' in line for line in logs)
        assert 'fixture-secret' not in '\n'.join(logs) and 'server-token' not in '\n'.join(logs)
        engine._turn(('bzx', 1), 1)
        assert len(writes) == 1
    finally:
        engine.close()
