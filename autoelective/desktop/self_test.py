"""Offline release checks, including real frozen worker pipe bootstrap."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .platform.process_tree import spawn_owned_process
from .runtime.protocol import EventValidator, decode, encode


def _check_desktop_scheduler():
    """Exercise the shipped scheduler with no school clients or credentials."""
    from .domain.config import AppConfig, CourseConfig
    from .runtime.engine import DesktopEngine
    from .runtime.scheduler import FairDispatcher
    config = AppConfig(courses=[CourseConfig(id='primary', name='offline', school='test'),
                                CourseConfig(id='minor', name='offline', school='test', identity='bfx')])

    class OfflineSession:
        ready = True
        def __init__(self, slot):
            self.identity = None
        def ensure_login(self, identity, budget):
            self.identity = identity
            return True
        def fetch(self, page, budget):
            return [c for c in config.courses if c.identity == self.identity], []
        def close(self):
            pass

    engine = DesktopEngine(config, '', threading.Event(), session_factory=OfflineSession)
    try:
        engine.run()
        snapshot = engine.snapshot()
        if len(snapshot['sessions']) != 4 or [c['status'] for c in snapshot['courses']] != ['elected', 'elected']:
            raise RuntimeError('Offline desktop identity/session scheduling failed')
        dispatcher = FairDispatcher([('bzx', 1)], 4)
        slots = []
        for now in range(8):
            key, slot = dispatcher.lease(now)
            slots.append(slot)
            dispatcher.finish(key, slot, now)
        if slots != [1, 2, 3, 4] * 2:
            raise RuntimeError('Global pool rotation failed')
        return {'passed': True, 'session_limit': 4, 'identities': ['bzx', 'bfx'],
                'single_page_uses_all_slots': True, 'school_network_used': False}
    finally:
        engine.close()


def _check_worker(root, temporary_root):
    run_id = uuid.uuid4().hex
    command = ([sys.executable, "--worker"] if getattr(sys, "frozen", False)
               else [sys.executable, str(root / "desktop.py"), "--worker"])
    environment = os.environ.copy()
    environment.update(PKU_AUTOELECTIVE_DATA_DIR=str(temporary_root / "data"),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
                       TEMP=str(temporary_root), TMP=str(temporary_root), TMPDIR=str(temporary_root))
    payload = encode({"version": 1, "type": "start", "run_id": run_id,
                      "config": {}, "password": ""})
    process, tree = spawn_owned_process(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=str(temporary_root), env=environment,
                               start_new_session=os.name != "nt",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        output, diagnostic = process.communicate(payload, timeout=20)
        if process.returncode != 2:
            raise RuntimeError("Invalid worker configuration did not exit with code 2")
        if diagnostic:
            raise RuntimeError("Worker emitted unexpected raw diagnostics")
        validator = EventValidator(run_id)
        messages = [decode(line) for line in output.splitlines()]
        if not messages or not all(validator.accept(message) for message in messages):
            raise RuntimeError("Worker returned an invalid NDJSON event stream")
        if messages[-1].get("type") != "finished" or messages[-1].get("state") != "failed":
            raise RuntimeError("Worker did not reject invalid configuration")
        if any(message.get("state") == "running" for message in messages):
            raise RuntimeError("Worker ran with invalid configuration")
        return {"passed": True, "exit_code": process.returncode, "event_count": len(messages),
                "invalid_config_rejected_before_running": True, "frozen_executable": bool(getattr(sys, "frozen", False))}
    finally:
        if tree is not None:
            tree.kill()
            tree.close()
        elif process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    try:
                        stream.close()
                    except OSError:
                        pass


def run_self_test(report_path):
    """Write machine-readable evidence and return 0 only for all tested checks.

    This does not contact the school or certify visual/WebView2 behavior. The
    worker uses an intentionally invalid configuration and empty credentials.
    """
    from .adapters.config_store import atomic_write

    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    evidence = {"schema_version": 1, "passed": False, "platform": platform.system(),
                "frozen": bool(getattr(sys, "frozen", False)), "checks": {},
                "not_tested": ["live_school_requests", "visual_rendering", "WebView2_user_data_placement",
                               "parent_crash_descendant_cleanup"]}
    started = time.monotonic()
    checks = evidence["checks"]
    try:
        frontend = root / "frontend" / "dist" / "index.html"
        if not frontend.is_file() or frontend.stat().st_size == 0:
            raise FileNotFoundError("Embedded frontend/dist/index.html is missing")
        checks["frontend"] = {"passed": True, "bytes": frontend.stat().st_size}
        checks['desktop_scheduler'] = _check_desktop_scheduler()
        model_dir = root / "resources" / "model"
        manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        model_hash = hashlib.sha256((model_dir / "captcha.onnx").read_bytes()).hexdigest()
        if model_hash != manifest["sha256"]:
            raise ValueError("Model manifest checksum does not match")
        checks["model_integrity"] = {"passed": True, "sha256": model_hash}
        from autoelective.inference import OnnxPredictor
        predictor = OnnxPredictor(model_dir=model_dir)
        try:
            predictor.startSession()
            checks["onnx_session"] = {"passed": True}
        finally:
            predictor.closeSession()
        with tempfile.TemporaryDirectory(prefix=".pku-self-test-", dir=str(report_path.parent)) as temporary:
            checks["worker_transport"] = _check_worker(root, Path(temporary))
        evidence["passed"] = True
    except Exception as error:
        # No account material is used by this command; retain only exception type
        # and a bounded diagnostic to make packaging failures actionable.
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)[:500]}
    evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
    atomic_write(report_path, json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"))
    return 0 if evidence["passed"] else 1
