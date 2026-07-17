from datetime import datetime, timedelta

from model import db
from routes.common import get_logical_date

from conftest import TimeEntry, register, get_user, make_entry

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _create(client, desc='write code', start='10:00', end='11:30', headers=None):
    return client.post('/', data={
        'desc': desc, 'start_time': start, 'end_time': end,
    }, headers=headers or {})


def test_table_name_stays_expenses(app):
    # 生产库的表还叫 'expenses'（无迁移框架）。谁要是动了这个映射，先想好数据迁移方案。
    assert TimeEntry.__tablename__ == 'expenses'


def test_create_entry_via_form(auth_client):
    resp = _create(auth_client)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'

    entry = TimeEntry.query.filter_by(user_id=auth_client.user_id).first()
    assert entry is not None
    assert entry.desc == 'write code'
    assert entry.is_archived is False
    assert entry.archive_date == get_logical_date(datetime.now())


def test_create_entry_via_ajax_returns_payload(auth_client):
    resp = _create(auth_client, headers=AJAX)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'
    payload = data['entry']
    assert set(payload) == {'id', 'desc', 'start_time', 'end_time', 'timestamp'}
    assert payload['desc'] == 'write code'


def test_created_entry_shows_on_homepage(auth_client):
    _create(auth_client, desc='unique-marker-xyz')
    resp = auth_client.get('/')
    assert resp.status_code == 200
    assert 'unique-marker-xyz' in resp.get_data(as_text=True)


def test_delete_own_entry_ajax(auth_client):
    entry = make_entry(auth_client.user_id)
    resp = auth_client.post(f'/api/entries/{entry.id}', headers=AJAX)
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'success'
    assert db.session.get(TimeEntry, entry.id) is None


def test_delete_own_entry_form_redirects(auth_client):
    entry = make_entry(auth_client.user_id)
    resp = auth_client.post(f'/api/entries/{entry.id}')
    assert resp.status_code == 302
    assert db.session.get(TimeEntry, entry.id) is None


def test_cannot_delete_other_users_entry(auth_client, client):
    other_entry = make_entry(user_id=auth_client.user_id + 999)
    resp = auth_client.post(f'/api/entries/{other_entry.id}')
    assert b'Unauthorized' in resp.data
    assert db.session.get(TimeEntry, other_entry.id) is not None


def test_delete_nonexistent_entry_404(auth_client):
    resp = auth_client.post('/api/entries/424242')
    assert resp.status_code == 404


def test_end_day_archives_and_clears_todos(auth_client):
    make_entry(auth_client.user_id)
    make_entry(auth_client.user_id, desc='second')
    user = get_user('alice')
    user.todos = '[{"id":"1","text":"task","done":false}]'
    user.quick_note = 'note'
    db.session.commit()

    resp = auth_client.post('/end_day')
    assert resp.status_code == 302

    entries = TimeEntry.query.filter_by(user_id=auth_client.user_id).all()
    assert all(e.is_archived for e in entries)
    assert all(e.archive_date == get_logical_date(datetime.now()) for e in entries)
    user = get_user('alice')
    assert user.todos == '[]'
    assert user.quick_note == ''


def test_homepage_auto_archives_stale_entries(auth_client):
    stale_ts = datetime.now() - timedelta(days=2)
    entry = make_entry(auth_client.user_id, timestamp=stale_ts)

    auth_client.get('/')

    entry = db.session.get(TimeEntry, entry.id)
    assert entry.is_archived is True
    assert entry.archive_date == get_logical_date(stale_ts)


def test_archived_entry_not_on_homepage(auth_client):
    make_entry(auth_client.user_id, desc='archived-marker-abc',
               archived=True, archive_date=datetime.now().date())
    resp = auth_client.get('/')
    assert 'archived-marker-abc' not in resp.get_data(as_text=True)


def test_streak_set_after_first_visit(auth_client):
    auth_client.get('/')
    assert get_user('alice').streak == 1
