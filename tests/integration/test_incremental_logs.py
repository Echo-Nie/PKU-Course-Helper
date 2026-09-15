from autoelective.desktop.bridge import DesktopBridge
from autoelective.desktop.adapters.portable import PortablePaths


def test_log_cursor_is_bounded_and_resets_after_clear_and_overflow(tmp_path):
    bridge = DesktopBridge(PortablePaths(tmp_path))
    try:
        for i in range(2500): bridge._on_log('event %d' % i)
        assert len(bridge._logs) == 2000
        batch = bridge.poll(0, None)
        assert batch['logs_reset'] and len(batch['logs']) == 200
        while batch['logs_more']:
            batch = bridge.poll(batch['log_cursor'], batch['generation'])
            assert len(batch['logs']) <= 200 and not batch['logs_reset']
        empty = bridge.poll(batch['log_cursor'], batch['generation'])
        assert empty['logs'] == []
        assert not bridge.poll(-1, 0)['ok']
        assert bridge.clear_data()['ok']
        assert bridge.poll(batch['log_cursor'], batch['generation'])['logs_reset']
    finally:
        assert bridge._shutdown()


def test_logs_have_date_single_line_and_disk_retention_is_bounded(tmp_path):
    from autoelective.desktop.runtime.journal import StrictRotatingHandler
    import logging
    handler = StrictRotatingHandler(tmp_path / 'runtime.log', maxBytes=1000, backupCount=9, encoding='utf8')
    for _ in range(1000): handler.emit(logging.LogRecord('test', 20, '', 0, 'bounded line ' * 20, (), None))
    handler.close()
    files = list(tmp_path.glob('runtime.log*'))
    assert len(files) == 10 and sum(f.stat().st_size for f in files) <= 10_000
