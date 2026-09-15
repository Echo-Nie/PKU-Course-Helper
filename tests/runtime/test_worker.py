import json
import os
from pathlib import Path
import sys

from autoelective.desktop.domain.config import AppConfig, CourseConfig
from autoelective.desktop.runtime.protocol import encode


def launch(tmp_path, mode, worker_factory):
    config = AppConfig()
    config.user["student_id"] = "1234567890"
    config.courses = [CourseConfig(id="test", name="离线课程", class_no=1, school="测试学院")]
    environment = dict(os.environ, PKU_AUTOELECTIVE_DATA_DIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    child = worker_factory([sys.executable, str(Path(__file__).with_name("worker_harness.py")), mode], env=environment)
    child.send(encode(dict(type="start", version=1, run_id="test-run", config=config.to_dict(), password="private-only-in-pipe")))
    return child


def receive(child):
    return child.receive()


def collect(child):
    messages = []
    while True:
        event = receive(child)
        messages.append(event)
        if event["type"] == "finished":
            break
    assert child.wait(timeout=3) in (0, 1)
    return messages


def test_real_adapter_completes_with_accurate_ignore_status_and_no_raw_logs(tmp_path, worker_factory):
    child = launch(tmp_path, "complete", worker_factory)
    messages = collect(child)
    assert messages[-1]["state"] == "completed"
    snapshots = [m["data"] for m in messages if m["type"] == "snapshot"]
    assert snapshots[-1]["courses"][0]["status"] == "ignored"
    assert "private-only-in-pipe" not in json.dumps(messages)
    assert "raw-engine-output" not in json.dumps(messages)
    assert child.stderr == b""


def test_stop_preserves_in_flight_uncertainty(tmp_path, worker_factory):
    child = launch(tmp_path, "wait", worker_factory)
    while True:
        message = receive(child)
        if message["type"] == "snapshot" and message["data"]["unconfirmed_count"]:
            break
    child.send(encode({"type": "stop"}))
    messages = collect(child)
    assert messages[-1]["state"] == "stopped"
    snapshots = [m["data"] for m in messages if m["type"] == "snapshot"]
    assert snapshots[-1]["courses"][0]["status"] == "unconfirmed"


def test_parent_pipe_eof_terminates_worker(tmp_path, worker_factory):
    child = launch(tmp_path, "wait", worker_factory)
    while receive(child)["type"] != "snapshot":
        pass
    child.process.stdin.close()
    assert child.wait(timeout=2) == 0


def test_engine_exception_is_reported_without_its_raw_secret(tmp_path, worker_factory):
    child = launch(tmp_path, "failure", worker_factory)
    messages = collect(child)
    assert messages[-1]["state"] == "failed"
    assert "RuntimeError" in json.dumps(messages)
    assert "raw-exception-secret" not in json.dumps(messages)


def test_legacy_engine_initializes_from_memory_without_network_or_tensorflow(tmp_path, worker_factory):
    child = launch(tmp_path, "legacy_import", worker_factory)
    messages = collect(child)
    assert messages[-1]["state"] == "completed", messages
    assert not any("AssertionError" in m.get("message", "") for m in messages)
    assert all("private-only-in-pipe" not in p.read_text(errors="ignore")
               for p in tmp_path.rglob("*") if p.is_file())


def test_windowed_stdio_none_restores_private_worker_transport(tmp_path, worker_factory):
    child = launch(tmp_path, "stdio_none", worker_factory)
    messages = collect(child)
    assert messages[-1]["state"] == "completed"
    assert all(m["run_id"] == "test-run" for m in messages)
    assert "private-only-in-pipe" not in json.dumps(messages)
    assert child.stderr == b""


def test_timed_out_submission_is_not_replayed_on_stale_result_page(tmp_path, worker_factory):
    child = launch(tmp_path, "ambiguous", worker_factory)
    messages = collect(child)
    assert messages[-1]["state"] == "completed", messages
    final = [m["data"] for m in messages if m["type"] == "snapshot"][-1]
    assert final["errors"]["offline_submission_count"] == 1
    assert final["courses"][0]["status"] == "unconfirmed"
    assert final["elective_loop"] == 3
