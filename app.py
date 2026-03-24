from gevent import monkey
monkey.patch_all() 
import os
import json
import time
import requests
from groq import Groq

import redis
from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response, stream_with_context
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date, timezone
from itertools import groupby
from collections import OrderedDict
from sqlalchemy import and_, or_
from model import db, User, Expenses, AlignmentSignal

from services.prompts import get_audit_prompt, get_weekly_audit_prompt
from services.stats import calculate_stats_from_logs, calculate_duration
from services.streak import update_user_streak
from services.history_helper import calculate_duration_minutes, build_day_stats

from dotenv import load_dotenv
load_dotenv()  # Auto-load variables from the .env file.

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
XAI_API_KEY = os.environ.get('XAI_API_KEY')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
REDIS_CHANNEL_PREFIX = os.environ.get('REDIS_CHANNEL_PREFIX', 'onyx:user')
SSE_HEARTBEAT_SECONDS = int(os.environ.get('SSE_HEARTBEAT_SECONDS', '25'))

EVENT_EXPENSE_CREATED = 'expense_created'
EVENT_EXPENSE_DELETED = 'expense_deleted'
EVENT_NOTEBOOK_UPDATED = 'notebook_updated'
EVENT_HEARTBEAT = 'heartbeat'

EVENT_PAYLOAD_SCHEMA = {
    EVENT_EXPENSE_CREATED: ('id', 'desc', 'start_time', 'end_time', 'timestamp'),
    EVENT_EXPENSE_DELETED: ('id',),
    EVENT_NOTEBOOK_UPDATED: ('type', 'content', 'saved_at'),
}

SSE_EVENT_NAMES = set(EVENT_PAYLOAD_SCHEMA.keys())

redis_client = None
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
except Exception as redis_error:
    print(f"Redis init failed at {REDIS_URL}: {redis_error}")
    redis_client = None

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///site.db'

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def user_event_channel(user_id):
    return f"{REDIS_CHANNEL_PREFIX}:{user_id}"


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


def publish_user_event(user_id, event_name, payload):
    if event_name not in SSE_EVENT_NAMES:
        app.logger.warning('SSE publish skipped: unknown event=%s', event_name)
        return False

    if redis_client is None:
        app.logger.warning('SSE publish skipped: Redis unavailable event=%s user_id=%s', event_name, user_id)
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
        app.logger.exception('SSE publish failed event=%s user_id=%s error=%s', event_name, user_id, str(e))
        return False


def format_sse(event_name, data):
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"

# --- Helper: calculate logical date ---
def get_logical_date(dt_obj):
    """
    If the time is between 00:00 and 06:00, treat it as the previous day.
    Example: Jan 30 03:00 -> logically Jan 29
    """
    if dt_obj.hour < 6:
        return (dt_obj - timedelta(days=1)).date()
    return dt_obj.date()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Auto-create tables when the app starts.
with app.app_context():
    db.create_all()

# --- Route logic ---

@app.route('/', methods=["POST", "GET"])
@login_required
def index(): # get user lgo entry; 
# it is one of the only three routings when the project was initially built :D
    # 1. POST: add new record
    if request.method == 'POST':
        item_desc = request.form.get('desc')
        item_start = request.form.get('start_time')
        item_end = request.form.get('end_time')
        
        # New records belong to the current logical day by default.
        logical_date = get_logical_date(datetime.now())
        
        try:
            item = Expenses(
                desc=item_desc, 
                start_time=item_start, 
                end_time=item_end, 
                user_id=current_user.id,
                is_archived=False,           # Show on homepage by default.
                archive_date=logical_date    # Mark which logical day it belongs to.
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

    # 2. GET: render homepage
    else:
        # [Core logic] Auto-check whether a new logical day has started.
        # If current logical date > an item's logical date, it should be archived.
        now = datetime.now()
        current_logical_date = get_logical_date(now)
        
        # Fetch all records still active on the homepage.
        active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
        
        items_to_archive = False
        for item in active_items:
            # Determine which logical day this record belongs to.
            item_logical_date = get_logical_date(item.timestamp)
            
            # Archive records from previous logical days once the day has rolled over.
            if item_logical_date < current_logical_date:
                item.is_archived = True
                item.archive_date = item_logical_date # Ensure archive date stays correct.
                items_to_archive = True
        
        if items_to_archive:
            db.session.commit()
        
        # Re-fetch remaining records for today.
        expenses = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Expenses.timestamp.desc()).all()

        total_h, deep_h = calculate_stats_from_logs(expenses)

        # [NEW] Get current user's RLHF sample count.
        rlhf_count = AlignmentSignal.query.filter_by(user_id=current_user.id).count()
        
        # [NEW] Add a simple fake model confidence metric.
        # Logic: more samples -> higher confidence. Start at 75% and add over time.
        model_confidence = min(99, 75 + int(rlhf_count / 5))
            
        return render_template('index.html', expenses=expenses, total_hours=total_h, deep_hours=deep_h, rlhf_count=rlhf_count, model_confidence=model_confidence)

