import json

from model import db
from routes.common import (
    sanitize_notebooks, load_notebooks, next_notebook_id,
    NOTEBOOK_NAME_MAX, NOTEBOOK_MAX_COUNT, DEFAULT_NOTEBOOK_NAME,
)

from conftest import get_user


# --- sanitize_notebooks ---

def test_sanitize_drops_non_dict_and_fills_defaults():
    books = sanitize_notebooks([
        {'id': '1', 'name': 'Work', 'content': 'hello'},
        'garbage',
        {'id': '2'},                      # 缺 name/content
    ])
    assert books == [
        {'id': '1', 'name': 'Work', 'content': 'hello'},
        {'id': '2', 'name': DEFAULT_NOTEBOOK_NAME, 'content': ''},
    ]


def test_sanitize_rejects_non_list():
    assert sanitize_notebooks(None) == []
    assert sanitize_notebooks({'id': '1'}) == []


def test_sanitize_truncates_name_and_dedupes_ids():
    books = sanitize_notebooks([
        {'id': '1', 'name': 'x' * 100, 'content': ''},
        {'id': '1', 'name': 'dup', 'content': ''},   # 重复 id 要被改写
    ])
    assert len(books[0]['name']) == NOTEBOOK_NAME_MAX
    assert books[0]['id'] != books[1]['id']


def test_sanitize_caps_count():
    many = [{'id': str(i), 'name': f'n{i}', 'content': ''} for i in range(60)]
    assert len(sanitize_notebooks(many)) == NOTEBOOK_MAX_COUNT


def test_sanitize_coerces_non_string_content():
    books = sanitize_notebooks([{'id': '1', 'name': 'a', 'content': 123}])
    assert books[0]['content'] == ''


# --- load_notebooks / 迁移 ---

def test_load_migrates_legacy_notebook(app):
    user = get_user('alice') or _make_user()
    user.notebook = 'legacy long-term notes'
    user.notebooks = None
    db.session.commit()

    books = load_notebooks(user)
    assert len(books) == 1
    assert books[0]['content'] == 'legacy long-term notes'
    # 旧列保留不动，作为迁移前的备份
    assert user.notebook == 'legacy long-term notes'


def test_load_always_returns_at_least_one(app):
    user = _make_user('bob')
    user.notebook = ''
    user.notebooks = '[]'
    db.session.commit()
    books = load_notebooks(user)
    assert len(books) == 1
    assert books[0]['content'] == ''


def test_load_survives_corrupt_json(app):
    user = _make_user('carol')
    user.notebooks = '{not json'
    user.notebook = 'fallback'
    db.session.commit()
    books = load_notebooks(user)
    assert books[0]['content'] == 'fallback'


def test_next_notebook_id_avoids_collisions():
    books = [{'id': '1'}, {'id': '2'}, {'id': '3'}]
    assert next_notebook_id(books) not in {'1', '2', '3'}


def _make_user(username='alice'):
    from model import User
    from werkzeug.security import generate_password_hash
    u = User(username=username, password=generate_password_hash('password123'))
    db.session.add(u)
    db.session.commit()
    return u


# --- 端点 ---

def _books(client):
    resp = client.get('/')
    assert resp.status_code == 200
    return json.loads(get_user('alice').notebooks)


def test_dashboard_seeds_notebooks_column(auth_client):
    user = get_user('alice')
    user.notebook = 'seeded from legacy'
    user.notebooks = None
    db.session.commit()

    books = _books(auth_client)
    assert len(books) == 1
    assert books[0]['content'] == 'seeded from legacy'


def test_create_notebook(auth_client):
    _books(auth_client)
    resp = auth_client.post('/api/notebooks/create', json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['notebooks']) == 2
    assert data['active_id'] == data['notebook']['id']
    assert data['notebook']['content'] == ''


def test_create_notebook_with_name(auth_client):
    _books(auth_client)
    resp = auth_client.post('/api/notebooks/create', json={'name': 'Research'})
    assert resp.get_json()['notebook']['name'] == 'Research'


