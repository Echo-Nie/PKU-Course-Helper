import pytest

from autoelective.desktop.runtime.pagination import PagePoolRouter, PageRateLimiter
from autoelective.environ import EngineCancelled


def test_page_pools_share_fixed_global_slots_and_rotate_fairly():
    router = PagePoolRouter([1, 2, 3, 4, 5], total_slots=2, per_page=1)
    assert router.allocations == {1: (1,), 2: (2,), 3: (1,), 4: (2,), 5: (1,)}
    assert {router.next_routes()[0][0] for _ in range(5)} == {1, 2, 3, 4, 5}


def test_spare_slots_are_allocated_without_multiplying_global_capacity():
    router = PagePoolRouter([1, 2], total_slots=5, per_page=2)
    assert router.allocations == {1: (1, 3), 2: (2, 4)}
    assert router.next_routes() == [(1, 1), (2, 2)]
    assert router.next_routes() == [(2, 4), (1, 3)]


class FakeClock:
    def __init__(self):
        self.now = 0
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        return self.stopped


def test_all_pages_and_retries_share_one_jittered_budget():
    clock = FakeClock()
    random_values = iter([0, 1, 0.5, 0.5])
    limiter = PageRateLimiter(6, 0.5, clock, clock=lambda: clock.now, random_value=lambda: next(random_values))
    limiter.wait()  # First page starts immediately; its next gap is 3 seconds.
    limiter.wait()  # Other page consumes the same budget; next gap is 9 seconds.
    limiter.wait()  # Retry cannot bypass it.
    assert clock.waits == [3, 9]
    assert clock.now == 12


def test_rate_wait_cancels_and_invalid_fast_configs_are_rejected():
    clock = FakeClock()
    limiter = PageRateLimiter(6, 0.5, clock)
    clock.stopped = True
    with pytest.raises(EngineCancelled):
        limiter.wait()
    with pytest.raises(ValueError):
        PageRateLimiter(2, 0.5, clock)


def test_real_event_cancels_a_long_shared_budget_wait_promptly():
    from threading import Event, Thread
    stop = Event()
    cancelled = Event()
    limiter = PageRateLimiter(60, 0, stop)
    limiter.wait()

    def attempt():
        try:
            limiter.wait()
        except EngineCancelled:
            cancelled.set()

    thread = Thread(target=attempt, daemon=True)
    thread.start()
    stop.set()
    thread.join(timeout=0.5)
    assert cancelled.is_set()
    assert not thread.is_alive()
