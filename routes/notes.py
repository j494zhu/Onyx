import json

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from model import db
from routes.common import (
    sanitize_todos, publish_user_event,
    EVENT_NOTEBOOKS_UPDATED, EVENT_TODOS_UPDATED,
    load_notebooks, next_notebook_id,
    NOTEBOOK_NAME_MAX, NOTEBOOK_CONTENT_MAX, NOTEBOOK_MAX_COUNT,
    DEFAULT_NOTEBOOK_NAME, now_local,
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


@bp.route('/api/todos', methods=['POST'])
@login_required
def save_todos():
    data = request.json or {}
    todos = sanitize_todos(data.get('todos', []))

    current_user.todos = json.dumps(todos)
    db.session.commit()

    saved_at = now_local().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_TODOS_UPDATED, {
        'todos': todos,
        'saved_at': saved_at,
    })
    return jsonify({"status": "success", "saved_at": saved_at, "todos": todos})
