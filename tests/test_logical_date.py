from datetime import datetime, date

from routes.common import get_logical_date
from services.stats import get_logical_date as get_logical_date_str


# 逻辑日期：每天 06:00 为分界，凌晨活动算前一天

def test_before_6am_belongs_to_previous_day():
    dt = datetime(2026, 7, 16, 5, 59)
    assert get_logical_date(dt) == date(2026, 7, 15)


def test_6am_belongs_to_same_day():
    dt = datetime(2026, 7, 16, 6, 0)
    assert get_logical_date(dt) == date(2026, 7, 16)


def test_midnight_belongs_to_previous_day():
    dt = datetime(2026, 7, 16, 0, 0)
    assert get_logical_date(dt) == date(2026, 7, 15)


def test_evening_belongs_to_same_day():
    dt = datetime(2026, 7, 16, 23, 30)
    assert get_logical_date(dt) == date(2026, 7, 16)


def test_month_boundary_rollback():
    dt = datetime(2026, 7, 1, 2, 0)
    assert get_logical_date(dt) == date(2026, 6, 30)


def test_string_variant_consistent_with_date_variant():
    # services/stats.py 里有一个返回字符串的重复实现，两者语义必须一致
    for dt in [datetime(2026, 7, 16, 3, 0), datetime(2026, 7, 16, 12, 0)]:
        assert get_logical_date_str(dt) == get_logical_date(dt).strftime('%Y-%m-%d')
