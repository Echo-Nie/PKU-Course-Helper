#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: environ.py
# modified: 2020-02-16

from .utils import Singleton
from collections import defaultdict
from threading import Event, RLock
from queue import Empty


class EngineCancelled(BaseException):
    """Cooperative shutdown; deliberately bypass legacy retry handlers."""


def checkpoint():
    if Environ().stop_event.is_set():
        raise EngineCancelled()


def interruptible_get(queue):
    while True:
        checkpoint()
        try:
            return queue.get(timeout=0.2)
        except Empty:
            continue

class Environ(object, metaclass=Singleton):

    def __init__(self):
        self.config_ini = None
        self.config_parser = None
        self.stop_event = Event()
        self.state_lock = RLock()
        self.course_details = {}
        self.page_last_seen = {}
        self.page_allocations = {}
        self.pending_courses = set()
        self.blocked_by_pending = set()
        self.event_sink = None
        self.with_monitor = None
        self.iaaa_loop = 0
        self.elective_loop = 0
        self.errors = defaultdict(lambda: 0)
        self.iaaa_loop_thread = None
        self.elective_loop_thread = None
        self.monitor_thread = None
        self.goals = [] # [Course]
        self.ignored = {} # {Course, reason}
