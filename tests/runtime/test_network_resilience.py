from collections import deque
import json
import threading
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError, ReadTimeout, ChunkedEncodingError, ContentDecodingError

from autoelective.desktop.domain.config import AppConfig, CourseConfig, MutexRule
from autoelective.desktop.runtime.engine import DesktopEngine
from autoelective.desktop.runtime.school_session import SchoolSession, RetryTurn, response_object


def config():
    value = AppConfig(courses=[CourseConfig(id='a', name='课', school='院')])
    value.client['elective_client_pool_size'] = 1
    return value


@pytest.mark.parametrize('error_type', [ConnectionError, ReadTimeout, ChunkedEncodingError, ContentDecodingError])
def test_10000_network_failures_remain_retryable_then_recover(error_type):
    now, logs = [0], deque(maxlen=100)
    cfg = config()
    class Session:
        ready = True
        def __init__(self, sid): self.calls = self.resets = 0
        def ensure_login(self, identity, budget): return False
        def fetch(self, page, budget):
            self.calls += 1
            if self.calls <= 10000: raise error_type('private-network-detail')
            return [cfg.courses[0]], []
        def reset_transport(self): self.resets += 1
        def close(self): pass
    engine = DesktopEngine(cfg, '', threading.Event(), logs.append,
                           session_factory=Session, clock=lambda: now[0])
    try:
        for index in range(10001):
            key, sid = engine.dispatcher.lease(now[0])
            failed, done = engine._turn(key, sid)
            engine.dispatcher.finish(key, sid, now[0], failed=failed, done=done)
            route = engine.dispatcher.routes[key]
            assert not engine.stop_event.is_set() and engine.failure is None
            if index < 10000:
                assert failed and not done
                assert 0 < route.ready_at - now[0] <= 60
                assert len(engine.notices) == 1 and len(engine.errors) == 1
                now[0] = route.ready_at
        assert engine.book.rows['a']['status'] == 'elected'
        assert engine.sessions[1].resets == 10000
        assert not engine.notices and any('[恢复]' in line for line in logs)
        assert 'private-network-detail' not in json.dumps(list(logs))
    finally:
        engine.close()


def test_submission_response_lost_then_outage_never_replays_or_selects_mutex_peer():
    cfg = config()
    cfg.courses.append(CourseConfig(id='b', name='替代课', school='院'))
    cfg.mutexes = [MutexRule(id='m', courses=['a', 'b'])]
    writes = []
    class Session:
        ready = True
        def __init__(self, sid): self.queries = 0
        def ensure_login(self, identity, budget): return False
        def fetch(self, page, budget):
            self.queries += 1
            if 2 <= self.queries < 8: raise ConnectionError('offline')
            elected = [cfg.courses[0]] if self.queries >= 12 else []
            return elected, [SimpleNamespace(name=c.name, school=c.school, class_no=1, status=(10, 9)) for c in cfg.courses]
        def prepare(self): pass
        def submit(self, course):
            writes.append(course.name)
            raise ReadTimeout('response lost after school accepted the write')
        def reset_transport(self): pass
        def close(self): pass
    engine = DesktopEngine(cfg, '', threading.Event(), session_factory=Session)
    try:
        for _ in range(12):
            engine._turn(('bzx', 1), 1)
            assert not engine.stop_event.is_set()
        assert writes == ['课']
        assert engine.book.rows['a']['status'] == 'elected'
        assert engine.book.rows['b']['status'] == 'ignored'
        assert not engine.book.pending and not engine.book.reserved
    finally:
        engine.close()


@pytest.mark.parametrize('payload', [None, [], 'login', 1])
def test_wrong_json_shape_is_transient(payload):
    with pytest.raises(RetryTurn):
        response_object(SimpleNamespace(json=lambda: payload))


def test_truncated_json_is_transient_and_does_not_expose_body():
    def invalid(): raise ValueError('private partial response')
    with pytest.raises(RetryTurn) as caught:
        response_object(SimpleNamespace(json=invalid))
    assert 'private' not in str(caught.value)


def test_invalid_captcha_yields_before_validation_or_submission():
    from autoelective.inference.predictor import preprocess
    session = SchoolSession.__new__(SchoolSession)
    session.client = SimpleNamespace(get_DrawServlet=lambda: SimpleNamespace(content=b'<html>temporary failure</html>'))
    session.recognizer = SimpleNamespace(recognize=preprocess)
    session.recognition_lock = threading.Lock()
    with pytest.raises(RetryTurn, match='验证码内容异常'):
        session.prepare()


def test_transport_reset_retires_connections_without_forcing_login_or_erasing_cookies():
    from requests import Session
    session = SchoolSession.__new__(SchoolSession)
    client = Session()
    client.cookies.set('session', 'fixture-cookie')
    closed = []
    client.close = lambda: closed.append(True)
    session.client = SimpleNamespace(_session=client)
    session.ready, session.initialized = True, True
    session.reset_transport()
    assert closed and not session.initialized and session.ready
    assert client.cookies.get('session') == 'fixture-cookie'


def test_suspend_time_does_not_create_false_stall_but_awake_hang_still_detected():
    elapsed, awake = [100], [10]
    engine = DesktopEngine(config(), '', threading.Event(),
                           session_factory=lambda sid: SimpleNamespace(ready=True, close=lambda: None),
                           clock=lambda: elapsed[0], watchdog_clock=lambda: awake[0])
    try:
        key, sid = engine.dispatcher.lease(elapsed[0])
        engine._phase(sid, key, '查询', 30)
        elapsed[0] += 3600  # A whole hour asleep, not a hung network call.
        assert not engine.snapshot()['stalled']
        awake[0] += 31
        assert engine.snapshot()['stalled']
    finally:
        engine.close()


def test_real_loopback_connection_drop_then_bad_response_then_recovery():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import requests
    attempts = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            attempts.append(1)
            if len(attempts) == 1:
                self.close_connection = True
                return
            body = b'[]' if len(attempts) == 2 else b'{"valid":"2"}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = requests.Session()
    client.trust_env = False
    url = 'http://127.0.0.1:%d/' % server.server_address[1]
    try:
        with pytest.raises(ConnectionError): client.get(url, timeout=1)
        client.close()  # Same pool retirement used by SchoolSession.
        with pytest.raises(RetryTurn): response_object(client.get(url, timeout=1))
        assert response_object(client.get(url, timeout=1)) == {'valid': '2'}
        assert len(attempts) == 3  # No invisible transport-level replay.
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
