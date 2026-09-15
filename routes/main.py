import json
from datetime import datetime, timedelta, date
from collections import OrderedDict
from itertools import groupby

from flask import Blueprint, render_template, request, redirect, jsonify, Response
from flask_login import login_required, current_user
from model import db, User, TimeEntry

from routes.common import (
    serialize_entry, is_ajax_request, publish_user_event,
    EVENT_ENTRY_CREATED, EVENT_ENTRY_DELETED,
    load_todos, migrate_quick_note_to_todos, get_logical_date,
    load_user_profile, load_notebooks, load_todo_lists, now_local,
)
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

        now = now_local()
        logical_date = get_logical_date(now)

        try:
            item = TimeEntry(
                desc=item_desc,
                start_time=item_start,
                end_time=item_end,
                user_id=current_user.id,
                is_archived=False,
                archive_date=logical_date,
                # 显式写用户本地时间，否则 model 默认值取的是容器的 UTC，
                # 下面 index GET 里拿 timestamp 算逻辑日期时会串时区。
                timestamp=now,
            )
            db.session.add(item)
            update_user_streak(current_user, logical_date)
            db.session.commit()

            payload = serialize_entry(item)
            publish_user_event(current_user.id, EVENT_ENTRY_CREATED, payload)

            if is_ajax_request(request):
                return jsonify({'status': 'success', 'entry': payload})
            return redirect('/')
        except Exception as e:
            if is_ajax_request(request):
                return jsonify({'status': 'error', 'message': str(e)}), 500
            return f'Error: {str(e)}'

    else:
        now = now_local()
        current_logical_date = get_logical_date(now)

        active_items = TimeEntry.query.filter_by(user_id=current_user.id, is_archived=False).all()

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

        entries = TimeEntry.query.filter_by(user_id=current_user.id, is_archived=False).order_by(TimeEntry.timestamp.desc()).all()

        # 更早的 quick_note 自由文本先迁成旧的单栏 todos（只在多 list 列还没建立时），
        # 紧接着再由 load_todo_lists() 把单栏 todos 迁成第一个 list。
        if not current_user.todo_lists:
            todos = load_todos(current_user)
            if not todos and (current_user.quick_note or '').strip():
                todos = migrate_quick_note_to_todos(current_user.quick_note)
                current_user.todos = json.dumps(todos)
                current_user.quick_note = ""
                db.session.commit()

        # 多 to-do list：和 notebooks 同一套迁移逻辑，首次访问落库后
        # todo_lists 列就一直非空（至少一个），不会再走迁移分支。
        todo_lists = load_todo_lists(current_user)
        if not current_user.todo_lists:
            current_user.todo_lists = json.dumps(todo_lists)
            db.session.commit()

        # 多 notebook：首次访问时把旧的单栏 user.notebook 迁进来并落库，
        # 之后 notebooks 列就一直非空（至少一本），不会再走迁移分支。
        notebooks = load_notebooks(current_user)
        if not current_user.notebooks:
            current_user.notebooks = json.dumps(notebooks)
            db.session.commit()

        profile = load_user_profile(current_user)
        onboarding_needed = (
            profile.primary_goal == ''
            and json.loads(profile.interests or '[]') == []
        )

        return render_template(
            'index.html',
            entries=entries,
            # 顶栏显示的是自然日（零点翻页），和 Archive Day 用的逻辑日期
            # （06:00 分界）是两套独立逻辑。这里只负责首屏，之后由
            # dashboard.js 的 updateHeaderDate() 在零点自动更新。
            display_date=now.date(),
            todo_lists_json=json.dumps(todo_lists),
            notebooks_json=json.dumps(notebooks),
            streak_incremented=streak_incremented,
            streak=current_user.streak,
            onboarding_needed=onboarding_needed,
        )


@bp.route('/end_day', methods=['POST'])
@login_required
def end_day():
    active_items = TimeEntry.query.filter_by(user_id=current_user.id, is_archived=False).all()

    current_logical_date = get_logical_date(now_local())

    for item in active_items:
        item.is_archived = True
        item.archive_date = current_logical_date

    # 只存档 History Flow；To-Do list 和 Notebook 都不动。
    db.session.commit()
    return redirect('/')


