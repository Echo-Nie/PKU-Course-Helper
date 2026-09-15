"""Bounded, drained subprocess transport for offline worker integration tests."""
from collections import deque
import json
import queue
import subprocess
import threading
import time

import pytest


class WorkerClient:
    def __init__(self, command, env, timeout=15):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.deadline = time.monotonic() + timeout
        self.events = queue.Queue(maxsize=128)
        self.errors = deque(maxlen=64)
        self.closed = threading.Event()
        self.readers = [threading.Thread(target=target, daemon=True)
                        for target in (self._stdout, self._stderr)]
        for reader in self.readers:
            reader.start()

    def _stdout(self):
        while not self.closed.is_set():
            line = self.process.stdout.readline(1024 * 1024 + 1)
            while not self.closed.is_set():
                try:
                    self.events.put(line, timeout=0.1)
                    break
                except queue.Full:
                    pass
            if not line:
                return

    def _stderr(self):
        while True:
            chunk = self.process.stderr.read(1024)
            if not chunk:
                return
            self.errors.append(chunk)

    @property
    def stderr(self):
        return b''.join(self.errors)

    def send(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def receive(self):
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            line = self.events.get(timeout=remaining)
        except queue.Empty:
            pytest.fail('Worker deadline exceeded; stderr: ' + self.stderr.decode('utf-8', 'replace'))
        assert line, 'Worker exited before finished; stderr: ' + self.stderr.decode('utf-8', 'replace')
        return json.loads(line)

    def wait(self, timeout=3):
        result = self.process.wait(timeout=timeout)
        for reader in self.readers:
            reader.join(timeout=1)
        return result

    def close(self):
        self.closed.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=3)
        for reader in self.readers:
            reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


@pytest.fixture
def worker_factory():
    workers = []

    def spawn(command, env, timeout=15):
        worker = WorkerClient(command, env, timeout)
        workers.append(worker)
        return worker

    yield spawn
    for worker in workers:
        worker.close()
