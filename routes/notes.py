import json

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from model import db
from routes.common import (
    sanitize_todos, publish_user_event,
    EVENT_NOTEBOOKS_UPDATED, EVENT_TODO_LISTS_UPDATED,
    load_notebooks, next_notebook_id,
    NOTEBOOK_NAME_MAX, NOTEBOOK_CONTENT_MAX, NOTEBOOK_MAX_COUNT,
    DEFAULT_NOTEBOOK_NAME, now_local,
    load_todo_lists, next_list_id,
    TODO_LIST_NAME_MAX, TODO_LIST_MAX_COUNT, DEFAULT_TODO_LIST_NAME,
)

bp = Blueprint('notes', __name__)


def _persist_notebooks(books, active_id):
    """写库 + 广播，返回 (payload, saved_at)。四个 notebook 接口共用这一段收尾。"""
    current_user.notebooks = json.dumps(books)
    db.session.commit()

    saved_at = now_local().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_NOTEBOOKS_UPDATED, {
        'notebooks': books,
        'active_id': active_id,
        'saved_at': saved_at,
    })
    return saved_at


@bp.route('/api/notebooks/save', methods=['POST'])
@login_required
def save_notebook():
    """自动保存某一本的正文。前端 debounce 后调用，是最高频的那个。"""
    data = request.get_json(silent=True) or {}
    nb_id = str(data.get('id') or '').strip()
    content = data.get('content', '')
    if not isinstance(content, str):
        content = ''

    books = load_notebooks(current_user)
    target = next((b for b in books if b['id'] == nb_id), None)
    if target is None:
        return jsonify({'status': 'error', 'message': 'Notebook not found'}), 404

    target['content'] = content[:NOTEBOOK_CONTENT_MAX]
    saved_at = _persist_notebooks(books, nb_id)
    return jsonify({'status': 'success', 'saved_at': saved_at})


@bp.route('/api/notebooks/create', methods=['POST'])
@login_required
def create_notebook():
    data = request.get_json(silent=True) or {}
    books = load_notebooks(current_user)

    if len(books) >= NOTEBOOK_MAX_COUNT:
        return jsonify({
            'status': 'error',
            'message': f'Limit reached ({NOTEBOOK_MAX_COUNT} notebooks).',
        }), 400

    name = str(data.get('name', '')).strip()[:NOTEBOOK_NAME_MAX]
    if not name:
        name = f'{DEFAULT_NOTEBOOK_NAME} {len(books) + 1}'

    new_book = {'id': next_notebook_id(books), 'name': name, 'content': ''}
    books.append(new_book)

    saved_at = _persist_notebooks(books, new_book['id'])
    return jsonify({
        'status': 'success',
        'notebook': new_book,
        'notebooks': books,
        'active_id': new_book['id'],
        'saved_at': saved_at,
    })


@bp.route('/api/notebooks/rename', methods=['POST'])
@login_required
def rename_notebook():
    data = request.get_json(silent=True) or {}
    nb_id = str(data.get('id') or '').strip()
    name = str(data.get('name', '')).strip()[:NOTEBOOK_NAME_MAX]

    books = load_notebooks(current_user)
    target = next((b for b in books if b['id'] == nb_id), None)
    if target is None:
        return jsonify({'status': 'error', 'message': 'Notebook not found'}), 404

    target['name'] = name or DEFAULT_NOTEBOOK_NAME
    saved_at = _persist_notebooks(books, nb_id)
    return jsonify({
        'status': 'success',
        'notebooks': books,
        'active_id': nb_id,
        'saved_at': saved_at,
    })


@bp.route('/api/notebooks/delete', methods=['POST'])
@login_required
def delete_notebook():
    data = request.get_json(silent=True) or {}
    nb_id = str(data.get('id') or '').strip()

    books = load_notebooks(current_user)
    if len(books) <= 1:
        return jsonify({
            'status': 'error',
            'message': 'Cannot delete the last notebook.',
        }), 400

    idx = next((i for i, b in enumerate(books) if b['id'] == nb_id), None)
    if idx is None:
        return jsonify({'status': 'error', 'message': 'Notebook not found'}), 404

    books.pop(idx)
    # 删完后落到右边一本；删的是最后一本就落到新的最后一本。
    active_id = books[min(idx, len(books) - 1)]['id']

    saved_at = _persist_notebooks(books, active_id)
    return jsonify({
        'status': 'success',
        'notebooks': books,
        'active_id': active_id,
        'saved_at': saved_at,
    })


