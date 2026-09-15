"""Bounded UI history and nonblocking rolling disk log; no growing event lists."""
from collections import deque
import logging
from logging.handlers import RotatingFileHandler
import threading
import time


class StrictRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # The standard handler otherwise swallows disk-full/permission failures.
        raise OSError('Unable to write application log')


class RollingLogWriter:
    LIMIT = 512

    def __init__(self, directory, handler_factory=StrictRotatingHandler):
        self.directory, self.handler_factory = directory, handler_factory
        self.condition = threading.Condition()
        self.queue = deque(maxlen=self.LIMIT)
        self.thread = None
        self.closing = False
        self.dropped = 0
        self.error = ''
        self.handler = None

    def submit(self, text):
        with self.condition:
            if self.closing:
                return
            if len(self.queue) == self.LIMIT:
                self.dropped += 1
            self.queue.append(text)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='RollingLogWriter', daemon=True)
                self.thread.start()
            self.condition.notify()

    def _run(self):
        retry_at = 0
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.queue or self.closing)
                    if not self.queue:
                        return
                    text = self.queue.popleft()
                if time.monotonic() < retry_at:
                    with self.condition:
                        self.dropped += 1
                    continue
                try:
                    if self.handler is None:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        self.handler = self.handler_factory(self.directory / 'runtime.log', maxBytes=2_000_000,
                                                            backupCount=9, encoding='utf-8')
                    self.handler.emit(logging.LogRecord('desktop', logging.INFO, '', 0, text, (), None))
                    with self.condition:
                        self.error = ''
                except Exception:
                    with self.condition:
                        self.dropped += 1
                        self.error = '磁盘日志暂时无法写入；请检查剩余空间与目录权限。界面日志和选课仍继续。'
                    retry_at = time.monotonic() + 30
                    if self.handler:
                        try:
                            self.handler.close()
                        except Exception:
                            pass
                        self.handler = None
        finally:
            if self.handler:
                self.handler.close()
                self.handler = None

    def status(self):
        with self.condition:
            return {'error': self.error, 'dropped': self.dropped, 'queued': len(self.queue)}

    def close(self, timeout=2):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()
