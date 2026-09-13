from datetime import datetime, timedelta

from model import db, User, UserProfile, TimeEntry
from routes.common import get_logical_date, load_todo_lists, load_notebooks
from routes.guest import (
    create_guest_user, purge_expired_guests, delete_guest_users, GUEST_TTL,
)

from conftest import register, get_user


def guest_ids():
    return [u.id for u in User.query.filter_by(is_guest=True).all()]


def age_account(user_id, by):
    profile = UserProfile.query.filter_by(user_id=user_id).one()
    profile.created_at = datetime.now() - by
    db.session.commit()


def test_login_page_offers_guest_entry(client):
    html = client.get('/login').get_data(as_text=True)
    assert 'action="/guest"' in html
    assert 'Continue without account' in html


def test_guest_login_skips_onboarding_and_opens_dashboard(client):
    resp = client.post('/guest')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'

    assert len(guest_ids()) == 1
    assert client.get('/').status_code == 200
    assert client.get('/history?offset=-1').status_code == 200


def test_guest_entry_is_post_only(client):
    # GET 不能建号，否则爬虫顺着链接就能刷出一堆访客账号
    assert client.get('/guest').status_code == 405
    assert guest_ids() == []


def test_each_click_gets_a_separate_guest(client, app):
    client.post('/guest')
    app.test_client().post('/guest')
    ids = guest_ids()
    assert len(ids) == 2
    names = {db.session.get(User, i).username for i in ids}
    assert len(names) == 2


def test_guest_is_seeded_with_sample_data(app):
    now = datetime(2026, 3, 10, 15, 2)
    guest = create_guest_user(now)
    today = get_logical_date(now)

    assert guest.profile is not None
    assert any(lst['todos'] for lst in load_todo_lists(guest))
    assert len(load_notebooks(guest)) >= 1

    archived = TimeEntry.query.filter_by(user_id=guest.id, is_archived=True).all()
    assert archived
    assert all(e.archive_date < today for e in archived)
    assert today - timedelta(days=1) in {e.archive_date for e in archived}

    active = TimeEntry.query.filter_by(user_id=guest.id, is_archived=False).all()
    assert active
    for e in active:
        assert e.archive_date == today
        # 逻辑日期必须是今天，否则首页加载时会被当成旧记录自动归档
        assert get_logical_date(e.timestamp) == today
        assert e.timestamp <= now
        assert '06:00' <= e.start_time < e.end_time


def test_no_today_sessions_that_would_start_before_day_boundary(app):
    guest = create_guest_user(datetime(2026, 3, 10, 6, 20))
    assert TimeEntry.query.filter_by(user_id=guest.id, is_archived=False).count() == 0


def test_today_sessions_after_midnight_stay_in_logical_day(app):
    now = datetime(2026, 3, 11, 1, 30)   # 逻辑上仍是 3 月 10 日
    guest = create_guest_user(now)
    active = TimeEntry.query.filter_by(user_id=guest.id, is_archived=False).all()
    assert active
    assert all(get_logical_date(e.timestamp) == get_logical_date(now) for e in active)


def test_guest_cannot_log_in_with_password_form(client):
    client.post('/guest')
    username = db.session.get(User, guest_ids()[0]).username
    client.get('/logout')
    resp = client.post('/login', data={'username': username, 'password': ''})
    assert resp.status_code == 200   # 留在登录页


def test_guest_logout_deletes_account_and_data(client):
    client.post('/guest')
    guest_id = guest_ids()[0]

    resp = client.get('/logout')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']

    assert User.query.filter_by(id=guest_id).first() is None
    assert TimeEntry.query.filter_by(user_id=guest_id).count() == 0
    assert UserProfile.query.filter_by(user_id=guest_id).count() == 0


def test_regular_logout_keeps_account(client):
    register(client, 'alice', 'password123')
    client.get('/logout')
    assert get_user('alice') is not None


def test_expired_guests_purged_on_next_guest_login(client, app):
    register(app.test_client(), 'alice', 'password123')
    alice_id = get_user('alice').id

    old_guest = create_guest_user(datetime.now()).id
    fresh_guest = create_guest_user(datetime.now()).id
    age_account(old_guest, GUEST_TTL + timedelta(minutes=1))
    age_account(fresh_guest, GUEST_TTL - timedelta(minutes=5))
    # 真实用户再老也不能被清理
    age_account(alice_id, GUEST_TTL * 30)

    client.post('/guest')

    assert User.query.filter_by(id=old_guest).first() is None
    assert TimeEntry.query.filter_by(user_id=old_guest).count() == 0
    assert User.query.filter_by(id=fresh_guest).first() is not None
    assert User.query.filter_by(id=alice_id).first() is not None
    assert len(guest_ids()) == 2   # fresh_guest + 刚进来的这位


def test_purge_with_nothing_expired_is_a_noop(app):
    guest = create_guest_user(datetime.now()).id
    purge_expired_guests()
    assert guest_ids() == [guest]


def test_delete_guest_users_ignores_real_accounts(auth_client):
    delete_guest_users([auth_client.user_id])
    assert get_user('alice') is not None
    assert UserProfile.query.filter_by(user_id=auth_client.user_id).count() == 1
