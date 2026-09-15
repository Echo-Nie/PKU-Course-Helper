import os
from pathlib import Path
import sys

from autoelective.desktop.domain.config import AppConfig, CourseConfig, MutexRule
from autoelective.desktop.runtime.protocol import encode


def run(tmp_path, mode, worker_factory):
    config = AppConfig()
    config.client['elective_client_pool_size'] = 2  # Historical CLI regression, not desktop defaults.
    config.user['student_id'] = 'offline-test'
    # Global course priority intentionally opposes ascending page order.
    config.courses = [CourseConfig(id='high', name='高优先级', school='学院', page=2),
                      CourseConfig(id='low', name='低优先级', school='学院', page=1)]
    if mode in ('mutex', 'ambiguous_mutex', 'uncertain_mutex'):
        config.mutexes = [MutexRule(id='m', courses=['high', 'low'])]
    child = worker_factory([sys.executable, str(Path(__file__).with_name('paginated_harness.py')), mode],
                             env=dict(os.environ, PKU_AUTOELECTIVE_DATA_DIR=str(tmp_path), PYTHONDONTWRITEBYTECODE='1'))
    child.send(encode(dict(version=1, type='start', run_id='pagination', config=config.to_dict(), password='offline-password')))
    messages = []
    try:
        while True:
            event = child.receive()
            messages.append(event)
            if event['type'] == 'finished':
                break
        failed = mode in ('rate_limited', 'logout_limited', 'iaaa_limited')
        assert child.wait(timeout=3) == (1 if failed else 0), messages
        assert messages[-1]['state'] == ('failed' if failed else 'completed'), messages
        return [event['data'] for event in messages if event['type'] == 'snapshot'][-1]
    finally:
        child.close()


def test_gathers_all_pages_before_global_priority_and_uses_source_session(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'success', worker_factory)
    assert snapshot['errors']['write_order_2,1'] == 1
    assert snapshot['errors']['write_page_2_client_2'] == 1
    assert snapshot['errors']['write_page_1_client_1'] == 1
    assert snapshot['errors']['budget_reservations'] == 2
    assert [c['page'] for c in snapshot['courses']] == [2, 1]
    assert all(c['observed_at'] for c in snapshot['courses'])
    assert snapshot['page_allocations'] == {'1': [1], '2': [2]}


def test_mutex_remains_global_across_pages(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'mutex', worker_factory)
    assert snapshot['errors']['write_order_2'] == 1
    assert snapshot['courses'][1]['status'] == 'ignored'
    assert snapshot['courses'][1]['reason'] == '互斥规则'


def test_broken_page_aborts_all_decisions_and_retries_use_same_budget(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'partial', worker_factory)
    assert snapshot['errors']['write_order_'] == 1
    assert snapshot['errors']['budget_reservations'] == 6
    assert snapshot['errors']['read_order_1,2,1,2,1,2'] == 1
    assert all(c['status'] == 'unknown' for c in snapshot['courses'])
    assert all(c['observed_at'] is None for c in snapshot['courses'])


def test_timed_out_mutex_peer_is_not_replayed_or_bypassed_across_pages(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'ambiguous_mutex', worker_factory)
    assert snapshot['errors']['write_order_2'] == 1
    assert snapshot['errors']['read_order_1,2,2,1,1,2'] == 1
    assert snapshot['courses'][0]['status'] == 'unconfirmed'
    assert snapshot['courses'][1]['status'] == 'pending'
    assert snapshot['courses'][1]['reason'] == '等待互斥课程的提交结果确认'


def test_uncertain_response_blocks_same_cycle_mutex_peer(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'uncertain_mutex', worker_factory)
    assert snapshot['errors']['write_order_2'] == 1
    assert snapshot['courses'][1]['status'] == 'pending'


def test_explicit_rate_limit_stops_without_retry_or_submission(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'rate_limited', worker_factory)
    assert snapshot['errors']['write_order_'] == 1
    assert snapshot['errors']['read_order_1'] == 1
    assert snapshot['errors']['AccessLimitedError'] == 1


def test_page_leases_warm_only_required_slots_and_return_without_duplicates(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'warm', worker_factory)
    assert snapshot['errors']['login_client_1'] == 1
    assert snapshot['errors']['login_client_2'] == 1
    assert snapshot['errors']['returned_pool_slots'] == 2
    assert snapshot['errors']['write_order_2,1'] == 1
    assert snapshot['errors']['budget_reservations'] == 2


def test_rate_limited_logout_stops_without_queuing_relogin_or_polling(tmp_path, worker_factory):
    snapshot = run(tmp_path, 'logout_limited', worker_factory)
    assert snapshot['errors']['logout_requests'] == 1
    assert snapshot['errors']['AccessLimitedError'] == 1
    assert snapshot['errors']['queued_relogin_slots'] == 0
    assert snapshot['errors']['read_order_'] == 1
    assert snapshot['errors']['write_order_'] == 1


def test_fatal_iaaa_error_sets_stop_before_long_finally_delay(tmp_path, worker_factory):
    import time
    started = time.monotonic()
    snapshot = run(tmp_path, 'iaaa_limited', worker_factory)
    assert time.monotonic() - started < 5
    assert snapshot['errors']['restricted_login_requests'] == 1
    assert snapshot['errors']['AccessLimitedError'] == 1
    assert snapshot['errors']['stop_set_before_guarded_failure'] == 1
    assert snapshot['errors']['read_order_'] == 1
    assert snapshot['errors']['write_order_'] == 1
