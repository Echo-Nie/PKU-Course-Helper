"""Run the real IPC adapter against fake loops, without school network access."""
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autoelective.environ import Environ, checkpoint
from autoelective.desktop.runtime.worker import worker_main

mode = sys.argv[1]
loop = types.ModuleType("autoelective.loop")


def login():
    Environ().stop_event.wait()


def elect():
    from autoelective.config import AutoElectiveConfig
    environment = Environ()
    course = next(iter(AutoElectiveConfig().courses.values()))
    print("raw-engine-output-must-not-escape")
    if mode == "failure":
        raise RuntimeError("raw-exception-secret-must-not-escape")
    if mode in ("complete", "stdio_none"):
        environment.ignored[course] = "Mutex rules"
        return
    environment.pending_courses.add(course)
    environment.stop_event.wait()
    checkpoint()


def ambiguous_submission():
    """Exercise the real course loop with a timed-out write and stale result page."""
    import importlib
    import requests
    from autoelective.config import AutoElectiveConfig
    from autoelective.course import Course
    sys.modules.pop("autoelective.loop")
    real = importlib.import_module("autoelective.loop")
    state = Environ()
    course = next(iter(AutoElectiveConfig().courses.values()))
    available = Course(course.name, course.class_no, course.school, status=(10, 9), href="offline")
    requests.sessions.Session.send = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network prohibited"))
    from autoelective.desktop.runtime.pagination import PageRateLimiter
    PageRateLimiter.wait = lambda self: checkpoint()
    real.ElectiveClient.has_logined = property(lambda self: True)
    real.ElectiveClient.is_expired = property(lambda self: False)
    reads = 0

    def supply(*args):
        nonlocal reads
        reads += 1
        if reads == 3:
            state.stop_event.set()
        return types.SimpleNamespace(_tree=None)

    def submit(*args):
        state.errors["offline_submission_count"] += 1
        if state.errors["offline_submission_count"] > 1:
            raise AssertionError("Unconfirmed write was replayed")
        raise requests.Timeout("private-exception-must-not-leak")

    real.ElectiveClient.get_SupplyCancel = supply
    real.ElectiveClient.get_DrawServlet = lambda *a: types.SimpleNamespace(content=b"offline")
    real.ElectiveClient.get_Validate = lambda *a: types.SimpleNamespace(json=lambda: {"valid": "2"})
    real.ElectiveClient.get_ElectSupplement = submit
    real.recognizer.recognize = lambda *a: types.SimpleNamespace(code="TEST")
    real.get_tables = lambda tree: [None, None]
    real.get_courses = lambda table: []
    real.get_courses_with_detail = lambda table: [available]
    real.run_elective_loop()


if mode in ("legacy_import", "ambiguous"):
    import requests.sessions

    def no_network(*args, **kwargs):
        raise AssertionError("Network is prohibited in offline tests")

    requests.sessions.Session.send = no_network

    class Predictor:
        def __init__(self):
            if mode == "legacy_import":
                Environ().stop_event.set()

        def startSession(self):
            pass

        def closeSession(self):
            pass

    inference = types.ModuleType("autoelective.inference")
    inference.OnnxPredictor = Predictor
    sys.modules["autoelective.inference"] = inference
if mode != "legacy_import":
    loop.run_iaaa_loop = login
    loop.run_elective_loop = ambiguous_submission if mode == "ambiguous" else elect
    loop.recognizer = types.SimpleNamespace(model=types.SimpleNamespace(closeSession=lambda: None))
    sys.modules["autoelective.loop"] = loop
if mode == "stdio_none":
    # PyInstaller console=False sets these to None on Windows.
    sys.stdin = sys.stdout = sys.stderr = None
from legacy_harness_engine import LegacyHarnessEngine
sys.exit(worker_main(engine_factory=LegacyHarnessEngine))
