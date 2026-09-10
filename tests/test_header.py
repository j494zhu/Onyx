"""顶栏日期 + 星期条。

关键点：显示的是**逻辑日期**（06:00 为分界），不是自然日 ——
凌晨那几个小时表头必须和下面列出的记录属于同一天。
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
    """把 routes.main 里的 datetime.now() 冻结到指定时刻。"""
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr('routes.main.datetime', FrozenDatetime)


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
    (datetime(2026, 9, 10, 6, 0), '2026-09-10', 3),    # 06:00 整 -> 已算新的一天
    (datetime(2026, 9, 10, 5, 59), '2026-09-09', 2),   # 05:59 -> 仍算前一天（周三）
    (datetime(2026, 9, 10, 0, 30), '2026-09-09', 2),   # 午夜后 -> 仍算前一天
])
def test_logical_date_boundary(auth_client, monkeypatch, when, expected_date, expected_idx):
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
