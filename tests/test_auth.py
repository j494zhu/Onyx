from model import User, UserProfile

from conftest import register, login, get_user


def test_register_creates_user_and_profile(client):
    resp = register(client, 'alice', 'password123')
    assert resp.status_code == 302
    assert '/onboarding' in resp.headers['Location']

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
