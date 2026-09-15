"""Offline child process fixture; never imports the live engine."""
import json
import os
import sys
import time

initial = json.loads(sys.stdin.readline())
sequence = 0


def emit(kind, **payload):
    global sequence
    sequence += 1
    print(json.dumps(dict(version=1, run_id=initial["run_id"], seq=sequence, type=kind, **payload)), flush=True)


mode = sys.argv[1]
assert initial["password"] not in str(sys.argv)
assert initial["password"] not in str(dict(os.environ))
emit("state", state="running")
emit("snapshot", data={"courses": [], "elective_loop": 1})
if mode == 'stalled':
    emit('snapshot', data={'courses': [], 'stalled': True})
if mode == "malformed":
    print("not-json", flush=True)
elif mode == "crash":
    sys.exit(17)
elif mode == "complete":
    emit("finished", state="completed")
    time.sleep(0.2)
elif mode == "stubborn":
    time.sleep(60)
else:
    sys.stdin.readline()
    emit("finished", state="stopped")
    time.sleep(0.15)
