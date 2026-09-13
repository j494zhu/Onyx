import json
from types import SimpleNamespace

from model import db
from routes.common import (
    sanitize_todo_lists, load_todo_lists, next_list_id,
    TODO_LIST_NAME_MAX, TODO_LIST_MAX_COUNT, DEFAULT_TODO_LIST_NAME,
)

from conftest import get_user


# --- sanitize_todo_lists ---

def test_sanitize_drops_non_dict_and_fills_defaults():
    lists = sanitize_todo_lists([
        {'id': '1', 'name': 'Work', 'todos': [{'id': 'a', 'text': 'x', 'done': True}]},
        'garbage',
        {'id': '2'},                      # 缺 name/todos
    ])
    assert lists == [
        {'id': '1', 'name': 'Work', 'todos': [{'id': 'a', 'text': 'x', 'done': True}]},
        {'id': '2', 'name': DEFAULT_TODO_LIST_NAME, 'todos': []},
    ]


def test_sanitize_rejects_non_list():
    assert sanitize_todo_lists(None) == []
    assert sanitize_todo_lists({'id': '1'}) == []


def test_sanitize_truncates_name_and_dedupes_ids():
    lists = sanitize_todo_lists([
        {'id': '1', 'name': 'x' * 100, 'todos': []},
        {'id': '1', 'name': 'dup', 'todos': []},   # 重复 id 要被改写
    ])
    assert len(lists[0]['name']) == TODO_LIST_NAME_MAX
    assert lists[0]['id'] != lists[1]['id']


def test_sanitize_caps_count():
    many = [{'id': str(i), 'name': f'n{i}', 'todos': []} for i in range(60)]
    assert len(sanitize_todo_lists(many)) == TODO_LIST_MAX_COUNT


def test_sanitize_runs_todo_sanitizer_on_items():
    lists = sanitize_todo_lists([{'id': '1', 'name': 'a', 'todos': [{'text': ''}, 'junk', {'text': 'ok'}]}])
    assert [t['text'] for t in lists[0]['todos']] == ['ok']


# --- load_todo_lists / 迁移 ---

def test_load_migrates_legacy_todos():
    user = SimpleNamespace(todo_lists=None, todos='[{"id": "7", "text": "hi", "done": true}]')
    lists = load_todo_lists(user)
    assert len(lists) == 1
    assert lists[0]['todos'] == [{'id': '7', 'text': 'hi', 'done': True}]
    # 旧列保留不动，作为迁移前的备份
    assert user.todos == '[{"id": "7", "text": "hi", "done": true}]'


def test_load_always_returns_at_least_one():
    user = SimpleNamespace(todo_lists='[]', todos='[]')
    lists = load_todo_lists(user)
    assert len(lists) == 1
    assert lists[0]['todos'] == []


def test_load_survives_corrupt_json():
    user = SimpleNamespace(todo_lists='{not json', todos='[{"id":"1","text":"fallback"}]')
    lists = load_todo_lists(user)
    assert lists[0]['todos'][0]['text'] == 'fallback'


def test_next_list_id_avoids_collisions():
    assert next_list_id([{'id': '1'}, {'id': '2'}, {'id': '3'}]) not in {'1', '2', '3'}


# --- 端点 ---

def _lists(client):
    resp = client.get('/')
    assert resp.status_code == 200
    return json.loads(get_user('alice').todo_lists)


def test_dashboard_seeds_todo_lists_column(auth_client):
    user = get_user('alice')
    user.todos = '[{"id":"1","text":"seeded","done":false}]'
    user.todo_lists = None
    db.session.commit()

    lists = _lists(auth_client)
    assert len(lists) == 1
    assert lists[0]['todos'][0]['text'] == 'seeded'


def test_dashboard_migrates_quick_note_then_seeds_lists(auth_client):
    user = get_user('alice')
    user.todos = '[]'
    user.quick_note = '- alpha\n- beta'
    user.todo_lists = None
    db.session.commit()

    lists = _lists(auth_client)
    assert [t['text'] for t in lists[0]['todos']] == ['alpha', 'beta']
    assert get_user('alice').quick_note == ''


def test_create_todo_list(auth_client):
    _lists(auth_client)
    resp = auth_client.post('/api/todolists/create', json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['lists']) == 2
    assert data['active_id'] == data['list']['id']
    assert data['list']['todos'] == []


def test_create_todo_list_with_name(auth_client):
    _lists(auth_client)
    resp = auth_client.post('/api/todolists/create', json={'name': 'Groceries'})
    assert resp.get_json()['list']['name'] == 'Groceries'


def test_create_todo_list_respects_cap(auth_client):
    _lists(auth_client)
    for _ in range(TODO_LIST_MAX_COUNT - 1):
        assert auth_client.post('/api/todolists/create', json={}).status_code == 200
    resp = auth_client.post('/api/todolists/create', json={})
    assert resp.status_code == 400
    assert 'Limit' in resp.get_json()['message']


