import json
from datetime import date, timedelta

from conftest import (
    TimeEntry, register, make_entry, DummyDeepSeekResponse,
)

AUDIT_CONTENT = {
    'rubric': {'dimensions': [{'weight': 1.0, 'points': [{'score': 20}]}]},
    'status': 'green',
    'insight': 'well done',
    'warning': 'None',
}


def _mock_deepseek(monkeypatch, content):
    monkeypatch.setattr(
        'routes.ai.requests.post',
        lambda *args, **kwargs: DummyDeepSeekResponse(content),
    )


def test_audit_success(auth_client, monkeypatch):
    _mock_deepseek(monkeypatch, AUDIT_CONTENT)
    resp = auth_client.post('/api/ai/audit', json={
        'tone': 'strict', 'client_time': '2026-07-16 12:00',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['score'] == 100  # (20/20) * 100 * weight 1.0
    assert data['status'] == 'green'
    assert data['insight'] == 'well done'


def test_audit_session_cooldown_429(auth_client, monkeypatch):
    _mock_deepseek(monkeypatch, AUDIT_CONTENT)
    body = {'tone': 'strict', 'client_time': '2026-07-16 12:00'}
    assert auth_client.post('/api/ai/audit', json=body).status_code == 200
    # 15 秒冷却内的第二次调用应被拒绝
    resp = auth_client.post('/api/ai/audit', json=body)
    assert resp.status_code == 429


def test_audit_owner_exempt_from_cooldown(client, monkeypatch):
    register(client, 'juncheng', 'password123')
    _mock_deepseek(monkeypatch, AUDIT_CONTENT)
    body = {'tone': 'strict', 'client_time': '2026-07-16 12:00'}
    assert client.post('/api/ai/audit', json=body).status_code == 200
    assert client.post('/api/ai/audit', json=body).status_code == 200


def test_audit_requires_login(client):
    assert client.post('/api/ai/audit', json={}).status_code == 302


def test_visualize_no_data(auth_client):
    resp = auth_client.post('/api/visualize')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['labels'] == ['No Data Yet']
    assert data['total_minutes'] == 0


def test_visualize_assigns_categories(auth_client, monkeypatch):
    e1 = make_entry(auth_client.user_id, desc='write code',
                    start='10:00', end='11:00')
    e2 = make_entry(auth_client.user_id, desc='lunch',
                    start='12:00', end='12:30')
    _mock_deepseek(monkeypatch, {f'ID_{e1.id}': 'Coding', f'ID_{e2.id}': 'Break'})

    resp = auth_client.post('/api/visualize')
    assert resp.status_code == 200
    data = resp.get_json()
    assert sorted(data['labels']) == ['Break', 'Coding']
    assert data['total_minutes'] == 90

    from model import db
    assert db.session.get(TimeEntry, e1.id).category == 'Coding'
    assert db.session.get(TimeEntry, e2.id).category == 'Break'


def test_weekly_insight_needs_data(auth_client):
    resp = auth_client.post('/api/insights/weekly')
    assert resp.status_code == 400


def test_weekly_insight_with_logs(auth_client, monkeypatch):
    monkeypatch.setattr('routes.ai.gevent.sleep', lambda s: None)
    make_entry(auth_client.user_id, archived=True,
               archive_date=date.today() - timedelta(days=1))
    resp = auth_client.post('/api/insights/weekly')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'week_label' in data
    assert 'neural_phase' in data
