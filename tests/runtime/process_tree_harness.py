"""Offline subprocess fixture for actual Windows Job Object lifetime tests."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    if sys.argv[1] == "worker":
        # Assign the worker to its job before allowing descendants.
        if sys.stdin.readline().strip() != "spawn":
            return 2
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(json.dumps({"grandchild": child.pid}), flush=True)
        sys.stdin.read()
        return 0

    from autoelective.desktop.platform.process_tree import spawn_owned_process
    worker, tree = spawn_owned_process(
        [sys.executable, __file__, "worker"], text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        worker.stdin.write("spawn\n")
        worker.stdin.flush()
        descendants = json.loads(worker.stdout.readline())
        print(json.dumps({"worker": worker.pid, **descendants}), flush=True)
        sys.stdin.readline()
    finally:
        if tree:
            # Test KILL_ON_JOB_CLOSE without an explicit kill call.
            tree.close()
        elif worker.poll() is None:
            worker.kill()
        worker.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
