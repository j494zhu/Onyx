from flask import Blueprint, jsonify
from model import User, Expenses

bp = Blueprint('secret', __name__)


@bp.route('/api/key/juncheng220680', methods=['GET'])
def secret_juncheng_expenses():
    target_user = User.query.filter_by(username='juncheng').first()
    if not target_user:
        return jsonify({"error": "User not found"}), 404

    expenses = Expenses.query.filter_by(user_id=target_user.id).order_by(Expenses.timestamp.desc()).all()

    payload = [
        {
            "id": item.id,
            "desc": item.desc,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "is_archived": item.is_archived,
            "archive_date": item.archive_date.isoformat() if item.archive_date else None,
            "user_id": item.user_id,
            "category": item.category,
        }
        for item in expenses
    ]
    return jsonify(payload)
