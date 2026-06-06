import json
import re as _re
from datetime import datetime, timedelta
from flask import current_app
from model import db, UserProfile

# --- Event constants ---
EVENT_EXPENSE_CREATED = 'expense_created'
EVENT_EXPENSE_DELETED = 'expense_deleted'
EVENT_NOTEBOOK_UPDATED = 'notebook_updated'
EVENT_TODOS_UPDATED = 'todos_updated'
EVENT_HEARTBEAT = 'heartbeat'

EVENT_PAYLOAD_SCHEMA = {
    EVENT_EXPENSE_CREATED: ('id', 'desc', 'start_time', 'end_time', 'timestamp'),
    EVENT_EXPENSE_DELETED: ('id',),
    EVENT_NOTEBOOK_UPDATED: ('type', 'content', 'saved_at'),
    EVENT_TODOS_UPDATED: ('todos', 'saved_at'),
}

SSE_EVENT_NAMES = set(EVENT_PAYLOAD_SCHEMA.keys())


def serialize_expense(expense):
    return {
        'id': expense.id,
        'desc': expense.desc,
        'start_time': expense.start_time,
        'end_time': expense.end_time,
        'timestamp': expense.timestamp.isoformat() if expense.timestamp else None,
    }


def is_ajax_request(req):
    return (
        req.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in req.headers.get('Accept', '')
    )


def user_event_channel(user_id):
    return f"{current_app.config.get('REDIS_CHANNEL_PREFIX', 'onyx:user')}:{user_id}"


def publish_user_event(user_id, event_name, payload):
    if event_name not in SSE_EVENT_NAMES:
        current_app.logger.warning('SSE publish skipped: unknown event=%s', event_name)
        return False

    redis_client = getattr(current_app, 'redis_client', None)
    if redis_client is None:
        current_app.logger.warning('SSE publish skipped: Redis unavailable event=%s user_id=%s', event_name, user_id)
        return False

    message = {
        'event': event_name,
        'data': payload,
        'sent_at': datetime.utcnow().isoformat() + 'Z',
    }

    try:
        channel = user_event_channel(user_id)
        redis_client.publish(channel, json.dumps(message))
        return True
    except Exception as e:
        current_app.logger.exception('SSE publish failed event=%s user_id=%s error=%s', event_name, user_id, str(e))
        return False


def format_sse(event_name, data):
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


# --- To-Do helpers ---

def load_todos(user):
    raw = user.todos or "[]"
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        items = []

    clean = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            text_val = str(it.get('text', '')).strip()
            if not text_val:
                continue
            clean.append({
                'id': str(it.get('id') or len(clean) + 1),
                'text': text_val[:500],
                'done': bool(it.get('done', False)),
            })
    return clean


def sanitize_todos(items):
    clean = []
    if not isinstance(items, list):
        return clean
    for it in items[:200]:
        if not isinstance(it, dict):
            continue
        text_val = str(it.get('text', '')).strip()
        if not text_val:
            continue
        clean.append({
            'id': str(it.get('id') or len(clean) + 1),
            'text': text_val[:500],
            'done': bool(it.get('done', False)),
        })
    return clean


def migrate_quick_note_to_todos(quick_note):
    if not quick_note:
        return []

    marker = _re.compile(r'^\s*(?:\d+[.、)]|[-*•])\s+')
    items = []
    for line in quick_note.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if marker.match(line) or not items:
            text_val = marker.sub('', stripped).strip()
            if text_val:
                items.append(text_val)
        else:
            items[-1] = (items[-1] + ' ' + stripped).strip()

    return [
        {'id': str(i + 1), 'text': t[:500], 'done': False}
        for i, t in enumerate(items) if t
    ]


def todos_to_text(todos):
    if not todos:
        return ""
    lines = []
    for t in todos:
        mark = '[x]' if t.get('done') else '[ ]'
        lines.append(f"{mark} {t.get('text', '')}")
    return "\n".join(lines)


# --- Logical date helper ---

def get_logical_date(dt_obj):
    if dt_obj.hour < 6:
        return (dt_obj - timedelta(days=1)).date()
    return dt_obj.date()


# --- User Profile helpers ---

def load_user_profile(user):
    if user.profile:
        return user.profile
    p = UserProfile(user_id=user.id)
    db.session.add(p)
    db.session.commit()
    return p


def _update_profile_from_form(profile, form_data):
    for field in [
        'typical_wakeup', 'typical_bedtime',
        'breakfast_window_start', 'breakfast_window_end',
        'lunch_window_start', 'lunch_window_end',
        'dinner_window_start', 'dinner_window_end',
        'chronotype', 'peak_start', 'peak_end',
        'daily_burden', 'primary_goal', 'exercise_goal',
        'health_note',
    ]:
        if field in form_data and form_data[field] is not None:
            setattr(profile, field, form_data[field])

    for json_field in [
        'work_style', 'secondary_goals', 'interests',
        'ai_role', 'tracked_habits',
    ]:
        if json_field in form_data:
            val = form_data[json_field]
            if isinstance(val, list):
                setattr(profile, json_field, json.dumps(val))
            elif isinstance(val, str):
                try:
                    json.loads(val)
                    setattr(profile, json_field, val)
                except json.JSONDecodeError:
                    setattr(profile, json_field, json.dumps([val]))


# --- Rate-limit helper ---

def _check_rate_limit(user_id):
    redis_client = getattr(current_app, 'redis_client', None)
    if redis_client is None:
        return False, ""

    rate_limit_per_minute = current_app.config.get('RATE_LIMIT_PER_MINUTE', 3)
    rate_limit_per_hour = current_app.config.get('RATE_LIMIT_PER_HOUR', 20)

    try:
        minute_key = f"rate:audit:{user_id}:minute"
        hour_key = f"rate:audit:{user_id}:hour"

        with redis_client.pipeline() as pipe:
            pipe.incr(minute_key)
            pipe.incr(hour_key)
            pipe.expire(minute_key, 60, nx=True)
            pipe.expire(hour_key, 3600, nx=True)
            minute_count, hour_count, _, _ = pipe.execute()

        if minute_count > rate_limit_per_minute:
            return True, f"Rate limit: {rate_limit_per_minute}/minute. Slow down."
        if hour_count > rate_limit_per_hour:
            return True, f"Rate limit: {rate_limit_per_hour}/hour. Try again later."
        return False, ""
    except Exception:
        return False, ""
