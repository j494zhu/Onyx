from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from model import User, UserProfile

from conftest import register, login, get_user


def test_register_creates_user_and_profile(client):
    resp = register(client, 'alice', 'password123')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'

    user = get_user('alice')
    assert user is not None
    assert user.password != 'password123'  # 必须是哈希，不能存明文
    assert UserProfile.query.filter_by(user_id=user.id).first() is not None


def test_register_duplicate_username_rejected(client):
    register(client, 'alice', 'password123')
    resp = register(client, 'alice', 'other-password')
    assert resp.status_code == 200  # 留在注册页
    assert User.query.filter_by(username='alice').count() == 1


def test_register_password_mismatch_rejected(client):
    resp = client.post('/register', data={
        'username': 'bob',
        'password': 'aaa',
        'password-confirm': 'bbb',
    })
    assert resp.status_code == 200
    assert get_user('bob') is None


def test_login_success_redirects_home(client):
    register(client, 'alice', 'password123')
    client.get('/logout')
    resp = login(client, 'alice', 'password123')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_login_wrong_password(client):
    register(client, 'alice', 'password123')
    client.get('/logout')
    resp = login(client, 'alice', 'wrong')
    assert resp.status_code == 200  # 留在登录页


def test_login_unknown_user(client):
    resp = login(client, 'ghost', 'whatever')
    assert resp.status_code == 200


def test_logout_ends_session(client):
    register(client, 'alice', 'password123')
    resp = client.get('/logout')
    assert resp.status_code == 302
    # 登出后首页应跳转到登录页
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_index_requires_login(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def _remember_cookie(resp):
    """返回响应里 remember_token 的那条 Set-Cookie（没有则 None）。"""
    for header in resp.headers.getlist('Set-Cookie'):
        if header.startswith('remember_token='):
            return header
    return None


def test_login_issues_a_14_day_remember_cookie(client):
    """session cookie 关浏览器就没了；remember_token 让登录保持 14 天。"""
    register(client, 'alice', 'password123')
    client.get('/logout')
    cookie = _remember_cookie(login(client, 'alice', 'password123'))
    assert cookie is not None
    expires = parsedate_to_datetime(cookie.split('Expires=')[1].split(';')[0])
    lifetime = expires - datetime.now(timezone.utc)
    assert timedelta(days=13, hours=23) < lifetime <= timedelta(days=14)
    assert 'HttpOnly' in cookie
    assert 'SameSite=Lax' in cookie


def test_register_also_remembers_the_login(client):
    assert _remember_cookie(register(client, 'bob', 'password123')) is not None


def test_remember_cookie_restores_login_without_session(client):
    """模拟关掉浏览器：删掉 session cookie，只剩 remember_token，仍然是登录状态。"""
    register(client, 'alice', 'password123')
    client.delete_cookie('session')
    assert client.get('/').status_code == 200


def test_logout_clears_the_remember_cookie(client):
    register(client, 'alice', 'password123')
    resp = client.get('/logout')
    cookie = _remember_cookie(resp)
    assert cookie is not None and ('Max-Age=0' in cookie or 'Expires=Thu, 01 Jan 1970' in cookie)
    client.delete_cookie('session')
    assert client.get('/').status_code in (302, 401)


def test_guest_login_is_not_remembered(client):
    """guest 在 logout 或 24h 后被删，不需要跨浏览器重启保持登录。"""
    assert _remember_cookie(client.post('/guest')) is None
