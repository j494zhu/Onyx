import json
from types import SimpleNamespace

from routes.common import (
    sanitize_todos, load_todos, migrate_quick_note_to_todos, todos_to_text,
)

from conftest import get_user


# --- sanitize_todos ---

def test_sanitize_rejects_non_list():
    assert sanitize_todos('not a list') == []
    assert sanitize_todos({'text': 'x'}) == []
    assert sanitize_todos(None) == []


def test_sanitize_skips_non_dict_items():
    assert sanitize_todos(['string', 42, {'text': 'ok'}]) == [
        {'id': '1', 'text': 'ok', 'done': False}
    ]


def test_sanitize_skips_empty_text():
    assert sanitize_todos([{'text': '   '}, {'text': ''}, {}]) == []


def test_sanitize_truncates_long_text():
    result = sanitize_todos([{'text': 'x' * 1000}])
    assert len(result[0]['text']) == 500


def test_sanitize_caps_at_200_items():
    items = [{'text': f'task {i}'} for i in range(300)]
    assert len(sanitize_todos(items)) == 200


def test_sanitize_coerces_done_to_bool():
    result = sanitize_todos([{'text': 'a', 'done': 1}, {'text': 'b'}])
    assert result[0]['done'] is True
    assert result[1]['done'] is False


def test_sanitize_assigns_missing_ids():
    result = sanitize_todos([{'text': 'a'}, {'id': 'custom', 'text': 'b'}])
    assert result[0]['id'] == '1'
    assert result[1]['id'] == 'custom'


# --- load_todos ---

def test_load_todos_invalid_json_returns_empty():
    user = SimpleNamespace(todos='{broken json')
    assert load_todos(user) == []


def test_load_todos_none_returns_empty():
    user = SimpleNamespace(todos=None)
    assert load_todos(user) == []


def test_load_todos_valid():
    user = SimpleNamespace(todos='[{"id": "7", "text": "hi", "done": true}]')
    assert load_todos(user) == [{'id': '7', 'text': 'hi', 'done': True}]


# --- migrate_quick_note_to_todos ---

def test_migrate_numbered_list():
    todos = migrate_quick_note_to_todos('1. buy milk\n2. write code')
    assert [t['text'] for t in todos] == ['buy milk', 'write code']
    assert all(t['done'] is False for t in todos)


def test_migrate_bullet_list():
    todos = migrate_quick_note_to_todos('- alpha\n* beta\n• gamma')
    assert [t['text'] for t in todos] == ['alpha', 'beta', 'gamma']


def test_migrate_continuation_lines_merge():
    todos = migrate_quick_note_to_todos('- first task\nmore detail\n- second')
    assert [t['text'] for t in todos] == ['first task more detail', 'second']


def test_migrate_empty_note():
    assert migrate_quick_note_to_todos('') == []
    assert migrate_quick_note_to_todos(None) == []


# --- todos_to_text ---

def test_todos_to_text_formats_checkboxes():
    text = todos_to_text([
        {'text': 'done task', 'done': True},
        {'text': 'open task', 'done': False},
    ])
    assert text == '[x] done task\n[ ] open task'


def test_todos_to_text_empty():
    assert todos_to_text([]) == ''


# --- POST /api/todos ---

def test_save_todos_persists_and_sanitizes(auth_client):
    resp = auth_client.post('/api/todos', json={
        'todos': [{'text': 'valid'}, {'text': ''}, 'junk'],
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'
    assert [t['text'] for t in data['todos']] == ['valid']

    user = get_user('alice')
    assert json.loads(user.todos) == data['todos']


def test_save_todos_requires_login(client):
    resp = client.post('/api/todos', json={'todos': []})
    assert resp.status_code == 302