@app.route('/end_day', methods=['POST'])
@login_required
def end_day():
    """Manually end today: force-archive all homepage records."""
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    
    current_logical_date = get_logical_date(datetime.now())
    
    for item in active_items:
        item.is_archived = True
        # For manual end-day, use current logical date as archive date.
        item.archive_date = current_logical_date

    # empty quick_note
    current_user.quick_note = ""
    # and do NOT change notebook
        
    db.session.commit()
    return redirect('/')


@app.route('/history')
@login_required
def history():
    """History page: day/week pagination with timeline navigation and daily stats."""

    # ── 1. Parse params ──────────────────────────────────
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

    # ── 2. Database query ───────────────────────────────
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

    # ── 3. Group by date + calculate daily stats ────────────────
    grouped_history = OrderedDict()  # { date: { 'items': [...], 'stats': {...} } }

    for archive_date, group in groupby(items, key=lambda x: x.archive_date):
        day_items = list(group)
        grouped_history[archive_date] = {
            'items': day_items,
            'stats': build_day_stats(day_items),
        }

    # ── 4. Range-level summary stats (top section) ───────────────
    total_entries = len(items)
    range_total_min = sum(d['stats']['total_minutes'] for d in grouped_history.values())
    range_total_hours = f"{range_total_min / 60:.1f}h"
    range_days = len(grouped_history)

    # ── 5. Navigation boundaries ─────────────────────────────────
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


@app.route('/api/key/juncheng220680', methods=['GET'])
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

# delete log
@app.route('/delete/<int:id>', methods=['POST'])
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

@app.route('/register', methods=['POST', 'GET'])
def register():
    # ... (keep existing logic) ...
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_2 = request.form.get('password-confirm')
        user = User.query.filter_by(username=username).first()
        if user:
            return render_template('register.html', user_exists=True)
        if password != password_2:
            return render_template('register.html', password_mismatch=True)
        # Hash password
        new_user = User(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        return redirect('/login')
    else:
        return render_template('register.html')

@app.route('/login', methods=['POST', 'GET'])
def login():
    # ... (keep existing logic) ...
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        # username exists and password matches:
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/')

        # username exists but password is incorrect:
        if user:
            return render_template('login.html', wrong_password=True, user_dne=False)

        # username does not exist
        return render_template('login.html', user_dne=True, wrong_password=False)
    else:
        return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


# save notebook
@app.route('/save_notes', methods=['POST'])
@login_required
def save_notes():
    data = request.json
    note_type = data.get('type')
    content = data.get('content')

    if (note_type == 'quick_note'):
        current_user.quick_note = content
    else:
        current_user.notebook = content

    db.session.commit()
    saved_at = datetime.now().strftime("%H:%M:%S")
    publish_user_event(current_user.id, EVENT_NOTEBOOK_UPDATED, {
        'type': note_type,
        'content': content,
        'saved_at': saved_at,
    })
    return jsonify({"status": "success", "saved_at": saved_at})


@app.route('/api/events', methods=['GET'])
@login_required
def stream_events():
    user_id = current_user.id
    channel = user_event_channel(user_id)

    @stream_with_context
    def event_stream():
        pubsub = None
        last_heartbeat = time.monotonic()
        app.logger.info('SSE connect user_id=%s channel=%s', user_id, channel)
        try:
            if redis_client is None:
                app.logger.warning('SSE stream unavailable: Redis unavailable user_id=%s', user_id)
                yield format_sse(EVENT_HEARTBEAT, {'status': 'redis_unavailable'})
                return

            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)

            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    try:
                        payload = json.loads(message.get('data') or '{}')
                    except Exception:
                        payload = {}

                    event_name = payload.get('event')
                    event_data = payload.get('data', {})
                    if event_name in SSE_EVENT_NAMES:
                        yield format_sse(event_name, event_data)
                        last_heartbeat = time.monotonic()

                if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                    yield format_sse(EVENT_HEARTBEAT, {'ts': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')})
                    last_heartbeat = time.monotonic()
                gevent.sleep(0.01)
        except GeneratorExit:
            app.logger.info('SSE disconnect user_id=%s channel=%s reason=client_closed', user_id, channel)
        except Exception as e:
            app.logger.exception('SSE stream error user_id=%s error=%s', user_id, str(e))
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(channel)
                    pubsub.close()
                except Exception:
                    pass
            app.logger.info('SSE cleanup user_id=%s channel=%s', user_id, channel)

    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route('/api/ai/audit', methods=['POST'])
@login_required
def ai_audit():
    # --- 1. Rate-limit logic (unchanged) ---
    last_run = session.get('last_audit_time')
    now = datetime.now()
    
    if last_run:
        last_time = datetime.fromisoformat(last_run)
        if now - last_time < timedelta(seconds=10):
            return jsonify({
                "score": 0,
                "status": "red",
                "insight": "Cool down! System recharging.",
                "warning": "Rate limit exceeded. Wait 10s."
            }), 429

    session['last_audit_time'] = now.isoformat()

    # --- 2. Collect data (unchanged) ---
    data = request.get_json() or {} 
    user_tone = data.get('tone', 'strict')
    
    logical_date = get_logical_date(datetime.now())
    today_logs = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        or_(
            Expenses.archive_date == logical_date,
            Expenses.is_archived == False
        )
    ).all()
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    
    logs_data = [f"{log.start_time}-{log.end_time}: {log.desc}" for log in today_logs]
    
    notebook = current_user.notebook
    quick_note = current_user.quick_note

    # Build prompt text
    prompt_text = get_audit_prompt(notebook, quick_note, logs_data, tone=user_tone)

    # --- 3. Call Grok API (core change point) ---
    # Key should come from env vars (already configured above).

    
    # Build x.ai OpenAI-compatible request payload.
    payload = {
        # Fast and cost-effective model choice.
        "model": "grok-4-1-fast-non-reasoning", 
        
        "messages": [
            {
                "role": "system", 
                "content": "You are a concise log classifier. Always output valid JSON."
            },
            {
                "role": "user", 
                "content": prompt_text
            }
        ],
        "temperature": 0.1, # Keep low for stable classification.
        "stream": False
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {XAI_API_KEY}"
    }

    try:
        # Send POST request via requests.
        response = requests.post(
            "https://api.x.ai/v1/chat/completions", 
            headers=headers, 
            json=payload,
            timeout=30 # Timeout safeguard.
        )
        response.raise_for_status() # Raise exception on 4xx/5xx.
        
        full_res = response.json()
        raw_content = full_res['choices'][0]['message']['content']

        # Clean and parse JSON.
        clean_json = raw_content.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(clean_json))

    except Exception as e:
        print(f"Grok Error: {str(e)}")
        return jsonify({
            "score": 0, 
            "status": "red", 
            "insight": "Grok Connection Failed", 
            "warning": f"Technical details: {str(e)}"
        })


