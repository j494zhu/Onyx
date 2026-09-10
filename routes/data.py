import json
import time

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from model import db

bp = Blueprint('data', __name__)


@bp.route('/api/pomodoro', methods=['POST'])
@login_required
def pomodoro_save():
    try:
        data = request.get_json(silent=True) or json.loads(request.get_data(as_text=True) or '{}')
    except (ValueError, TypeError):
        data = {}
    state = {
        'remaining_seconds': int(data.get('remaining_seconds', 1500)),
        'phase': data.get('phase', 'WORK'),
        'cycle_count': int(data.get('cycle_count', 0)),
        'running': bool(data.get('running', False)),
        'paused_at': time.time(),
    }
    current_user.pomodoro_state = json.dumps(state)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/pomodoro', methods=['GET'])
@login_required
def pomodoro_load():
    raw = current_user.pomodoro_state
    if not raw:
        return jsonify({'state': None, 'server_now': time.time()})
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return jsonify({'state': None, 'server_now': time.time()})
    state['server_now'] = time.time()
    return jsonify({'state': state, 'server_now': state['server_now']})
