"""Real desktop IPC + real fair scheduler, entirely simulated school sessions."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests
requests.sessions.Session.send = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Network prohibited'))

from autoelective.desktop.runtime.engine import DesktopEngine
from autoelective.desktop.runtime.scheduler import FifoBudget
from autoelective.desktop.runtime.worker import worker_main
from autoelective.exceptions import AccessLimitedError

mode = sys.argv[1]


def engine_factory(config, password, stop_event, log):
    if mode == 'initialization-failure':
        raise RuntimeError('private-initialization-error')
    class Session:
        ready = True
        def __init__(self, slot):
            self.slot, self.identity = slot, None
        def ensure_login(self, identity, budget):
            self.identity = identity
            return True
        def fetch(self, page, budget):
            budget.wait()
            if mode == 'restricted':
                raise AccessLimitedError('private-exception-must-not-escape')
            goals = [c for c in config.courses if c.identity == self.identity and c.page == page]
            if mode == 'complete':
                return goals, []
            return [], [SimpleNamespace(name=c.name, school=c.school, class_no=c.class_no,
                                         status=(10, 9), href='/offline') for c in goals]
        def prepare(self):
            pass
        def submit(self, course):
            log('offline-write-count')
            if mode == 'unknown-tips':
                from autoelective import hook
                response = requests.Response()
                response.encoding = 'utf-8'
                response._content = '<html><table><tr><td id="msgTips">新的学校反馈 private-pipe-only token=private-school-token</td></tr></table></html>'.encode('utf-8')
                response.request = SimpleNamespace()
                hook.with_etree(response)
                hook.check_elective_tips(response)
                raise AssertionError('Unknown desktop tips were swallowed')
            raise requests.Timeout('private-timeout-must-not-escape')
        def invalidate(self):
            self.ready = False
        def close(self):
            pass
    return DesktopEngine(config, password, stop_event, log, session_factory=Session,
                         query_budget=FifoBudget(0.01), login_budget=FifoBudget(0.01))


sys.exit(worker_main(engine_factory=engine_factory))