@bp.route('/api/entries/<int:id>', methods=['POST'])
@login_required
def delete(id):
    del_item = TimeEntry.query.get_or_404(id)
    if (del_item.user_id != current_user.id):
        return "Unauthorized", 403
    try:
        deleted_id = del_item.id
        db.session.delete(del_item)
        db.session.commit()
        publish_user_event(current_user.id, EVENT_ENTRY_DELETED, {'id': deleted_id})
        if is_ajax_request(request):
            return jsonify({'status': 'success', 'id': deleted_id})
        return redirect('/')
    except Exception as e:
        if is_ajax_request(request):
            return jsonify({'status': 'error', 'message': str(e)}), 500
        return f"Error deleting item: {e}"


@bp.route('/api/export/today')
@login_required
def export_today():
    logical_date = get_logical_date(now_local())
    date_label = logical_date.strftime('%Y-%m-%d')

    entries = TimeEntry.query.filter_by(
        user_id=current_user.id, is_archived=False
    ).order_by(TimeEntry.timestamp.asc()).all()

    todo_lists = load_todo_lists(current_user)

    total_min = 0
    for e in entries:
        try:
            st = datetime.strptime(e.start_time, '%H:%M')
            en = datetime.strptime(e.end_time, '%H:%M')
            total_min += max((en - st).total_seconds() / 60, 0)
        except (ValueError, TypeError):
            continue

    sep = '=' * 44
    dash = '-' * 44
    lines = [sep, f"  ONYX DAILY LOG - {date_label}", sep, ""]

    lines.append("HISTORY FLOW")
    lines.append(dash)
    if entries:
        for i, e in enumerate(entries, 1):
            lines.append(f"  {i:>2}. {e.start_time} - {e.end_time}  |  {e.desc}")
        lines.append("")
        lines.append(f"  Total tracked: {total_min / 60:.1f}h")
    else:
        lines.append("  -- No Records Yet --")

    lines.append("")
    lines.append("TO-DO LIST")
    lines.append(dash)
    # 多个 list 时每个 list 单独列一段（带名字和各自的完成数）；只有一个时不加小标题。
    for lst in todo_lists:
        todos = lst['todos']
        if len(todo_lists) > 1:
            lines.append(f"  [{lst['name']}]")
        if todos:
            for i, t in enumerate(todos, 1):
                mark = '[x]' if t['done'] else '[ ]'
                lines.append(f"  {i:>2}. {mark}  {t['text']}")
            done = sum(1 for t in todos if t['done'])
            lines.append("")
            lines.append(f"  Completed: {done}/{len(todos)}")
        else:
            lines.append("  -- No Tasks Yet --")
        if len(todo_lists) > 1:
            lines.append("")

    body = "\r\n".join(lines) + "\r\n"
    return Response(
        body,
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{date_label}.txt"'},
    )


@bp.route('/history')
@login_required
def history():
    mode = request.args.get('mode', 'day')
    offset = request.args.get('offset', 0, type=int)

    # history 页按逻辑日期翻页：凌晨 5 点看的仍然是"昨天"
    today = get_logical_date(now_local())

    if mode == 'week':
        current_monday = today - timedelta(days=today.weekday())
        start_date = current_monday + timedelta(weeks=offset)
        end_date = start_date + timedelta(days=6)
        label = f"{start_date.strftime('%Y-%m-%d')} — {end_date.strftime('%Y-%m-%d')}"
    else:
        start_date = today + timedelta(days=offset)
        end_date = start_date
        label = start_date.strftime('%Y-%m-%d (%A)')

    items = TimeEntry.query.filter(
        TimeEntry.user_id == current_user.id,
        TimeEntry.is_archived == True,
        TimeEntry.archive_date.isnot(None),
        TimeEntry.archive_date >= start_date,
        TimeEntry.archive_date <= end_date,
    ).order_by(
        TimeEntry.archive_date.desc(),
        TimeEntry.timestamp.desc()
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
    has_older = TimeEntry.query.filter(
        TimeEntry.user_id == current_user.id,
        TimeEntry.is_archived == True,
        TimeEntry.archive_date.isnot(None),
        TimeEntry.archive_date <= prev_end,
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