def test_save_todo_list_persists_and_sanitizes(auth_client):
    lists = _lists(auth_client)
    resp = auth_client.post('/api/todolists/save', json={
        'id': lists[0]['id'],
        'todos': [{'text': 'valid'}, {'text': ''}, 'junk'],
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'
    assert [t['text'] for t in data['todos']] == ['valid']

    stored = json.loads(get_user('alice').todo_lists)
    assert stored[0]['todos'] == data['todos']


def test_save_only_touches_target_list(auth_client):
    _lists(auth_client)
    second = auth_client.post('/api/todolists/create', json={}).get_json()
    first_id = json.loads(get_user('alice').todo_lists)[0]['id']

    auth_client.post('/api/todolists/save', json={'id': first_id, 'todos': [{'text': 'AAA'}]})
    auth_client.post('/api/todolists/save',
                     json={'id': second['list']['id'], 'todos': [{'text': 'BBB', 'done': True}]})

    stored = {l['id']: l['todos'] for l in json.loads(get_user('alice').todo_lists)}
    assert [t['text'] for t in stored[first_id]] == ['AAA']
    assert [t['text'] for t in stored[second['list']['id']]] == ['BBB']
    assert stored[second['list']['id']][0]['done'] is True


def test_save_unknown_list_404(auth_client):
    _lists(auth_client)
    resp = auth_client.post('/api/todolists/save', json={'id': 'nope', 'todos': []})
    assert resp.status_code == 404


def test_rename_todo_list(auth_client):
    lists = _lists(auth_client)
    resp = auth_client.post('/api/todolists/rename',
                            json={'id': lists[0]['id'], 'name': 'Chores'})
    assert resp.status_code == 200
    assert json.loads(get_user('alice').todo_lists)[0]['name'] == 'Chores'


def test_rename_blank_falls_back_to_default(auth_client):
    lists = _lists(auth_client)
    auth_client.post('/api/todolists/rename', json={'id': lists[0]['id'], 'name': '   '})
    assert json.loads(get_user('alice').todo_lists)[0]['name'] == DEFAULT_TODO_LIST_NAME


def test_delete_todo_list(auth_client):
    _lists(auth_client)
    created = auth_client.post('/api/todolists/create', json={}).get_json()
    resp = auth_client.post('/api/todolists/delete', json={'id': created['list']['id']})
    assert resp.status_code == 200
    assert len(resp.get_json()['lists']) == 1


def test_delete_last_todo_list_refused(auth_client):
    lists = _lists(auth_client)
    assert len(lists) == 1
    resp = auth_client.post('/api/todolists/delete', json={'id': lists[0]['id']})
    assert resp.status_code == 400
    assert 'last to-do list' in resp.get_json()['message']
    assert len(json.loads(get_user('alice').todo_lists)) == 1


def test_delete_returns_neighbour_as_active(auth_client):
    _lists(auth_client)
    a = json.loads(get_user('alice').todo_lists)[0]['id']
    b = auth_client.post('/api/todolists/create', json={}).get_json()['list']['id']

    resp = auth_client.post('/api/todolists/delete', json={'id': a})
    assert resp.get_json()['active_id'] == b


def test_delete_unknown_list_404(auth_client):
    _lists(auth_client)
    auth_client.post('/api/todolists/create', json={})
    resp = auth_client.post('/api/todolists/delete', json={'id': 'nope'})
    assert resp.status_code == 404


def test_todo_list_endpoints_require_login(client):
    for path in ('save', 'create', 'rename', 'delete'):
        resp = client.post(f'/api/todolists/{path}', json={})
        assert resp.status_code == 302, path


def test_todo_list_save_publishes_sse(auth_client, fake_redis):
    lists = _lists(auth_client)
    auth_client.post('/api/todolists/save',
                     json={'id': lists[0]['id'], 'todos': [{'text': 'sync me'}]})
    published = [json.loads(m) for _c, m in fake_redis.published]
    assert any(p['event'] == 'todolists_updated' for p in published)
    payload = next(p for p in published if p['event'] == 'todolists_updated')['data']
    assert set(payload) == {'lists', 'active_id', 'saved_at'}
    assert payload['active_id'] == lists[0]['id']


def test_end_day_leaves_todo_lists_untouched(auth_client):
    _lists(auth_client)
    second = auth_client.post('/api/todolists/create', json={'name': 'Side'}).get_json()
    first_id = json.loads(get_user('alice').todo_lists)[0]['id']
    auth_client.post('/api/todolists/save', json={'id': first_id, 'todos': [{'text': 'a'}]})
    auth_client.post('/api/todolists/save', json={'id': second['list']['id'], 'todos': [{'text': 'b'}]})

    before = get_user('alice').todo_lists

    assert auth_client.post('/end_day').status_code == 302

    assert get_user('alice').todo_lists == before
    lists = json.loads(before)
    assert [l['name'] for l in lists] == [DEFAULT_TODO_LIST_NAME, 'Side']
    assert [[t['text'] for t in l['todos']] for l in lists] == [['a'], ['b']]


def test_export_lists_each_todo_list_when_several(auth_client):
    _lists(auth_client)
    second = auth_client.post('/api/todolists/create', json={'name': 'Side'}).get_json()
    first_id = json.loads(get_user('alice').todo_lists)[0]['id']
    auth_client.post('/api/todolists/save', json={'id': first_id, 'todos': [{'text': 'main task', 'done': True}]})
    auth_client.post('/api/todolists/save', json={'id': second['list']['id'], 'todos': [{'text': 'side task'}]})

    body = auth_client.get('/api/export/today').get_data(as_text=True)
    assert f'[{DEFAULT_TODO_LIST_NAME}]' in body
    assert '[Side]' in body
    assert '1. [x]  main task' in body
    assert '1. [ ]  side task' in body
    assert 'Completed: 1/1' in body
    assert 'Completed: 0/1' in body
