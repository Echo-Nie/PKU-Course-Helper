from types import SimpleNamespace

from autoelective.desktop.domain.config import AppConfig, CourseConfig, MutexRule, DelayRule
from autoelective.desktop.runtime.rules import RuleBook


def goal(cid, identity='bzx', page=1):
    return CourseConfig(id=cid, name=cid, school='测试学院', identity=identity, page=page)


def available(c, remaining=1):
    return SimpleNamespace(name=c.name, class_no=c.class_no, school=c.school,
                           status=(10, 10 - remaining), href='/supplement/electSupplement.do?offline=1')


def test_priority_never_compares_different_identity_page_groups():
    a, b, c = goal('a', page=2), goal('b', 'bfx'), goal('c')
    config = AppConfig(courses=[a, b, c], mutexes=[MutexRule(courses=['a', 'b'])])
    book = RuleBook(config)
    book.observe(('bzx', 2), [], [available(a)])
    minor = book.observe(('bfx', 1), [], [available(b)])
    assert book.reserve(('bfx', 1), minor)[0] == 'b'
    book.release('b')
    assert book.rank['a'] == book.rank['b'] == book.rank['c'] == 0
    primary = book.observe(('bzx', 1), [], [available(c)])
    assert book.reserve(('bzx', 1), primary)[0] == 'c'
    book.release('c')
    book.observe(('bzx', 2), [], [available(a, remaining=0)])
    assert book.reserve(('bfx', 1), minor)[0] == 'b'


def test_uncertain_submission_is_never_replayed_and_blocks_cross_identity_peer():
    a, b = goal('a'), goal('b', 'bfx')
    book = RuleBook(AppConfig(courses=[a, b], mutexes=[MutexRule(courses=['a', 'b'])]))
    book.observe(('bfx', 1), [], [available(b)])
    catalog = book.observe(('bzx', 1), [], [available(a)])
    assert book.reserve(('bzx', 1), catalog)[0] == 'a'
    assert book.submitted('a')
    book.release('a')  # Simulated timeout after the write reached the server.
    for _ in range(4):
        catalog = book.observe(('bzx', 1), [], [available(a)])
        assert book.reserve(('bzx', 1), catalog) is None
    minor = book.observe(('bfx', 1), [], [available(b)])
    assert book.reserve(('bfx', 1), minor) is None
    assert book.snapshot()[0]['status'] == 'unconfirmed'
    book.observe(('bzx', 1), [a], [])
    assert [r['status'] for r in book.snapshot()] == ['elected', 'ignored']


def test_reserved_peer_is_exclusive_before_captcha_or_write():
    a, b = goal('a'), goal('b', page=2)
    book = RuleBook(AppConfig(courses=[a, b], mutexes=[MutexRule(courses=['a', 'b'])]))
    book.observe(('bzx', 1), [], [available(a, 0)])
    catalog_b = book.observe(('bzx', 2), [], [available(b)])
    assert book.reserve(('bzx', 2), catalog_b)[0] == 'b'
    catalog_a = book.observe(('bzx', 1), [], [available(a)])
    assert book.reserve(('bzx', 1), catalog_a) is None
    book.release('b')
    assert book.reserve(('bzx', 1), catalog_a)[0] == 'a'


def test_identity_isolates_same_named_course_and_missing_page_does_not_abort_others():
    a, b = goal('a'), goal('b', 'bfx')
    b.name = a.name
    book = RuleBook(AppConfig(courses=[a, b]))
    book.observe(('bzx', 1), [a], [])
    assert [r['status'] for r in book.snapshot()] == ['elected', 'unknown']
    book.observe(('bfx', 1), [], [])
    assert [r['status'] for r in book.snapshot()] == ['elected', 'unmatched']


def test_first_cross_identity_write_waits_for_elected_check_but_unrelated_course_does_not():
    a, b, independent = goal('a'), goal('b', 'bfx'), goal('free', page=2)
    book = RuleBook(AppConfig(courses=[a, b, independent], mutexes=[MutexRule(courses=['a', 'b'])]))
    catalog = book.observe(('bzx', 1), [], [available(a)])
    assert book.reserve(('bzx', 1), catalog) is None
    other = book.observe(('bzx', 2), [], [available(independent)])
    assert book.reserve(('bzx', 2), other)[0] == 'free'
    book.observe(('bfx', 1), [b], [])
    assert book.rows['a']['status'] == 'ignored'
    assert book.reserve(('bzx', 1), catalog) is None


def test_retry_status_recovers_and_does_not_overwrite_uncertain_submission():
    a = goal('a')
    book = RuleBook(AppConfig(courses=[a]))
    catalog = book.observe(('bzx', 1), [], [available(a)])
    book.retry(('bzx', 1), '连接中断', 8)
    assert book.rows['a']['status'] == 'retrying' and book.rows['a']['retry_at']
    catalog = book.observe(('bzx', 1), [], [available(a)])
    assert book.rows['a']['status'] == 'pending' and book.rows['a']['retry_at'] is None
    assert book.reserve(('bzx', 1), catalog)
    assert book.submitted('a')
    book.retry(('bzx', 1), '网络超时', 8)
    book.fail_remaining('任务停止')
    assert book.rows['a']['status'] == 'unconfirmed'


def test_mutex_logging_is_automatic_and_not_repeated_each_poll():
    a, b = goal('a'), goal('b', 'bfx')
    logs = []
    config = AppConfig(courses=[a, b], mutexes=[MutexRule(courses=['a', 'b'])])
    config.client['print_mutex_rules'] = False
    book = RuleBook(config, logs.append)
    for _ in range(5):
        book.observe(('bzx', 1), [a], [])
    assert sum('互斥规则：' in log for log in logs) == 1
    assert sum('互斥规则生效' in log for log in logs) == 1


def test_delay_threshold_and_stale_higher_priority_are_conservative():
    a, b = goal('a'), goal('b')
    now = [0]
    config = AppConfig(courses=[a, b], mutexes=[MutexRule(courses=['a', 'b'])],
                       delays=[DelayRule(course='a', threshold=2)])
    book = RuleBook(config, clock=lambda: now[0])
    catalog = book.observe(('bzx', 1), [], [available(a, 4), available(b)])
    assert book.reserve(('bzx', 1), catalog)[0] == 'b'
    book.release('b')
    now[0] = 200
    assert book.reserve(('bzx', 1), catalog) is None


def test_same_group_mutex_respects_local_priority_even_with_other_groups_interleaved():
    a, other, b = goal('a'), goal('other', 'bfx'), goal('b')
    book = RuleBook(AppConfig(courses=[a, other, b], mutexes=[MutexRule(courses=['a', 'b'])]))
    assert book.rank == {'a': 0, 'other': 0, 'b': 1}
    catalog = book.observe(('bzx', 1), [], [available(a), available(b)])
    assert book.reserve(('bzx', 1), catalog)[0] == 'a'
    book.release('a')
    assert book.reserve(('bzx', 1), catalog)[0] == 'a'


def test_failed_attempt_does_not_starve_independent_courses_on_same_page():
    a, b = goal('a'), goal('b')
    book = RuleBook(AppConfig(courses=[a, b]))
    catalog = book.observe(('bzx', 1), [], [available(a), available(b)])
    seen = []
    for _ in range(6):
        cid, _ = book.reserve(('bzx', 1), catalog)
        seen.append(cid)
        book.release(cid)
    assert seen == ['a', 'b'] * 3
