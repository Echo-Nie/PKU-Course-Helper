"""One synchronized decision book across every identity and page."""
from dataclasses import asdict
import threading
import time


def fingerprint(course):
    return course.name.strip(), int(course.class_no), course.school.strip()


class RuleBook:
    TERMINAL = {'elected', 'ignored', 'failed', 'unmatched', 'identity_unavailable'}

    def __init__(self, config, log=lambda message: None, clock=time.monotonic):
        self.lock = threading.RLock()
        self.clock, self.log = clock, log
        self.goals = {c.id: c for c in config.courses}
        self.route = {c.id: (c.identity, c.page) for c in config.courses}
        self.route_members = {}
        for cid, key in self.route.items():
            self.route_members.setdefault(key, []).append(cid)
        self.rank = {}
        group_sizes = {}
        for course in config.courses:
            key = self.route[course.id]
            self.rank[course.id] = group_sizes.get(key, 0)
            group_sizes[key] = self.rank[course.id] + 1
        self.peers = {c.id: set() for c in config.courses}
        for group in config.mutexes:
            for cid in group.courses:
                self.peers[cid].update(set(group.courses) - {cid})
        self.thresholds = {d.course: d.threshold for d in config.delays}
        self.rows = {c.id: dict(asdict(c), status='unknown', reason='尚未查询',
                               capacity=None, enrolled=None, remaining=None, observed_at=None)
                     for c in config.courses}
        self.seen = {}
        self.observed_identities = set()
        self.reserved = set()
        self.pending = set()
        self.attempt_turn = 0
        self.attempted = {}
        route_count = len({(c.identity, c.page) for c in config.courses})
        self.freshness = max(30, config.client['refresh_interval'] * (1 + config.client['random_deviation']) * route_count * 2)
        for group in config.mutexes:
            names = ['%s（%s，第 %s 页）' % (self.goals[cid].name,
                     '主修' if self.goals[cid].identity == 'bzx' else '辅修', self.goals[cid].page)
                     for cid in group.courses]
            self.log('互斥规则：' + ' / '.join(names) + '；同身份同页内按优先级，跨组不比较序号。')

    def _elected(self, identity, courses):
        self.observed_identities.add(identity)
        selected = {fingerprint(c) for c in courses}
        for cid, goal in self.goals.items():
            if goal.identity != identity or fingerprint(goal) not in selected:
                continue
            row = self.rows[cid]
            changed = row['status'] != 'elected'
            row.update(status='elected', reason='已确认选上')
            self.pending.discard(cid)
            if changed:
                self.log('[成功] 已确认选上：' + self.describe(cid))
            for peer in self.peers[cid]:
                if self.rows[peer]['status'] not in self.TERMINAL and peer not in self.pending:
                    self.rows[peer].update(status='ignored', reason='互斥规则：已选上 ' + goal.name)
                    self.log('互斥规则生效：%s 已选上，跳过 %s。' % (goal.name, self.goals[peer].name))

    def observe(self, key, elected, plans, wall_time=None):
        with self.lock:
            self._elected(key[0], elected)
            catalog = {fingerprint(c): c for c in plans}
            for cid in self.route_members[key]:
                goal = self.goals[cid]
                row = self.rows[cid]
                if row['status'] in self.TERMINAL:
                    continue
                match = catalog.get(fingerprint(goal))
                if match is None:
                    if cid not in self.pending:
                        identity_label = '辅修' if goal.identity == 'bfx' else '主修 / 选修'
                        row.update(status='unmatched', reason='%s入口第 %d 页未找到匹配课程。请核对课程全名、班号、开课单位和所在页码；也请确认已加入该入口的补退选计划。' % (identity_label, goal.page),
                                   capacity=None, enrolled=None, remaining=None, retry_at=None,
                                   observed_at=wall_time if wall_time is not None else time.time())
                        self.log('[警告] 不匹配：%s；该页共 %d 门可选课程，请核对配置。' % (self.describe(cid), len(plans)))
                    continue
                capacity, enrolled = match.status
                old_quota = row['remaining']
                self.seen[cid] = self.clock()
                row.update(capacity=capacity, enrolled=enrolled, remaining=capacity - enrolled,
                           retry_at=None,
                           observed_at=wall_time if wall_time is not None else time.time())
                if cid in self.pending:
                    row.update(status='unconfirmed', reason='已提交，结果待确认；不会重复提交')
                else:
                    delayed = self._delayed(cid)
                    row.update(status='waiting' if capacity <= enrolled or delayed else 'pending',
                               reason='等待名额达到延迟阈值' if delayed else '等待名额' if capacity <= enrolled else '有剩余名额，等待处理')
                if old_quota != row['remaining']:
                    self.log('[信息] 名额更新：%s；容量 %d，已选 %d，剩余 %d。' %
                             (self.describe(cid), capacity, enrolled, row['remaining']))
            return catalog

    def describe(self, cid):
        c = self.goals[cid]
        return '%s · 第 %d 页 · %s · %s · %d 班' % ('主修' if c.identity == 'bzx' else '辅修', c.page, c.name, c.school, c.class_no)

    def retry(self, key, reason, delay):
        with self.lock:
            for cid, row in self.rows.items():
                if self.route[cid] == key and row['status'] not in self.TERMINAL:
                    row.update(retry_at=time.time() + delay)
                    if cid not in self.pending:
                        row.update(status='retrying', reason=reason + '；自动退避后重试，旧名额仅供参考')
                    else:
                        row.update(reason=reason + '；已提交结果待核对，不会重复提交')

    def fail_remaining(self, reason):
        with self.lock:
            for cid, row in self.rows.items():
                if row['status'] not in self.TERMINAL and cid not in self.pending:
                    row.update(status='failed', reason=reason, retry_at=None)

    def _delayed(self, cid):
        return cid in self.thresholds and (self.rows[cid]['remaining'] or 0) > self.thresholds[cid]

    def reserve(self, key, catalog):
        with self.lock:
            # Preserve first-attempt priority, but let independent courses on
            # this page have a turn before retrying a failed captcha forever.
            order = sorted(self.route_members[key], key=lambda cid: (self.attempted.get(cid, 0), self.rank[cid]))
            for cid in order:
                goal = self.goals[cid]
                row = self.rows[cid]
                if ((goal.identity, goal.page) != key or row['status'] in self.TERMINAL
                        or cid in self.pending or cid in self.reserved
                        or (row['remaining'] or 0) <= 0 or self._delayed(cid)):
                    continue
                if any(p in self.pending or p in self.reserved for p in self.peers[cid]):
                    row['reason'] = '等待互斥课程处理或确认结果'
                    continue
                # Check previously elected courses once in every related identity
                # before the first write. Unrelated pages/identities remain free.
                if any(self.goals[p].identity not in self.observed_identities
                       and self.rows[p]['status'] not in self.TERMINAL for p in self.peers[cid]):
                    row['reason'] = '等待核对互斥身份的已选列表，防止重复选中替代课程'
                    continue
                higher = [p for p in self.peers[cid] if self.route[p] == key and self.rank[p] < self.rank[cid]
                          and self.rows[p]['status'] not in self.TERMINAL]
                # Unknown/stale higher-priority results are not proof of no seats.
                if any(p not in self.seen or self.clock() - self.seen[p] > self.freshness
                       or ((self.rows[p]['remaining'] or 0) > 0 and not self._delayed(p)) for p in higher):
                    row['reason'] = '等待高优先级互斥课程的最新结果'
                    continue
                course = catalog.get(fingerprint(goal))
                if course is not None:
                    self.attempt_turn += 1
                    self.attempted[cid] = self.attempt_turn
                    self.reserved.add(cid)
                    return cid, course
            return None

    def submitted(self, cid):
        with self.lock:
            if cid not in self.reserved or self.rows[cid]['status'] in self.TERMINAL:
                return False
            if any(p in self.pending or self.rows[p]['status'] == 'elected' for p in self.peers[cid]):
                return False
            self.pending.add(cid)  # Commit uncertainty BEFORE issuing the write.
            self.rows[cid].update(status='unconfirmed', reason='已提交，结果待确认；不会重复提交')
            self.log('[信息] 提交选课：' + self.describe(cid) + '；等待学校确认，不会重复提交。')
            return True

    def result(self, cid, status, reason, elected=()):
        with self.lock:
            if status != 'unconfirmed':
                self.pending.discard(cid)
            self.rows[cid].update(status=status, reason=reason)
            self.log('[%s] 选课响应：%s；%s。' % ('警告' if status != 'elected' else '成功', self.describe(cid), reason))
            self._elected(self.goals[cid].identity, elected)

    def release(self, cid):
        with self.lock:
            self.reserved.discard(cid)

    def fail_identity(self, identity, reason):
        with self.lock:
            for cid, goal in self.goals.items():
                if goal.identity == identity and self.rows[cid]['status'] not in self.TERMINAL and cid not in self.pending:
                    self.rows[cid].update(status='identity_unavailable', reason=reason, retry_at=None)

    def done(self, key):
        with self.lock:
            return all(self.rows[cid]['status'] in self.TERMINAL for cid in self.route_members[key])

    def snapshot(self):
        with self.lock:
            return [dict(row) for row in self.rows.values()]
