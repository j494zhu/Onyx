import json
from datetime import date

from model import AlignmentSignal
from routes.common import _check_rate_limit

from conftest import make_entry, get_user


# --- /api/stats ---

def test_stats_endpoint(auth_client):
    make_entry(auth_client.user_id, desc='coding', start='10:00', end='11:00')
    make_entry(auth_client.user_id, desc='nap', start='13:00', end='13:30')
    resp = auth_client.get('/api/stats')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total_minutes'] == 90
    assert data['total_hours'] == 1.5
    assert data['deep_hours'] == 1.0  # 只有 coding 命中深度关键词


def test_stats_requires_login(client):
    assert client.get('/api/stats').status_code == 302


# --- /api/alignment ---

def test_alignment_stores_signal(auth_client):
    resp = auth_client.post('/api/alignment', json={
        'context': 'Tone: strict', 'response': 'AI said X', 'score': 5,
    })
    assert resp.status_code == 200
    signal = AlignmentSignal.query.filter_by(user_id=auth_client.user_id).first()
    assert signal is not None
    assert signal.reward_score == 5
    assert signal.input_context == 'Tone: strict'


# --- /api/pomodoro ---

def test_pomodoro_save_load_roundtrip(auth_client):
    resp = auth_client.post('/api/pomodoro', json={
        'remaining_seconds': 900, 'phase': 'BREAK',
        'cycle_count': 2, 'running': True,
    })
    assert resp.status_code == 200

    resp = auth_client.get('/api/pomodoro')
    state = resp.get_json()['state']
    assert state['remaining_seconds'] == 900
    assert state['phase'] == 'BREAK'
    assert state['cycle_count'] == 2
    assert state['running'] is True


def test_pomodoro_load_empty_state(auth_client):
    resp = auth_client.get('/api/pomodoro')
    assert resp.get_json()['state'] is None


def test_pomodoro_save_bad_payload_uses_defaults(auth_client):
    resp = auth_client.post('/api/pomodoro', data='not json',
                            content_type='application/json')
    assert resp.status_code == 200
    state = auth_client.get('/api/pomodoro').get_json()['state']
    assert state['remaining_seconds'] == 1500
    assert state['phase'] == 'WORK'


# --- /api/notes ---

def test_save_notebook(auth_client):
    resp = auth_client.post('/api/notes', json={
        'type': 'notebook', 'content': 'permanent notes',
    })
    assert resp.status_code == 200
    assert get_user('alice').notebook == 'permanent notes'


def test_save_quick_note(auth_client):
    auth_client.post('/api/notes', json={
        'type': 'quick_note', 'content': 'temp note',
    })
    assert get_user('alice').quick_note == 'temp note'


# --- /history ---

def test_history_day_mode_shows_archived(auth_client):
    make_entry(auth_client.user_id, desc='history-marker-123',
               archived=True, archive_date=date.today())
    resp = auth_client.get('/history')
    assert resp.status_code == 200
    assert 'history-marker-123' in resp.get_data(as_text=True)


def test_history_week_mode(auth_client):
    make_entry(auth_client.user_id, desc='week-marker-456',
               archived=True, archive_date=date.today())
    resp = auth_client.get('/history?mode=week&offset=0')
    assert resp.status_code == 200
    assert 'week-marker-456' in resp.get_data(as_text=True)


def test_history_requires_login(client):
    assert client.get('/history').status_code == 302


# --- 限流 helper ---

def test_rate_limit_disabled_without_redis(app):
    limited, msg = _check_rate_limit(1)
    assert limited is False


def test_rate_limit_per_minute(app, fake_redis):
    # 默认 3 次/分钟，第 4 次触发限流
    for _ in range(3):
        limited, _msg = _check_rate_limit(1)
        assert limited is False
    limited, msg = _check_rate_limit(1)
    assert limited is True
    assert 'minute' in msg


def test_rate_limit_is_per_user(app, fake_redis):
    for _ in range(4):
        _check_rate_limit(1)
    limited, _msg = _check_rate_limit(2)  # 另一个用户不受影响
    assert limited is False


# --- 硬编码导出接口应已删除 ---

def test_secret_export_endpoint_removed(client):
    resp = client.get('/api/key/juncheng220680')
    assert resp.status_code == 404