@app.route('/api/visualize', methods=['POST'])
@login_required
def visualize_data():
    # A. Fetch today's active data (Raw Data)
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    
    if not active_items:
        return jsonify({"error": "No data to analyze"}), 400

    # B. [Context Retrieval] Fetch user's historical tags (Memory)
    # This helps maintain consistent categorization.
    existing_tags = []
    try:
        # Query 20 recent distinct tags.
        recent_tags_query = db.session.query(Expenses.category).filter(
            Expenses.user_id == current_user.id,
            Expenses.category != "Uncategorized",
            Expenses.category != None
        ).distinct().limit(20).all()
        existing_tags = [row[0] for row in recent_tags_query if row[0]]
    except Exception:
        pass # DB may be empty after reset; ignore safely.

    tags_context = ", ".join(existing_tags) if existing_tags else "None yet"

    # C. Build input packet
    entries_text = "\n".join([f"ID_{item.id}: [{item.start_time}-{item.end_time}] {item.desc}" for item in active_items])

    # D. Build prompt (High-Concept: Context-Aware Taxonomy)
    prompt = f"""
    You are a data taxonomy engine. Group the following logs into 3-6 high-level categories.
    
    [Context Memory]
    Existing Tags: {tags_context}
    (Prioritize using these tags if they fit. Create new ones only if necessary.)
    
    [Rules]
    1. Categories must be concise (1-2 words, e.g., "Coding", "Deep Work").
    2. Every entry must have exactly ONE category.
    3. Return ONLY valid JSON mapping Entry IDs to Categories.
    
    [Input Data]
    {entries_text}
    
    [Output Format]
    {{ "ID_1": "Coding", "ID_2": "Break" }}
    """

    # E. Call xAI (Grok)
    try:
        payload = {
            "model": "grok-4-1-fast-non-reasoning", # or gpt-4o-mini
            "messages": [
                {"role": "system", "content": "Output strictly JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1, # Low temperature for stable output.
            "stream": False
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {XAI_API_KEY}"
        }
        
        # Send request
        response = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        # Parse response
        ai_content = response.json()['choices'][0]['message']['content']
        clean_json = ai_content.replace("```json", "").replace("```", "").strip()
        mapping = json.loads(clean_json)

    except Exception as e:
        print(f"AI/Network Error: {e}")
        # If AI call fails, return an error safely.
        return jsonify({"error": "Taxonomy Engine Failed"}), 500

    # F. [Data Enrichment] Update DB and calculate stats
    stats = {} 
    
    for item in active_items:
        key = f"ID_{item.id}"
        # Get category (fallback to 'Uncategorized' if missing).
        category = mapping.get(key, "Uncategorized")
        
        # Persist category label.
        item.category = category
        
        # Accumulate duration.
        duration = calculate_duration(item.start_time, item.end_time)
        stats[category] = stats.get(category, 0) + duration

    db.session.commit()

    # G. Return chart data to frontend
    return jsonify({
        "labels": list(stats.keys()),
        "data": list(stats.values()),
        "total_minutes": sum(stats.values())
    })

@app.route('/api/submit_alignment', methods=['POST'])
@login_required
def submit_alignment():
    """Receive RLHF feedback from frontend and store it in DB."""
    try:
        data = request.json
        
        # Match AlignmentSignal field names explicitly.
        new_signal = AlignmentSignal(
            user_id=current_user.id,
            input_context=data.get('context', 'Unknown Context'), 
            ai_response=data.get('response', 'User Feedback'), # Correct field name.
            reward_score=data.get('score', 0)                  # Correct field name.
        )
        
        db.session.add(new_signal)
        db.session.commit()
        
        return jsonify({"status": "success", "message": "Signal Captured"})
        
    except Exception as e:
        print(f"Alignment Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/generate_weekly_insight', methods=['POST'])
@login_required
def generate_weekly_insight():
    # 1. Define time range (past 7 days)
    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    
    # 2. Query logs from database
    logs = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        Expenses.is_archived == True, 
        Expenses.archive_date >= start_date,
        Expenses.archive_date <= end_date
    ).all()

    # Defensive check
    if len(logs) < 1:
        return jsonify({
            "status": "error", 
            "message": "Insufficient data fragments. Please log more activity."
        }), 400
    # =======================================================
    # [NEW] 3. Fetch historical RLHF feedback (The Memory Module)
    # =======================================================
    # Query recent 3 negatively rated feedback items (reward_score=1).
    negative_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=1  # Correct field name.
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()
    
    # Query recent 3 positively rated feedback items (reward_score=5).
    positive_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=5  # Correct field name.
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()
    
    # Build context-memory string.
    rlhf_context = ""
    
    if negative_feedbacks:
        rlhf_context += "\n[⚠️ HISTORY WARNING - USER DISLIKED THESE PREVIOUS ANALYSES]:\n"
        for fb in negative_feedbacks:
            # Keep a short snippet as context reference.
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User rejected: {clean_context}...\n"
            
    if positive_feedbacks:
        rlhf_context += "\n[✅ HISTORY SUCCESS - USER LIKED THESE PATTERNS]:\n"
        for fb in positive_feedbacks:
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User approved: {clean_context}...\n"

    # =======================================================

    # 4. Data preprocessing (Log Summary)
    log_summary = "\n".join([
        f"[{l.archive_date} {l.start_time}-{l.end_time}] {l.category}: {l.desc}" 
        for l in logs
    ])
    
    # 5. Build prompt (inject RLHF memory)
    # Ensure prompts.py function accepts two parameters.
    system_prompt = get_weekly_audit_prompt(log_summary, rlhf_context)

    try:
        # --- Real AI call area ---
        # Uncomment below based on your actual provider (OpenAI / DeepSeek).
        
        # response = client.chat.completions.create(
        #     model="deepseek-chat", # or gpt-4o
        #     messages=[{"role": "system", "content": system_prompt}],
        #     temperature=0.7,
        #     response_format={"type": "json_object"} 
        # )
        # ai_content = response.choices[0].message.content
        # ai_data = json.loads(ai_content)
        
        # --- [FALLBACK] Mock Data (avoid failures before API key setup) ---
        # --- Once API is connected, remove or comment this block out. ---
        import time
        gevent.sleep(1.5)
        ai_data = {
            "week_label": "The Recursive Feedback Loop",
            "neural_phase": "HYPER-DRIVE",
            "peak_window": "21:00 - 23:00",
            "deep_work_ratio": 78,
            "primary_mood_color": "#3498db", 
            "achievement": "Integrated Reinforcement Learning Human Feedback (RLHF).",
            "roast": "You are actually coding the logic to audit your own coding logic. This is meta-programming at its finest.",
            "optimization_protocol": "Keep the feedback loop tight."
        }
        # -----------------------------------------------------------

        return jsonify(ai_data)

    except Exception as e:
        print(f"Neural Link Error: {e}")
        return jsonify({"status": "error", "message": f"Neural Link Severed: {str(e)}"}), 500
    
if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    http_server = WSGIServer(('127.0.0.1', 5000), app)
    print("Gevent Server started on http://127.0.0.1:5000")
    http_server.serve_forever()


#  git checkout -b ai-integration