"""Page routing over a bounded global pool, with one shared polling budget."""
import math
import random
import threading
import time

from autoelective.environ import EngineCancelled


class PagePoolRouter:
    def __init__(self, pages, total_slots, per_page):
        self.pages = tuple(sorted(set(pages)))
        if not self.pages or any(type(p) is not int or p < 1 for p in self.pages):
            raise ValueError("页面编号须为正整数")
        if type(total_slots) is not int or not 1 <= total_slots <= 5:
            raise ValueError("全局会话池须为 1 至 5")
        if type(per_page) is not int or not 1 <= per_page <= total_slots:
            raise ValueError("每页会话池不得超过全局上限")
        self.total_slots = total_slots
        allocations = {page: [(i % total_slots) + 1] for i, page in enumerate(self.pages)}
        if len(self.pages) < total_slots:
            unused = iter(range(len(self.pages) + 1, total_slots + 1))
            for _ in range(1, per_page):
                for page in self.pages:
                    slot = next(unused, None)
                    if slot is not None:
                        allocations[page].append(slot)
        else:
            for i, page in enumerate(self.pages):
                allocations[page] = [((i + offset) % total_slots) + 1 for offset in range(per_page)]
        self.allocations = {page: tuple(slots) for page, slots in allocations.items()}
        self._cycle = 0

    def next_routes(self):
        offset = self._cycle % len(self.pages)
        order = self.pages[offset:] + self.pages[:offset]
        routes = [(page, self.allocations[page][self._cycle % len(self.allocations[page])]) for page in order]
        self._cycle += 1
        return routes


class PageRateLimiter:
    def __init__(self, interval, deviation, stop_event, clock=time.monotonic, random_value=random.random):
        if (not math.isfinite(interval) or not math.isfinite(deviation) or interval <= 0
                or not 0 <= deviation < 1 or interval * (1 - deviation) < 3):
            raise ValueError("全局页面刷新最短间隔不得少于 3 秒")
        self.interval = interval
        self.deviation = deviation
        self.stop_event = stop_event
        self.clock = clock
        self.random_value = random_value
        self._next = None
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            if self.stop_event.is_set():
                raise EngineCancelled()
            if self._next is not None:
                delay = max(0, self._next - self.clock())
                if self.stop_event.wait(delay):
                    raise EngineCancelled()
            gap = self.interval * (1 + (2 * self.random_value() - 1) * self.deviation)
            self._next = self.clock() + gap
