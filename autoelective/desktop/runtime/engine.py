"""Desktop-only concurrent scheduler; the legacy CLI remains independent."""
from collections import Counter
import threading
import time

from .rules import RuleBook
from .scheduler import FairDispatcher, FifoBudget, Cancelled
from .school_session import SchoolSession, IdentityUnavailable, RetryTurn, FATAL_ERRORS, AUTH_ERRORS
from .feedback import describe_error
from ..platform.clock import active_time
from autoelective.exceptions import AutoElectiveClientException
from requests.exceptions import RequestException


class DesktopEngine:
    def __init__(self, config, password, stop_event, log=lambda message: None,
                 session_factory=None, query_budget=None, login_budget=None, clock=time.monotonic,
                 watchdog_clock=None):
        self.config, self.stop_event, self.log = config, stop_event, log
        self._log_secrets = (config.user.get('student_id', ''), password)
        self.clock, self.started_at = clock, clock()
        self.watchdog_clock = watchdog_clock or (active_time if clock is time.monotonic else clock)
        self.condition = threading.Condition()
        self.dispatcher = FairDispatcher([(c.identity, c.page) for c in config.courses],
                                         config.client['elective_client_pool_size'])
        self.query_budget = query_budget or FifoBudget(config.client['refresh_interval'], config.client['random_deviation'])
        self.login_budget = login_budget or FifoBudget(config.client['login_loop_interval'])
        self.book = RuleBook(config, log, clock=clock)
        self.recognizer = None
        if session_factory is None:
            from autoelective.captcha import CaptchaRecognizer
            from autoelective.const import CNN_MODEL_FILE
            self.recognizer = CaptchaRecognizer(CNN_MODEL_FILE)
            recognition_lock = threading.Lock()
            session_factory = lambda slot: SchoolSession(slot, config, password, self.recognizer, recognition_lock)
        self.sessions = {}
        try:
            for slot in self.dispatcher.slots:
                self.sessions[slot.id] = session_factory(slot.id)
        except BaseException:
            self.close()
            raise
        self.errors = Counter()
        self.login_count = self.query_count = 0
        self.failure = None
        self.tasks, self.workers = {}, []
        self.workers_stopping = False
        self.notices = {}  # At most one entry per configured page, never per event.
        self.activity = {sid: {'phase': '空闲', 'since': self.watchdog_clock(), 'deadline': None} for sid in self.sessions}
        self.page_stats = {key: {'queries': 0, 'last_query_at': None, 'last_error': ''} for key in self.dispatcher.routes}

    def _phase(self, sid, key, phase, allowance):
        with self.condition:
            now = self.watchdog_clock()
            self.activity[sid] = {'phase': phase, 'since': now, 'deadline': now + allowance,
                                  'identity': key[0], 'page': key[1]}

    def _worker(self, sid):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: sid in self.tasks or self.workers_stopping)
                if sid not in self.tasks:
                    return
                key = self.tasks.pop(sid)
            try:
                failed, done = self._turn(key, sid)
            except BaseException as error:
                # Even a bug in turn cleanup must release its lease and wake
                # the coordinator instead of leaving an invisible deadlock.
                self.failure = error
                failed, done = True, False
                self.cancel()
            finally:
                with self.condition:
                    self.dispatcher.finish(key, sid, self.clock(), failed=failed, done=done)
                    self.activity[sid] = {'phase': '空闲', 'since': self.watchdog_clock(), 'deadline': None}
                    self.condition.notify_all()

    def cancel(self):
        self.stop_event.set()
        self.query_budget.cancel()
        self.login_budget.cancel()
        with self.condition:
            self.condition.notify_all()

    def _turn(self, key, slot_id):
        session = self.sessions[slot_id]
        failed = False
        reserved = None
        submitted = False
        started = self.clock()
        label = '%s · 第 %d 页 · 会话 #%d' % ('主修' if key[0] == 'bzx' else '辅修', key[1], slot_id)
        timeout = self.config.client['elective_client_timeout']
        query_wait = len(self.sessions) * self.config.client['refresh_interval'] * (1 + self.config.client['random_deviation'])
        try:
            if self.stop_event.is_set():
                raise Cancelled()
            self._phase(slot_id, key, '登录 / 更新会话', 2 * self.config.client['iaaa_client_timeout'] + 3 * timeout
                        + 2 * len(self.sessions) * self.config.client['login_loop_interval'] + 60)
            logged_in = session.ensure_login(key[0], self.login_budget)
            if logged_in:
                with self.condition:
                    self.login_count += 1
                self.log('[信息] %s：登录成功，使用独立会话。' % label)
            if self.stop_event.is_set():
                raise Cancelled()
            self._phase(slot_id, key, '等待查询 / 读取页面', 2 * (query_wait + timeout) + 60)
            elected, plans = session.fetch(key[1], self.query_budget)
            with self.condition:
                self.query_count += 1
                stats = self.page_stats[key]
                stats.update(queries=stats['queries'] + 1, last_query_at=time.time(), last_error='')
            catalog = self.book.observe(key, elected, plans)
            candidate = self.book.reserve(key, catalog)
            if candidate:
                reserved, course = candidate
                self._phase(slot_id, key, '识别 / 验证验证码', 2 * timeout + 60)
                session.prepare()
                if self.stop_event.is_set():
                    raise Cancelled()
                if self.book.submitted(reserved):
                    submitted = True
                    self._phase(slot_id, key, '提交选课 / 等待确认', timeout + 30)
                    result = session.submit(course)
                    self.book.result(reserved, *result)
            with self.condition:
                previous = self.notices.pop(key, None)
            if previous:
                self.log('[恢复] %s：此前连续 %d 次失败后已恢复，本轮耗时 %.1f 秒，页面 %d 门课程。' %
                         (label, previous[2], self.clock() - started, len(plans)))
        except BaseException as error:
            name = type(error).__name__
            if isinstance(error, Cancelled) or name == 'EngineCancelled':
                pass
            elif isinstance(error, IdentityUnavailable):
                self.book.fail_identity(key[0], str(error))
                self.log('[警告] %s：%s；该身份已停止，其他身份继续。' % (label, str(error)))
            else:
                failed = True
                with self.condition:
                    self.errors[name] += 1
                if name in AUTH_ERRORS:
                    session.invalidate()
                elif isinstance(error, RequestException) and hasattr(session, 'reset_transport'):
                    session.reset_transport()
                if name == 'CourseIndexError':
                    session.initialized = False
                reason = describe_error(error, self._log_secrets)
                with self.condition:
                    phase = self.activity[slot_id]['phase']
                context = label + ' · 阶段：' + phase
                if reserved:
                    context += ' · 课程：' + self.book.describe(reserved)
                if submitted:
                    reason += '；本次提交结果待核对，不会重复提交自身或互斥课程'
                if name in FATAL_ERRORS or not isinstance(error, (AutoElectiveClientException, RequestException, RetryTurn)):
                    self.failure = error
                    from .worker import safe_error
                    if name not in {'CaughtCheatingError', 'NotAgreedToSelectionAgreement'}:
                        reason = safe_error(error)
                        if submitted:
                            reason += '；本次提交结果待核对，不会重复提交自身或互斥课程'
                    self.book.fail_remaining(reason)
                    self.log('[错误] %s：%s；任务已安全停止。' % (context, reason))
                    self.cancel()
                else:
                    with self.condition:
                        count = min(self.dispatcher.routes[key].failures + 1, 6)
                        delay = min(60, 2 ** count)
                        self.page_stats[key]['last_error'] = reason
                        last = self.notices.get(key)
                        repeat = (last[2] + 1) if last else 1
                        signature = (name, reason)
                        report = not last or last[1] != signature or self.clock() - last[0] >= 60
                        self.notices[key] = (self.clock() if report else last[0], signature, repeat)
                    self.book.retry(key, reason, delay)
                    if report:
                        self.log('[警告] %s：%s；本段累计 %d 次，%d 秒后重试，其他页面继续。' %
                                 (context, reason, repeat, delay))
                        if name in AUTH_ERRORS and repeat >= 3:
                            self.log('[提示] %s：认证问题反复出现，请核对课程身份与学校实际身份入口；桌面版无需手工配置 dual_degree。' % label)
        finally:
            if reserved:
                self.book.release(reserved)
            done = self.book.done(key)
        return failed, done

    def run(self):
        self.log('自动调度已启动：全局 %d 个会话，主修／辅修与页面公平轮转。' % len(self.sessions))
        self.log('[使用提示] 主要用于等待满员课程放出名额；启动需登录统一认证，网络拥堵时不保证比已登录的人工操作更快。')
        self.log('[频率提示] 全局查询间隔 %g 秒、随机偏移 %g；建议查询间隔不少于 4 秒。学校存在 IP 级限流，明确收到 HTTP 403/429 时停止，不保证账号不受限制。' %
                 (self.config.client['refresh_interval'], self.config.client['random_deviation']))
        try:
            for sid in self.sessions:
                thread = threading.Thread(target=self._worker, args=(sid,), daemon=True, name='Session-%d' % sid)
                thread.start()
                self.workers.append(thread)
            self._dispatch()
        except BaseException:
            self.cancel()
            with self.condition:
                while any(s.busy for s in self.dispatcher.slots):
                    self.condition.wait()
            raise
        finally:
            with self.condition:
                self.workers_stopping = True
                self.condition.notify_all()
            for thread in self.workers:
                thread.join()

    def _dispatch(self):
        with self.condition:
            while True:
                if self.stop_event.is_set():
                    self.query_budget.cancel()
                    self.login_budget.cancel()
                    if not any(s.busy for s in self.dispatcher.slots):
                        break
                    self.condition.wait()
                    continue
                if self.dispatcher.completed:
                    break
                lease = self.dispatcher.lease(self.clock())
                if lease:
                    self.tasks[lease[1]] = lease[0]
                    self.condition.notify_all()
                else:
                    self.condition.wait(self.dispatcher.wait_time(self.clock()))
        if self.failure:
            raise self.failure

    def snapshot(self):
        # Avoid holding the dispatcher lock while acquiring the rule-book lock.
        rows = self.book.snapshot()
        with self.condition:
            now = self.clock()
            watchdog_now = self.watchdog_clock()
            slots = [{'slot': s.id, 'identity': s.identity, 'busy': s.busy,
                      'ready': self.sessions[s.id].ready, 'phase': self.activity[s.id]['phase'],
                      'page': self.activity[s.id].get('page'),
                      'phase_seconds': max(0, watchdog_now - self.activity[s.id]['since']),
                      'stalled': bool(s.busy and self.activity[s.id]['deadline'] is not None
                                      and watchdog_now > self.activity[s.id]['deadline'])} for s in self.dispatcher.slots]
            errors = dict(self.errors)
            return {'courses': rows, 'iaaa_loop': self.login_count, 'elective_loop': self.query_count,
                    'error_count': sum(errors.values()), 'errors': errors,
                    'unconfirmed_count': sum(c['status'] == 'unconfirmed' for c in rows),
                    'uptime_seconds': max(0, now - self.started_at),
                    'stalled': any(s['stalled'] for s in slots),
                    'pages': [{'identity': r.identity, 'page': r.page, 'busy': r.busy, 'done': r.done,
                               'failures': r.failures, 'retry_in': max(0, r.ready_at - now), **self.page_stats[r.key]}
                              for r in self.dispatcher.routes.values()],
                    'sessions': slots, 'session_limit': len(slots),
                    'page_allocations': {('%s:%d' % r.key): [s.id for s in self.dispatcher.slots if s.identity == r.identity]
                                         for r in self.dispatcher.routes.values() if not r.done}}

    def close(self):
        self._log_secrets = ()
        for session in self.sessions.values():
            session.close()
        if self.recognizer:
            self.recognizer.model.closeSession()
