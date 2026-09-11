"""用户时区：cookie 里的 IANA 时区决定"现在"，没有/非法时回落多伦多。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from routes.common import now_local, resolve_user_tz, TZ_COOKIE, DEFAULT_TZ


def test_default_is_toronto():
    assert str(resolve_user_tz()) == DEFAULT_TZ
    assert str(resolve_user_tz(None)) == DEFAULT_TZ


@pytest.mark.parametrize('bad', ['', 'Not/A/Zone', '../../etc/passwd', 'x' * 100, 'Asia/Tokyo; DROP'])
def test_invalid_names_fall_back(bad):
    assert str(resolve_user_tz(bad)) == DEFAULT_TZ


def test_valid_name_is_honoured():
    assert str(resolve_user_tz('Asia/Shanghai')) == 'Asia/Shanghai'


def test_now_local_reads_cookie(app, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, 1, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr('routes.common.datetime', Frozen)

    with app.test_request_context('/', headers={'Cookie': f'{TZ_COOKIE}=Asia/Shanghai'}):
        assert now_local() == datetime(2026, 9, 11, 9, 30)      # UTC+8
        assert now_local().tzinfo is None

    with app.test_request_context('/'):
        assert now_local() == datetime(2026, 9, 10, 21, 30)     # 多伦多 EDT = UTC-4

    with app.test_request_context('/', headers={'Cookie': f'{TZ_COOKIE}=Mars/Olympus'}):
        assert now_local() == datetime(2026, 9, 10, 21, 30)


def test_dashboard_date_follows_cookie(auth_client, monkeypatch):
    """UTC 2026-09-11 01:30：上海已是周五 11 号，多伦多还是周四 10 号晚上。"""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, 1, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr('routes.common.datetime', Frozen)

    auth_client.set_cookie(TZ_COOKIE, 'Asia/Shanghai')
    assert 'datetime="2026-09-11"' in auth_client.get('/').get_data(as_text=True)

    auth_client.delete_cookie(TZ_COOKIE)
    assert 'datetime="2026-09-10"' in auth_client.get('/').get_data(as_text=True)
