from datetime import date

from routes.common import _check_rate_limit, get_logical_date, now_local

from conftest import make_entry


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


# --- /history ---

def test_history_day_mode_shows_archived(auth_client):
    # history 的"今天"是逻辑日期（06:00 分界），凌晨跑测试时和 date.today() 不同
    make_entry(auth_client.user_id, desc='history-marker-123',
               archived=True, archive_date=get_logical_date(now_local()))
    resp = auth_client.get('/history')
    assert resp.status_code == 200
    assert 'history-marker-123' in resp.get_data(as_text=True)


def test_history_week_mode(auth_client):
    make_entry(auth_client.user_id, desc='week-marker-456',
               archived=True, archive_date=get_logical_date(now_local()))
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
