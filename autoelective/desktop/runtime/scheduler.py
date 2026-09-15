"""Deterministic, affinity-aware identity/page fairness over a bounded pool.

The dispatcher is single-owner; callers hold their condition lock. Network
workers never select their own next task. A failed route retains its place in
the fair queue but is temporarily ineligible, so it cannot monopolize retries.
"""
from collections import Counter, deque
from dataclasses import dataclass
import math
import random
import threading
import time


class Cancelled(Exception):
    pass


@dataclass
class Route:
    identity: str
    page: int
    turn: int = 0
    ready_at: float = 0
    busy: bool = False
    failures: int = 0
    done: bool = False

    @property
    def key(self):
        return self.identity, self.page


@dataclass
class Slot:
    id: int
    identity: str
    turn: int = 0
    busy: bool = False


class FairDispatcher:
    def __init__(self, routes, limit):
        keys = sorted(set(routes))
        if not keys or any(i not in ('bzx', 'bfx') or type(p) is not int or p < 1 for i, p in keys):
            raise ValueError('Invalid identity/page routes')
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError('Session limit must be between 1 and 5')
        self.routes = {key: Route(*key) for key in keys}
        identities = sorted({i for i, _ in keys}, reverse=True)  # 主修 first
        self.slots = [Slot(n + 1, identities[n % len(identities)]) for n in range(limit)]
        self.identity_turn = dict.fromkeys(identities, 0)
        self.turn = 0

    def lease(self, now):
        idle = [s for s in self.slots if not s.busy]
        eligible = [r for r in self.routes.values() if not r.done and not r.busy and r.ready_at <= now]
        if not idle or not eligible:
            return None
        # First identity fairness, then oldest page within that identity.
        eligible.sort(key=lambda r: (self.identity_turn[r.identity], r.turn, r.identity != 'bzx', r.page))
        owners = Counter(s.identity for s in self.slots)
        active_identities = {r.identity for r in self.routes.values() if not r.done}
        active_pages = Counter(r.identity for r in self.routes.values() if not r.done)
        for route in eligible:
            own = [s for s in idle if s.identity == route.identity]
            # Keep warm identity affinity when both identities can use their
            # slots. Re-login on every brief idle gap costs more than it saves.
            spare = [s for s in idle if owners[s.identity] > max(1, active_pages[s.identity]) or s.identity not in active_identities
                     or len(self.slots) < len(active_identities)]
            orphaned = [s for s in idle if s.identity not in active_identities]
            candidates = own + orphaned if own else spare
            if not candidates:
                continue
            slot = min(candidates, key=lambda s: (s.turn, s.id))
            self.turn += 1
            slot.busy = route.busy = True
            slot.identity = route.identity
            slot.turn = route.turn = self.identity_turn[route.identity] = self.turn
            return route.key, slot.id
        return None

    def finish(self, key, slot_id, now, failed=False, done=False):
        route = self.routes[key]
        self.slots[slot_id - 1].busy = route.busy = False
        route.done = done
        route.failures = route.failures + 1 if failed else 0
        route.ready_at = now + min(60, 2 ** min(route.failures, 6)) if failed else now

    def wait_time(self, now):
        future = [r.ready_at - now for r in self.routes.values()
                  if not r.done and not r.busy and r.ready_at > now]
        return min(future) if future else None

    @property
    def completed(self):
        return all(r.done for r in self.routes.values())


class FifoBudget:
    """One cancellable FIFO budget; all real queries and recovery share it.

    Each waiter sleeps on a condition until its ticket and deadline arrive.
    Wakeups do not accrue credit: there is never a catch-up request burst.
    """
    def __init__(self, interval, deviation=0, clock=time.monotonic, random_value=random.random):
        if not math.isfinite(interval) or interval <= 0 or not 0 <= deviation < 1:
            raise ValueError('Invalid request interval')
        self.interval, self.deviation = interval, deviation
        self.clock, self.random_value = clock, random_value
        self.condition = threading.Condition()
        self.queue = deque()
        self.next_at = 0
        self.cancelled = False

    def cancel(self):
        with self.condition:
            self.cancelled = True
            self.condition.notify_all()

    def wait(self):
        token = object()
        with self.condition:
            self.queue.append(token)
            self.condition.notify_all()
            try:
                while True:
                    if self.cancelled:
                        raise Cancelled()
                    delay = self.next_at - self.clock()
                    if self.queue[0] is token and delay <= 0:
                        self.next_at = self.clock() + self.interval * (
                            1 + (2 * self.random_value() - 1) * self.deviation)
                        return
                    self.condition.wait(max(0, delay) if self.queue[0] is token else None)
            finally:
                self.queue.remove(token)
                self.condition.notify_all()
