import json
from pathlib import Path

from autoelective.desktop import self_test


def make_entry(tmp_path):
    root = Path(__file__).resolve().parents[2]
    entry_root = tmp_path / "entry"
    entry_root.mkdir()
    (entry_root / "desktop.py").write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n" % str(root)
        + "from autoelective.desktop.runtime.worker import worker_main\n"
        "sys.exit(worker_main())\n", encoding="utf-8")
    return entry_root


def test_self_test_worker_uses_real_invalid_config_protocol(tmp_path):
    entry = make_entry(tmp_path)
    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    result = self_test._check_worker(entry, worker_root)
    assert result["passed"]
    assert result["exit_code"] == 2
    assert result["invalid_config_rejected_before_running"]
    assert not (worker_root / "data").exists()


def test_self_test_loads_model_records_evidence_and_cleans_temp(tmp_path, monkeypatch):
    entry = make_entry(tmp_path)
    original = self_test._check_worker
    monkeypatch.setattr(self_test, "_check_worker", lambda root, temporary: original(entry, temporary))
    report_path = tmp_path / "report.json"
    assert self_test.run_self_test(report_path) == 0
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report["passed"]
    assert report["checks"]["model_integrity"]["passed"]
    assert report["checks"]["onnx_session"]["passed"]
    assert report["checks"]["worker_transport"]["passed"]
    assert report["checks"]["desktop_scheduler"]["single_page_uses_all_slots"]
    assert "visual_rendering" in report["not_tested"]
    assert not list(tmp_path.glob(".pku-self-test-*"))


def test_self_test_failure_writes_failed_report(tmp_path, monkeypatch):
    monkeypatch.setattr(self_test.sys, "_MEIPASS", str(tmp_path), raising=False)
    report_path = tmp_path / "report.json"
    assert self_test.run_self_test(report_path) == 1
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert not report["passed"]
    assert report["failure"]["type"] == "FileNotFoundError"
