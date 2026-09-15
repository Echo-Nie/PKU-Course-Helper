from collections import Counter
import threading
import time

import pytest

from autoelective.desktop.runtime.scheduler import FairDispatcher, FifoBudget, Cancelled


@pytest.mark.parametrize('limit', range(1, 6))
def test_unequal_page_counts_never_starve_identity_or_page(limit):
    keys = [('bzx', n) for n in range(1, 14)] + [('bfx', 1), ('bfx', 2)]
    dispatcher = FairDispatcher(keys, limit)
    count, slots = Counter(), set()
    for step in range(520):
        key, slot = dispatcher.lease(step)
        count[key] += 1
        slots.add(slot)
        dispatcher.finish(key, slot, step)
    assert min(count.values()) >= 20
    assert sum(n for (i, _), n in count.items() if i == 'bzx') == 260
    assert sum(n for (i, _), n in count.items() if i == 'bfx') == 260
    assert slots == set(range(1, limit + 1))


def test_one_page_rotates_through_every_global_slot():
    dispatcher = FairDispatcher([('bzx', 1)], 4)
    used = []
    for now in range(12):
        key, slot = dispatcher.lease(now)
        used.append(slot)
        dispatcher.finish(key, slot, now)
    assert used == [1, 2, 3, 4] * 3


def test_slow_page_is_leased_once_and_does_not_hold_all_slots():
    dispatcher = FairDispatcher([('bzx', 1), ('bzx', 2), ('bfx', 1)], 4)
    slow = dispatcher.lease(0)
    other = []
    for now in range(20):
        lease = dispatcher.lease(now)
        assert lease and lease[0] != slow[0] and lease[1] != slow[1]
        other.append(lease[0])
        dispatcher.finish(*lease, now)
    assert len(set(other)) == 2


def test_failed_route_has_bounded_backoff_without_monopolizing_others():
    dispatcher = FairDispatcher([('bzx', 1), ('bfx', 1)], 2)
    key, slot = dispatcher.lease(0)
    dispatcher.finish(key, slot, 0, failed=True)
    assert dispatcher.routes[key].ready_at == 2
    other = dispatcher.lease(0)
    assert other[0] != key
    dispatcher.finish(*other, 0)
    assert dispatcher.lease(2)[0] == key
    for now in range(10):
        dispatcher.finish(key, slot, now, failed=True)
    assert dispatcher.routes[key].ready_at - now == 60


def test_done_identity_returns_all_slots_to_remaining_work():
    dispatcher = FairDispatcher([('bzx', 1), ('bfx', 1)], 4)
    dispatcher.routes[('bfx', 1)].done = True
    used = set()
    for now in range(12):
        key, slot = dispatcher.lease(now)
        used.add(slot)
        dispatcher.finish(key, slot, now)
    assert used == {1, 2, 3, 4}


def test_fifo_budget_waits_without_bursts_and_cancels_sleepers():
    budget = FifoBudget(0.04)
    budget.next_at = time.monotonic() + 60
    observed = []
    def wait(index):
        try:
            budget.wait()
            observed.append((index, time.monotonic()))
        except Cancelled:
            observed.append((index, None))
    threads = []
    for index in range(5):
        thread = threading.Thread(target=wait, args=(index,))
        threads.append(thread)
        thread.start()
        # Synchronize actual FIFO insertion, not arbitrary thread scheduling.
        with budget.condition:
            assert budget.condition.wait_for(lambda: len(budget.queue) == index + 1, timeout=1)
    with budget.condition:
        budget.next_at = time.monotonic()
        budget.condition.notify_all()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert [i for i, _ in observed] == list(range(5))
    assert all(b[1] - a[1] >= 0.035 for a, b in zip(observed, observed[1:]))
    budget.next_at = time.monotonic() + 60
    thread = threading.Thread(target=wait, args=(99,))
    thread.start()
    budget.cancel()
    thread.join(1)
    assert observed[-1] == (99, None)
