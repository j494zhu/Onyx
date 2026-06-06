import json
import time

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from model import db, Expenses, AlignmentSignal
from services.stats import calculate_stats_from_logs, calculate_duration

bp = Blueprint('data', __name__)


@bp.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    total_h, deep_h = calculate_stats_from_logs(active_items)
    total_minutes = sum(calculate_duration(item.start_time, item.end_time) for item in active_items)
    return jsonify({
        "total_minutes": total_minutes,
        "total_hours": total_h,
        "deep_hours": deep_h,
    })


@bp.route('/api/alignment', methods=['POST'])
@login_required
def submit_alignment():
    try:
        data = request.json

        new_signal = AlignmentSignal(
            user_id=current_user.id,
            input_context=data.get('context', 'Unknown Context'),
            ai_response=data.get('response', 'User Feedback'),
            reward_score=data.get('score', 0)
        )

        db.session.add(new_signal)
        db.session.commit()

        return jsonify({"status": "success", "message": "Signal Captured"})

    except Exception as e:
        print(f"Alignment Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
