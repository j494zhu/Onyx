from types import SimpleNamespace

from services.stats import calculate_duration, calculate_stats_from_logs
from services.history_helper import calculate_duration_minutes, build_day_stats


def _log(desc='misc', start='10:00', end='11:00', category=None):
    return SimpleNamespace(desc=desc, start_time=start, end_time=end,
                           category=category)


# --- calculate_duration ---

def test_duration_normal():
    assert calculate_duration('10:00', '11:30') == 90


def test_duration_crosses_midnight():
    assert calculate_duration('23:00', '01:00') == 120


def test_duration_invalid_returns_zero():
    assert calculate_duration('abc', '11:00') == 0
    assert calculate_duration(None, None) == 0


# --- calculate_stats_from_logs ---

def test_stats_deep_keyword_detection():
    logs = [_log('coding session', '10:00', '12:00'),
            _log('watch tv', '13:00', '14:00')]
    total_h, deep_h = calculate_stats_from_logs(logs)
    assert total_h == 3.0
    assert deep_h == 2.0


def test_stats_invalid_rows_skipped():
    logs = [_log('code', 'bad', 'time'), _log('study', '10:00', '11:00')]
    total_h, deep_h = calculate_stats_from_logs(logs)
    assert total_h == 1.0
    assert deep_h == 1.0


def test_stats_empty_list():
    assert calculate_stats_from_logs([]) == (0.0, 0.0)


# --- history_helper.calculate_duration_minutes ---

def test_duration_minutes_supports_seconds_format():
    assert calculate_duration_minutes('10:00:00', '11:00:00') == 60


def test_duration_minutes_negative_wraps_24h():
    assert calculate_duration_minutes('23:00', '01:00') == 120


def test_duration_minutes_unparseable_returns_zero():
    assert calculate_duration_minutes('garbage', '11:00') == 0
    assert calculate_duration_minutes('', '') == 0


# --- build_day_stats ---

def test_build_day_stats_aggregates_categories():
    items = [
        _log('a', '10:00', '11:00', category='Deep Work'),
        _log('b', '11:00', '11:30', category='Break'),
        _log('c', '12:00', '13:00', category=None),  # → Uncategorized
    ]
    stats = build_day_stats(items)
    assert stats['total_minutes'] == 150
    assert stats['category_minutes'] == {
        'Deep Work': 60, 'Break': 30, 'Uncategorized': 60,
    }
    assert stats['focus_pct'] == 40  # 60/150
    assert stats['entry_count'] == 3
    assert stats['top_category'] in ('Deep Work', 'Uncategorized')  # 并列时取其一


def test_build_day_stats_empty():
    stats = build_day_stats([])
    assert stats['total_minutes'] == 0
    assert stats['focus_pct'] == 0
    assert stats['top_category'] == '—'
    assert stats['entry_count'] == 0
