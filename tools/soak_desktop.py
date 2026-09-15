"""Offline accelerated engine endurance. Not a claim of real 250-hour uptime."""
import argparse
from collections import Counter, deque
import ctypes
import gc
import json
from pathlib import Path
import sys
import threading
import time
import tracemalloc
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
requests.sessions.Session.send = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('School network prohibited'))
from autoelective.desktop.domain.config import AppConfig, CourseConfig
from autoelective.desktop.runtime.engine import DesktopEngine


def resources():
    if sys.platform != 'win32': return {}
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in (
            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
            'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    psapi, kernel = ctypes.WinDLL('psapi'), ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    value = Counters(); value.cb = ctypes.sizeof(value)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    kernel.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    count = ctypes.c_ulong()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb): raise ctypes.WinError()
    if not kernel.GetProcessHandleCount(handle, ctypes.byref(count)): raise ctypes.WinError()
    return {'private_bytes': value.PrivateUsage, 'working_set': value.WorkingSetSize, 'handles': count.value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=150_000)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if Path(__file__).resolve().parents[2] not in args.report.resolve().parents:
        raise ValueError('Report must stay within testing workspace')
    goals = [CourseConfig(id=f'{identity}-{p}', name=f'离线课程{p}', school='测试院', identity=identity, page=p)
             for identity, pages in [('bzx', range(1, 8)), ('bfx', range(1, 3))] for p in pages]
    config = AppConfig(courses=goals)
    stop, lock = threading.Event(), threading.Lock()
    count, threads, visits = [0], set(), Counter()
    events, samples = deque(maxlen=2000), []
    by_route = {(c.identity, c.page): c for c in goals}
    class Session:
        ready = True
        def __init__(self, sid): self.sid = sid; self.identity = None
        def ensure_login(self, identity, budget):
            changed = self.identity != identity; self.identity = identity; return changed
        def fetch(self, page, budget):
            with lock:
                count[0] += 1
                visits[(self.identity, page)] += 1
                threads.add(threading.get_ident())
                if count[0] >= args.turns: stop.set()
            c = by_route[(self.identity, page)]
            return [], [SimpleNamespace(name=c.name, school=c.school, class_no=1, status=(10, 10))]
        def close(self): pass
    engine = DesktopEngine(config, '', stop, events.append, session_factory=Session)
    failures = []
    def run():
        try: engine.run()
        except BaseException as error: failures.append(type(error).__name__); stop.set()
    gc.collect(); tracemalloc.start()
    started = time.monotonic()
    coordinator = threading.Thread(target=run, name='SoakCoordinator')
    coordinator.start()
    next_sample = 10_000
    while coordinator.is_alive():
        coordinator.join(0.2)
        if count[0] >= next_sample or not coordinator.is_alive():
            current, peak = tracemalloc.get_traced_memory()
            samples.append({'turns': count[0], 'python_bytes': current, 'python_peak': peak,
                            'threads': threading.active_count(), **resources()})
            print(json.dumps(samples[-1]), flush=True)
            next_sample += 20_000
        if time.monotonic() - started > 180:
            failures.append('StressTestDeadline'); engine.cancel(); coordinator.join(3); break
    engine.close()
    result = {'passed': not failures and count[0] >= args.turns, 'network': 'prohibited',
              'actual_seconds': round(time.monotonic() - started, 3), 'query_turns': count[0],
              'same_count_at_six_seconds_hours': round(count[0] * 6 / 3600, 2),
              'real_240_hour_test_completed': False, 'worker_threads_created': len(engine.workers),
              'worker_thread_ids_used': len(threads), 'live_workers_after_stop': sum(w.is_alive() for w in engine.workers),
              'session_logins': engine.login_count,
              'route_visits': {f'{i}:{p}': n for (i,p),n in visits.items()},
              'bounded_log_count': len(events), 'bounded_rule_rows': len(engine.book.rows),
              'samples': samples, 'failures': failures}
    if len(samples) > 1:
        result['python_growth_after_warmup'] = samples[-1]['python_bytes'] - samples[0]['python_bytes']
        result['passed'] &= result['python_growth_after_warmup'] < 8_000_000
        if 'private_bytes' in samples[0]:
            result['private_growth_after_warmup'] = samples[-1]['private_bytes'] - samples[0]['private_bytes']
            result['handle_growth_after_warmup'] = samples[-1]['handles'] - samples[0]['handles']
            result['passed'] &= result['private_growth_after_warmup'] < 16_000_000 and result['handle_growth_after_warmup'] <= 8
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','route_visits')}, ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
