import json
from datetime import datetime, timedelta, date
from collections import OrderedDict
from itertools import groupby

from flask import Blueprint, render_template, request, redirect, jsonify
from flask_login import login_required, current_user
from model import db, User, Expenses, AlignmentSignal

from routes.common import (
    serialize_expense, is_ajax_request, publish_user_event,
    EVENT_EXPENSE_CREATED, EVENT_EXPENSE_DELETED,
    load_todos, migrate_quick_note_to_todos, get_logical_date,
    load_user_profile,
)
from services.stats import calculate_stats_from_logs
from services.streak import update_user_streak
from services.history_helper import build_day_stats

bp = Blueprint('main', __name__)


@bp.route('/', methods=["POST", "GET"])
@login_required
def index():
    if request.method == 'POST':
        item_desc = request.form.get('desc')
        item_start = request.form.get('start_time')
        item_end = request.form.get('end_time')

        logical_date = get_logical_date(datetime.now())

        try:
            item = Expenses(
                desc=item_desc,
                start_time=item_start,
                end_time=item_end,
                user_id=current_user.id,
                is_archived=False,
                archive_date=logical_date
            )
            db.session.add(item)
            update_user_streak(current_user, logical_date)
            db.session.commit()

            payload = serialize_expense(item)
            publish_user_event(current_user.id, EVENT_EXPENSE_CREATED, payload)

            if is_ajax_request(request):
                return jsonify({'status': 'success', 'expense': payload})
            return redirect('/')
        except Exception as e:
            if is_ajax_request(request):
                return jsonify({'status': 'error', 'message': str(e)}), 500
            return f'Error: {str(e)}'

    else:
        now = datetime.now()
        current_logical_date = get_logical_date(now)

        active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()

        items_to_archive = False
        for item in active_items:
            item_logical_date = get_logical_date(item.timestamp)

            if item_logical_date < current_logical_date:
                item.is_archived = True
                item.archive_date = item_logical_date
                items_to_archive = True

        if items_to_archive:
            db.session.commit()

        old_streak = current_user.streak
        update_user_streak(current_user, current_logical_date)
        streak_incremented = current_user.streak > old_streak
        if current_user.streak != old_streak:
            db.session.commit()

        expenses = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Expenses.timestamp.desc()).all()

        total_h, deep_h = calculate_stats_from_logs(expenses)

        rlhf_count = AlignmentSignal.query.filter_by(user_id=current_user.id).count()

        model_confidence = min(99, 75 + int(rlhf_count / 5))

        todos = load_todos(current_user)
        if not todos and (current_user.quick_note or '').strip():
            todos = migrate_quick_note_to_todos(current_user.quick_note)
            current_user.todos = json.dumps(todos)
            current_user.quick_note = ""
            db.session.commit()

        profile = load_user_profile(current_user)
        onboarding_needed = (
            profile.primary_goal == ''
            and json.loads(profile.interests or '[]') == []
        )

        return render_template(
            'index.html',
            expenses=expenses,
            total_hours=total_h,
            deep_hours=deep_h,
            rlhf_count=rlhf_count,
            model_confidence=model_confidence,
            todos=todos,
            todos_json=json.dumps(todos),
            streak_incremented=streak_incremented,
            streak=current_user.streak,
            onboarding_needed=onboarding_needed,
        )


@bp.route('/end_day', methods=['POST'])
@login_required
def end_day():
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()

    current_logical_date = get_logical_date(datetime.now())

    for item in active_items:
        item.is_archived = True
        item.archive_date = current_logical_date

    current_user.quick_note = ""
    current_user.todos = "[]"

    db.session.commit()
    return redirect('/')


@bp.route('/api/expenses/<int:id>', methods=['POST'])
@login_required
def delete(id):
    del_item = Expenses.query.get_or_404(id)
    if (del_item.user_id != current_user.id):
        return "Unauthorized"
    try:
        deleted_id = del_item.id
        db.session.delete(del_item)
        db.session.commit()
        publish_user_event(current_user.id, EVENT_EXPENSE_DELETED, {'id': deleted_id})
        if is_ajax_request(request):
            return jsonify({'status': 'success', 'id': deleted_id})
        return redirect('/')
    except Exception as e:
        if is_ajax_request(request):
            return jsonify({'status': 'error', 'message': str(e)}), 500
        return f"Error deleting item: {e}"


@bp.route('/history')
@login_required
def history():
    mode = request.args.get('mode', 'day')
    offset = request.args.get('offset', 0, type=int)

    today = date.today()

    if mode == 'week':
        current_monday = today - timedelta(days=today.weekday())
        start_date = current_monday + timedelta(weeks=offset)
        end_date = start_date + timedelta(days=6)
        label = f"{start_date.strftime('%Y-%m-%d')} — {end_date.strftime('%Y-%m-%d')}"
    else:
        start_date = today + timedelta(days=offset)
        end_date = start_date
        label = start_date.strftime('%Y-%m-%d (%A)')

    items = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        Expenses.is_archived == True,
        Expenses.archive_date.isnot(None),
        Expenses.archive_date >= start_date,
        Expenses.archive_date <= end_date,
    ).order_by(
        Expenses.archive_date.desc(),
        Expenses.timestamp.desc()
    ).all()

    grouped_history = OrderedDict()

    for archive_date, group in groupby(items, key=lambda x: x.archive_date):
        day_items = list(group)
        grouped_history[archive_date] = {
            'items': day_items,
            'stats': build_day_stats(day_items),
        }

    total_entries = len(items)
    range_total_min = sum(d['stats']['total_minutes'] for d in grouped_history.values())
    range_total_hours = f"{range_total_min / 60:.1f}h"
    range_days = len(grouped_history)

    if mode == 'week':
        next_disabled = (start_date + timedelta(weeks=1)) > today
    else:
        next_disabled = (start_date + timedelta(days=1)) > today

    prev_end = start_date - timedelta(days=1)
    has_older = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        Expenses.is_archived == True,
        Expenses.archive_date.isnot(None),
        Expenses.archive_date <= prev_end,
    ).first() is not None

    return render_template(
        'history.html',
        grouped_history=grouped_history,
        mode=mode,
        offset=offset,
        label=label,
        total_entries=total_entries,
        range_total_hours=range_total_hours,
        range_days=range_days,
        start_date=start_date,
        end_date=end_date,
        next_disabled=next_disabled,
        has_older=has_older,
    )