def test_create_notebook_respects_cap(auth_client):
    _books(auth_client)
    for _ in range(NOTEBOOK_MAX_COUNT - 1):
        assert auth_client.post('/api/notebooks/create', json={}).status_code == 200
    resp = auth_client.post('/api/notebooks/create', json={})
    assert resp.status_code == 400
    assert 'Limit' in resp.get_json()['message']


def test_save_notebook_content(auth_client):
    books = _books(auth_client)
    nb_id = books[0]['id']
    resp = auth_client.post('/api/notebooks/save',
                            json={'id': nb_id, 'content': 'written'})
    assert resp.status_code == 200
    stored = json.loads(get_user('alice').notebooks)
    assert stored[0]['content'] == 'written'


def test_save_only_touches_target_notebook(auth_client):
    _books(auth_client)
    second = auth_client.post('/api/notebooks/create', json={}).get_json()
    first_id = json.loads(get_user('alice').notebooks)[0]['id']

    auth_client.post('/api/notebooks/save', json={'id': first_id, 'content': 'AAA'})
    auth_client.post('/api/notebooks/save',
                     json={'id': second['notebook']['id'], 'content': 'BBB'})

    stored = {b['id']: b['content'] for b in json.loads(get_user('alice').notebooks)}
    assert stored[first_id] == 'AAA'
    assert stored[second['notebook']['id']] == 'BBB'


def test_save_unknown_notebook_404(auth_client):
    _books(auth_client)
    resp = auth_client.post('/api/notebooks/save',
                            json={'id': 'nope', 'content': 'x'})
    assert resp.status_code == 404


def test_rename_notebook(auth_client):
    books = _books(auth_client)
    resp = auth_client.post('/api/notebooks/rename',
                            json={'id': books[0]['id'], 'name': 'Ideas'})
    assert resp.status_code == 200
    assert json.loads(get_user('alice').notebooks)[0]['name'] == 'Ideas'


def test_rename_blank_falls_back_to_default(auth_client):
    books = _books(auth_client)
    auth_client.post('/api/notebooks/rename',
                     json={'id': books[0]['id'], 'name': '   '})
    assert json.loads(get_user('alice').notebooks)[0]['name'] == DEFAULT_NOTEBOOK_NAME


def test_delete_notebook(auth_client):
    _books(auth_client)
    created = auth_client.post('/api/notebooks/create', json={}).get_json()
    resp = auth_client.post('/api/notebooks/delete',
                            json={'id': created['notebook']['id']})
    assert resp.status_code == 200
    assert len(resp.get_json()['notebooks']) == 1


def test_delete_last_notebook_refused(auth_client):
    books = _books(auth_client)
    assert len(books) == 1
    resp = auth_client.post('/api/notebooks/delete', json={'id': books[0]['id']})
    assert resp.status_code == 400
    assert 'last notebook' in resp.get_json()['message']
    # 数据没被动
    assert len(json.loads(get_user('alice').notebooks)) == 1


def test_delete_returns_neighbour_as_active(auth_client):
    _books(auth_client)
    a = json.loads(get_user('alice').notebooks)[0]['id']
    b = auth_client.post('/api/notebooks/create', json={}).get_json()['notebook']['id']

    # 删中间那本（第一本），应落到右边一本
    resp = auth_client.post('/api/notebooks/delete', json={'id': a})
    assert resp.get_json()['active_id'] == b


def test_delete_unknown_notebook_404(auth_client):
    _books(auth_client)
    auth_client.post('/api/notebooks/create', json={})
    resp = auth_client.post('/api/notebooks/delete', json={'id': 'nope'})
    assert resp.status_code == 404


def test_notebook_endpoints_require_login(client):
    for path in ('save', 'create', 'rename', 'delete'):
        resp = client.post(f'/api/notebooks/{path}', json={})
        assert resp.status_code == 302, path


def test_notebook_save_publishes_sse(auth_client, fake_redis):
    books = _books(auth_client)
    auth_client.post('/api/notebooks/save',
                     json={'id': books[0]['id'], 'content': 'sync me'})
    events = [json.loads(m)['event'] for _c, m in fake_redis.published]
    assert 'notebooks_updated' in events