# ─── 多 To-Do list ───────────────────────────────────────────
# 四个接口和 notebook 一一对应：save（改某一个 list 的条目）、create、rename、delete。
# 每次都写整个数组并广播一条 todolists_updated（带完整数组 + active_id）。

def _persist_todo_lists(lists, active_id):
    """写库 + 广播，返回 saved_at。四个 to-do list 接口共用这一段收尾。"""
    current_user.todo_lists = json.dumps(lists)
    db.session.commit()

    saved_at = now_local().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_TODO_LISTS_UPDATED, {
        'lists': lists,
        'active_id': active_id,
        'saved_at': saved_at,
    })
    return saved_at


@bp.route('/api/todolists/save', methods=['POST'])
@login_required
def save_todo_list():
    """保存某一个 list 的全部条目。勾选 / 增删 / 改文字都走这里，是最高频的那个。"""
    data = request.get_json(silent=True) or {}
    list_id = str(data.get('id') or '').strip()
    todos = sanitize_todos(data.get('todos', []))

    lists = load_todo_lists(current_user)
    target = next((l for l in lists if l['id'] == list_id), None)
    if target is None:
        return jsonify({'status': 'error', 'message': 'To-do list not found'}), 404

    target['todos'] = todos
    saved_at = _persist_todo_lists(lists, list_id)
    return jsonify({'status': 'success', 'saved_at': saved_at, 'todos': todos})


@bp.route('/api/todolists/create', methods=['POST'])
@login_required
def create_todo_list():
    data = request.get_json(silent=True) or {}
    lists = load_todo_lists(current_user)

    if len(lists) >= TODO_LIST_MAX_COUNT:
        return jsonify({
            'status': 'error',
            'message': f'Limit reached ({TODO_LIST_MAX_COUNT} to-do lists).',
        }), 400

    name = str(data.get('name', '')).strip()[:TODO_LIST_NAME_MAX]
    if not name:
        name = f'{DEFAULT_TODO_LIST_NAME} {len(lists) + 1}'

    new_list = {'id': next_list_id(lists), 'name': name, 'todos': []}
    lists.append(new_list)

    saved_at = _persist_todo_lists(lists, new_list['id'])
    return jsonify({
        'status': 'success',
        'list': new_list,
        'lists': lists,
        'active_id': new_list['id'],
        'saved_at': saved_at,
    })


@bp.route('/api/todolists/rename', methods=['POST'])
@login_required
def rename_todo_list():
    data = request.get_json(silent=True) or {}
    list_id = str(data.get('id') or '').strip()
    name = str(data.get('name', '')).strip()[:TODO_LIST_NAME_MAX]

    lists = load_todo_lists(current_user)
    target = next((l for l in lists if l['id'] == list_id), None)
    if target is None:
        return jsonify({'status': 'error', 'message': 'To-do list not found'}), 404

    target['name'] = name or DEFAULT_TODO_LIST_NAME
    saved_at = _persist_todo_lists(lists, list_id)
    return jsonify({
        'status': 'success',
        'lists': lists,
        'active_id': list_id,
        'saved_at': saved_at,
    })


@bp.route('/api/todolists/delete', methods=['POST'])
@login_required
def delete_todo_list():
    data = request.get_json(silent=True) or {}
    list_id = str(data.get('id') or '').strip()

    lists = load_todo_lists(current_user)
    if len(lists) <= 1:
        return jsonify({
            'status': 'error',
            'message': 'Cannot delete the last to-do list.',
        }), 400

    idx = next((i for i, l in enumerate(lists) if l['id'] == list_id), None)
    if idx is None:
        return jsonify({'status': 'error', 'message': 'To-do list not found'}), 404

    lists.pop(idx)
    # 删完后落到右边一个；删的是最后一个就落到新的最后一个。
    active_id = lists[min(idx, len(lists) - 1)]['id']

    saved_at = _persist_todo_lists(lists, active_id)
    return jsonify({
        'status': 'success',
        'lists': lists,
        'active_id': active_id,
        'saved_at': saved_at,
    })
