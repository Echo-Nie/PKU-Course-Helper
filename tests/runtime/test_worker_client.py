from collections import deque
import queue
import time

import pytest

from conftest import WorkerClient


def test_expired_deadline_rejects_even_a_queued_event():
    client = WorkerClient.__new__(WorkerClient)
    client.deadline = time.monotonic() - 60
    client.events = queue.Queue()
    client.events.put(b'{"type":"snapshot"}\n')
    client.errors = deque()
    with pytest.raises(pytest.fail.Exception, match='deadline exceeded'):
        client.receive()
