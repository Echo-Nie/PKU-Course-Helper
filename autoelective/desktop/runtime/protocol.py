"""Small versioned, bounded NDJSON transport shared by parent and child."""
import json

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 1024 * 1024


def encode(message):
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    if len(data) > MAX_LINE_BYTES:
        raise ValueError("消息超过大小限制")
    return data


def decode(line):
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("消息超过大小限制")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("消息格式无效")
    return value


class EventValidator:
    def __init__(self, run_id):
        self.run_id = run_id
        self.last_sequence = 0

    def accept(self, message):
        if message.get("version") != PROTOCOL_VERSION or message.get("run_id") != self.run_id:
            return False
        seq = message.get("seq")
        if type(seq) is not int or seq <= self.last_sequence:
            return False
        kind = message.get("type")
        if kind not in {"state", "snapshot", "log", "finished"}:
            return False
        if kind == "snapshot" and not isinstance(message.get("data"), dict):
            return False
        if kind in {"state", "finished"} and message.get("state") not in {"running", "stopped", "completed", "failed"}:
            return False
        if kind == "log" and not isinstance(message.get("message"), str):
            return False
        self.last_sequence = seq
        return True
