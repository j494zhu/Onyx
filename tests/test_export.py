from datetime import datetime

from model import db
from routes.common import get_logical_date

from conftest import get_user, make_entry


def test_export_today_requires_login(client):
    resp = client.get('/api/export/today')
    assert resp.status_code == 302


def test_export_today_contains_entries_and_todos(auth_client):
    make_entry(auth_client.user_id, desc='deep work session', start='09:00', end='10:30')
    make_entry(auth_client.user_id, desc='meeting', start='10:45', end='11:00')
    user = get_user('alice')
    user.todos = (
        '[{"id":"1","text":"finish report","done":true},'
        '{"id":"2","text":"exercise","done":false}]'
    )
    db.session.commit()

    resp = auth_client.get('/api/export/today')

    assert resp.status_code == 200
    assert resp.mimetype == 'text/plain'
    assert resp.headers['Content-Disposition'].startswith('attachment')

    date_label = get_logical_date(datetime.now()).strftime('%Y-%m-%d')
    assert resp.headers['Content-Disposition'] == f'attachment; filename="{date_label}.txt"'

    body = resp.get_data(as_text=True)
    assert f'ONYX DAILY LOG - {date_label}' in body
    assert 'HISTORY FLOW' in body
    assert '1. 09:00 - 10:30  |  deep work session' in body
    assert '2. 10:45 - 11:00  |  meeting' in body
    assert 'Total tracked: 1.8h' in body
    assert 'TO-DO LIST' in body
    assert '1. [x]  finish report' in body
    assert '2. [ ]  exercise' in body
    assert 'Completed: 1/2' in body


def test_export_today_empty_state(auth_client):
    resp = auth_client.get('/api/export/today')
    body = resp.get_data(as_text=True)
    assert '-- No Records Yet --' in body
    assert '-- No Tasks Yet --' in body


def test_export_today_ignores_archived_entries(auth_client):
    make_entry(auth_client.user_id, desc='stale-entry-zzz',
               archived=True, archive_date=datetime.now().date())
    resp = auth_client.get('/api/export/today')
    assert 'stale-entry-zzz' not in resp.get_data(as_text=True)
