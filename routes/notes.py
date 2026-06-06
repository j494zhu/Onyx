import json
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from routes.common import (
    sanitize_todos, publish_user_event,
    EVENT_NOTEBOOK_UPDATED, EVENT_TODOS_UPDATED,
)

bp = Blueprint('notes', __name__)


@bp.route('/api/notes', methods=['POST'])
@login_required
def save_notes():
    data = request.json
    note_type = data.get('type')
    content = data.get('content')

    if (note_type == 'quick_note'):
        current_user.quick_note = content
    else:
        current_user.notebook = content

    from model import db
    db.session.commit()
    saved_at = datetime.now().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_NOTEBOOK_UPDATED, {
        'type': note_type,
        'content': content,
        'saved_at': saved_at,
    })
    return jsonify({"status": "success", "saved_at": saved_at})


@bp.route('/api/todos', methods=['POST'])
@login_required
def save_todos():
    data = request.json or {}
    todos = sanitize_todos(data.get('todos', []))

    current_user.todos = json.dumps(todos)
    from model import db
    db.session.commit()

    saved_at = datetime.now().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_TODOS_UPDATED, {
        'todos': todos,
        'saved_at': saved_at,
    })
    return jsonify({"status": "success", "saved_at": saved_at, "todos": todos})
