"""顶栏日期 + 星期条。

关键点：显示的是用户本地的**自然日**（零点翻页），和 Archive Day 用的
逻辑日期（06:00 分界）是两套独立逻辑。服务端只负责首屏，之后由
dashboard.js 在零点自动更新。
"""

import re
from datetime import datetime, date

import pytest


WEEK_LETTERS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']


def _header(client):
    html = client.get('/').get_data(as_text=True)
    block = re.search(r'<div class="dash-date">.*?</div>\s*</div>', html, re.S)
    assert block, 'dash-date block missing'
    return block.group(0)


def _parse(block):
    iso = re.search(r'datetime="([^"]+)"', block).group(1)
    cells = re.findall(r'class="dash-week__day([^"]*)"[^>]*>([A-Za-z]{2})<', block)
    highlighted = [i for i, (cls, _l) in enumerate(cells) if 'is-today' in cls]
    return iso, [l for _c, l in cells], highlighted


def _freeze(monkeypatch, when):
    """把 routes.main 用的 now_local()（用户本地时间）冻结到指定时刻。"""
    monkeypatch.setattr('routes.main.now_local', lambda: when)


def test_old_title_is_gone(auth_client):
    html = auth_client.get('/').get_data(as_text=True)
    assert "'s Log" not in html
    assert 'dash-title' not in html


def test_week_strip_is_monday_first(auth_client):
    _iso, letters, _hl = _parse(_header(auth_client))
    assert letters == WEEK_LETTERS


def test_exactly_one_day_highlighted(auth_client):
    _iso, _letters, highlighted = _parse(_header(auth_client))
    assert len(highlighted) == 1


def test_highlight_matches_the_rendered_date(auth_client):
    iso, _letters, highlighted = _parse(_header(auth_client))
    assert highlighted == [date.fromisoformat(iso).weekday()]


@pytest.mark.parametrize('when, expected_date, expected_idx', [
    # 2026-09-10 是星期四（weekday 3）
    (datetime(2026, 9, 10, 12, 0), '2026-09-10', 3),   # 中午 -> 当天
    (datetime(2026, 9, 10, 6, 0), '2026-09-10', 3),    # 06:00 -> 当天
    (datetime(2026, 9, 10, 5, 59), '2026-09-10', 3),   # 05:59 -> 自然日已是 10 号（不按 06:00 分界）
    (datetime(2026, 9, 10, 0, 30), '2026-09-10', 3),   # 零点后 -> 已是新的一天
    (datetime(2026, 9, 9, 23, 59), '2026-09-09', 2),   # 零点前 -> 还是 9 号（周三）
])
def test_calendar_date_boundary(auth_client, monkeypatch, when, expected_date, expected_idx):
    _freeze(monkeypatch, when)
    iso, letters, highlighted = _parse(_header(auth_client))
    assert iso == expected_date
    assert highlighted == [expected_idx]
    assert letters[expected_idx] == WEEK_LETTERS[expected_idx]


def test_monday_and_sunday_land_on_the_ends(auth_client, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 14, 12, 0))   # 星期一
    _iso, _l, highlighted = _parse(_header(auth_client))
    assert highlighted == [0]

    _freeze(monkeypatch, datetime(2026, 9, 13, 12, 0))   # 星期日
    _iso, _l, highlighted = _parse(_header(auth_client))
    assert highlighted == [6]


def test_accessible_label_names_the_weekday(auth_client, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 10, 12, 0))
    block = _header(auth_client)
    assert 'aria-label="Thursday"' in block
