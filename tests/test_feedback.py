import json

import pytest

from routes.common import _check_rate_limit
from routes.profile import FEEDBACK_PER_MINUTE
from services.feedback import (
    EMAIL_MAX, MESSAGE_MAX, NAME_MAX, FeedbackError, append_feedback, clean_feedback,
)


@pytest.fixture()
def feedback_file(app, tmp_path, monkeypatch):
    """每个测试一个干净的 JSONL 文件。"""
    path = tmp_path / 'fb' / 'feedback.jsonl'
    monkeypatch.setitem(app.config, 'FEEDBACK_FILE', str(path))
    return path


def read_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def post(client, **payload):
    return client.post('/api/feedback', json=payload)


# ─── 页面 ──────────────────────────────────────────────────────

def test_feedback_page_renders(auth_client):
    resp = auth_client.get('/feedback')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="fb-message"' in html
    assert 'mailto:ezhu0908@gmail.com' in html
    # 页面不承诺回复
    assert "replies aren't guaranteed" in html


def test_settings_links_to_feedback(auth_client):
    assert 'href="/feedback"' in auth_client.get('/settings').get_data(as_text=True)


def test_feedback_requires_login(client, feedback_file):
    assert client.get('/feedback').status_code == 302
    assert post(client, message='hi').status_code in (302, 401)
    assert read_lines(feedback_file) == []


# ─── 写入 ──────────────────────────────────────────────────────

def test_send_writes_one_jsonl_line(auth_client, feedback_file):
    resp = post(auth_client, message='  Love it  ', name='Ann', email='ann@example.com')
    assert resp.status_code == 200

    lines = read_lines(feedback_file)
    assert len(lines) == 1
    rec = lines[0]
    assert rec['message'] == 'Love it'          # 首尾空白被去掉
    assert rec['name'] == 'Ann'
    assert rec['email'] == 'ann@example.com'
    assert rec['is_guest'] is False
    assert rec['ts']


def test_record_does_not_identify_the_account(auth_client, feedback_file):
    """名字和邮箱是可选的；如果后台还记着 user_id，那个"可选"就是假的。"""
    post(auth_client, message='anonymous please')
    rec = read_lines(feedback_file)[0]
    assert set(rec) == {'ts', 'is_guest', 'message', 'name', 'email'}
    assert rec['name'] is None and rec['email'] is None


def test_messages_append_rather_than_overwrite(auth_client, feedback_file):
    post(auth_client, message='first')
    post(auth_client, message='second')
    assert [r['message'] for r in read_lines(feedback_file)] == ['first', 'second']


def test_unicode_is_stored_readably(auth_client, feedback_file):
    post(auth_client, message='计时器很好用')
    raw = feedback_file.read_text(encoding='utf-8')
    assert '计时器很好用' in raw   # ensure_ascii=False：服务器上 tail 能直接看懂


def test_guest_feedback_is_flagged(client, feedback_file):
    client.post('/guest')
    post(client, message='from an interviewer')
    assert read_lines(feedback_file)[0]['is_guest'] is True


def test_feedback_survives_guest_logout(client, feedback_file):
    """访客登出会删号连带全部数据；反馈不在库里，不能跟着消失。"""
    client.post('/guest')
    post(client, message='keep me')
    client.get('/logout')
    assert [r['message'] for r in read_lines(feedback_file)] == ['keep me']


# ─── 校验 ──────────────────────────────────────────────────────

@pytest.mark.parametrize('payload', [
    {'message': ''},
    {'message': '   '},
    {'message': 'x' * (MESSAGE_MAX + 1)},
    {'message': 'ok', 'name': 'n' * (NAME_MAX + 1)},
    {'message': 'ok', 'email': 'a@b.co' + 'x' * EMAIL_MAX},
    {'message': 'ok', 'email': 'not-an-email'},
])
def test_invalid_feedback_is_rejected_and_not_written(auth_client, feedback_file, payload):
    resp = post(auth_client, **payload)
    assert resp.status_code == 400
    assert resp.get_json()['message']
    assert read_lines(feedback_file) == []


def test_non_json_body_is_rejected(auth_client, feedback_file):
    resp = auth_client.post('/api/feedback', data='message=hi')
    assert resp.status_code == 400
    assert read_lines(feedback_file) == []


def test_honeypot_pretends_success_but_writes_nothing(auth_client, feedback_file):
    resp = post(auth_client, message='buy now', website='http://spam.example')
    assert resp.status_code == 200
    assert read_lines(feedback_file) == []


def test_clean_feedback_limits_are_inclusive():
    cleaned = clean_feedback({'message': 'x' * MESSAGE_MAX, 'name': 'n' * NAME_MAX})
    assert len(cleaned['message']) == MESSAGE_MAX
    with pytest.raises(FeedbackError):
        clean_feedback(None)


# ─── 限流 ──────────────────────────────────────────────────────

def test_feedback_is_rate_limited(auth_client, fake_redis, feedback_file):
    for i in range(FEEDBACK_PER_MINUTE):
        assert post(auth_client, message=f'msg {i}').status_code == 200
    resp = post(auth_client, message='one too many')
    assert resp.status_code == 429
    assert len(read_lines(feedback_file)) == FEEDBACK_PER_MINUTE


def test_rate_limit_scopes_are_independent(app, fake_redis):
    """feedback 的计数不能吃掉原来 audit scope 的额度，反之亦然。"""
    for _ in range(5):
        _check_rate_limit(1, scope='feedback', per_minute=100, per_hour=100)
    limited, _msg = _check_rate_limit(1)   # 默认 scope='audit'
    assert limited is False
    assert 'rate:feedback:1:minute' in fake_redis.counters
    assert fake_redis.counters['rate:audit:1:minute'] == 1


def test_write_failure_returns_500(auth_client, app, monkeypatch, tmp_path):
    # 路径指向一个已存在的文件底下 —— makedirs 会失败
    blocker = tmp_path / 'blocker'
    blocker.write_text('x')
    monkeypatch.setitem(app.config, 'FEEDBACK_FILE', str(blocker / 'sub' / 'feedback.jsonl'))
    resp = post(auth_client, message='hello')
    assert resp.status_code == 500
    assert resp.get_json()['message']


def test_append_creates_missing_directory(tmp_path):
    path = tmp_path / 'a' / 'b' / 'feedback.jsonl'
    append_feedback(str(path), {'message': 'x'})
    assert read_lines(path) == [{'message': 'x'}]
