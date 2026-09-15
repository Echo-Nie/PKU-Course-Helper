"""Offline, real legacy-loop pagination integration fixture."""
from pathlib import Path
import sys
import types
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autoelective.environ import Environ, checkpoint
from autoelective.desktop.runtime.worker import worker_main

mode = sys.argv[1]
ready = threading.Event()
runtime = {}


class Predictor:
    def startSession(self): pass
    def closeSession(self): pass


inference = types.ModuleType('autoelective.inference')
inference.OnnxPredictor = Predictor
sys.modules['autoelective.inference'] = inference


def execute():
    import importlib
    import requests.sessions
    from autoelective.config import AutoElectiveConfig
    from autoelective.course import Course
    from autoelective.exceptions import ElectionSuccess
    from autoelective.desktop.runtime.pagination import PageRateLimiter

    sys.modules.pop('autoelective.loop')
    real = importlib.import_module('autoelective.loop')
    state = Environ()
    config = AutoElectiveConfig()
    courses = config.courses
    expected_pages = config.course_pages
    catalog = {expected_pages[cid]: Course(c.name, c.class_no, c.school, status=(10, 9), href=str(expected_pages[cid]))
               for cid, c in courses.items()}
    clients = {}
    writes = []
    reads = []
    elected = []

    def no_network(*args, **kwargs):
        raise AssertionError('Network prohibited in test')

    def budget(self):
        checkpoint()
        state.errors['budget_reservations'] += 1

    def read(client, page):
        reads.append(page)
        clients[page] = client.id
        state.errors['read_page_%d' % page] += 1
        if mode == 'rate_limited':
            from autoelective.hook import check_status_code
            check_status_code(types.SimpleNamespace(status_code=429))
        if mode in ('ambiguous_mutex', 'uncertain_mutex') and len(reads) == 6:
            state.stop_event.set()
        if mode == 'partial' and page == 2:
            if state.errors['read_page_2'] == 3:
                state.stop_event.set()
            return types.SimpleNamespace(_tree='broken', content=b'')
        return types.SimpleNamespace(_tree=page, content=b'')

    def tables(tree):
        return [] if tree == 'broken' else [('plans', tree), ('elected', tree)]

    def submit(client, href):
        page = int(href)
        assert len(set(reads)) == 2, 'Submitted before all target pages were collected'
        assert client.id == clients[page], 'Submitted using another session'
        writes.append(page)
        state.errors['write_page_%d_client_%d' % (page, client.id)] += 1
        if mode == 'ambiguous_mutex':
            from requests import Timeout
            raise Timeout('private-response-must-not-leak')
        if mode == 'uncertain_mutex':
            return types.SimpleNamespace()
        elected.append(catalog[page].to_simplified())
        if mode == 'mutex' or len(writes) == 2:
            state.stop_event.set()
        response = types.SimpleNamespace(_tree=99)
        raise ElectionSuccess(response=response)

    def restricted_logout(client):
        from autoelective.hook import check_status_code
        state.errors['logout_requests'] += 1
        check_status_code(types.SimpleNamespace(status_code=429))

    def restricted_login(client):
        from autoelective.hook import check_status_code
        state.errors['restricted_login_requests'] += 1
        check_status_code(types.SimpleNamespace(status_code=429))

    requests.sessions.Session.send = no_network
    PageRateLimiter.wait = budget
    real.ElectiveClient.has_logined = property(lambda self: getattr(self, '_offline_logged', False) if mode in ('warm', 'iaaa_limited') else True)
    real.ElectiveClient.is_expired = property(lambda self: mode == 'logout_limited')
    if mode == 'logout_limited':
        real.ElectiveClient.logout = restricted_logout
    if mode == 'iaaa_limited':
        real.login_loop_interval = 600
        real.IAAAClient.oauth_home = restricted_login
    real.ElectiveClient.get_SupplyCancel = lambda self, *a: read(self, 1)
    real.ElectiveClient.get_supplement = lambda self, *a, page=1: read(self, page)
    real.ElectiveClient.get_DrawServlet = lambda *a: types.SimpleNamespace(content=b'offline')
    real.ElectiveClient.get_Validate = lambda *a: types.SimpleNamespace(json=lambda: {'valid': '2'})
    real.ElectiveClient.get_ElectSupplement = submit
    real.get_tables = tables
    real.get_courses = lambda table: list(elected)
    real.get_courses_with_detail = lambda table: [catalog[table[1]]]
    real.recognizer.recognize = lambda *a: types.SimpleNamespace(code='TEST')
    runtime['loop'] = real
    ready.set()
    try:
        real.run_elective_loop()
    finally:
        state.errors['write_order_' + ','.join(map(str, writes))] = 1
        state.errors['read_order_' + ','.join(map(str, reads))] = 1
        state.errors['returned_pool_slots'] = real.electivePool.qsize()
        state.errors['queued_relogin_slots'] = real.reloginPool.qsize()


def login():
    from autoelective.environ import interruptible_get
    state = Environ()
    if mode not in ('warm', 'iaaa_limited'):
        state.stop_event.wait()
        return
    while not ready.wait(0.05):
        if state.stop_event.is_set():
            return
    real = runtime['loop']
    if mode == 'iaaa_limited':
        try:
            real.run_iaaa_loop()
        except BaseException:
            state.errors['stop_set_before_guarded_failure'] = int(state.stop_event.is_set())
            raise
        return
    while True:
        client = interruptible_get(real.reloginPool)
        if client is real.killedElective:
            return
        client._offline_logged = True
        state.errors['login_client_%d' % client.id] += 1
        real.electivePool.put_nowait(client)


loop = types.ModuleType('autoelective.loop')
loop.run_iaaa_loop = login
loop.run_elective_loop = execute
loop.recognizer = types.SimpleNamespace(model=Predictor())
sys.modules['autoelective.loop'] = loop
from legacy_harness_engine import LegacyHarnessEngine
sys.exit(worker_main(engine_factory=LegacyHarnessEngine))
