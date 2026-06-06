import json
import time as time_module
from datetime import datetime, timedelta, date

import gevent
import requests
from flask import Blueprint, request, jsonify, session
from flask import current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from model import db, Expenses, AlignmentSignal

from routes.common import (
    get_logical_date, load_todos, todos_to_text,
    load_user_profile, _check_rate_limit,
)
from services.prompts import get_audit_prompt, get_weekly_audit_prompt
from services.stats import calculate_duration

bp = Blueprint('ai', __name__)


@bp.route('/api/ai/audit', methods=['POST'])
@login_required
def ai_audit():
    if current_user.username != 'juncheng':
        limited, limit_msg = _check_rate_limit(current_user.id)
        if limited:
            return jsonify({
                "score": 0,
                "status": "red",
                "insight": "You are scanning too quickly.",
                "warning": limit_msg,
            }), 429

        last_run = session.get('last_audit_time')
        now = datetime.now()

        if last_run:
            last_time = datetime.fromisoformat(last_run)
            if now - last_time < timedelta(seconds=15):
                return jsonify({
                    "score": 0,
                    "status": "red",
                    "insight": "Cool down! System recharging.",
                    "warning": "Rate limit exceeded. Wait 15s."
                }), 429
    else:
        last_run = session.get('last_audit_time')
        now = datetime.now()

    session['last_audit_time'] = now.isoformat()

    data = request.get_json() or {}
    user_tone = data.get('tone', 'strict')
    client_time = data.get('client_time')

    logical_date = get_logical_date(datetime.now())
    today_logs = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        or_(
            Expenses.archive_date == logical_date,
            Expenses.is_archived == False
        )
    ).all()

    logs_data = [f"{log.start_time}-{log.end_time}: {log.desc}" for log in today_logs]
    if not logs_data:
        logs_data = ["(No activity logged yet today)"]

    notebook = current_user.notebook
    quick_note = todos_to_text(load_todos(current_user))

    profile = load_user_profile(current_user)

    system_prompt, user_prompt = get_audit_prompt(
        notebook, quick_note, logs_data,
        tone=user_tone,
        current_time=client_time,
        user_profile=profile,
    )

    tone_temperature = {"gentle": 1.0, "roast": 0.8, "strict": 0.5}
    audit_temperature = tone_temperature.get(user_tone, 0.5)

    deepseek_api_key = current_app.config.get('DEEPSEEK_API_KEY')

    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": audit_temperature,
        "stream": False,
        "thinking": {"type": "enabled"},
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {deepseek_api_key}"
    }

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=45
        )
        response.raise_for_status()

        full_res = response.json()
        raw_content = full_res['choices'][0]['message']['content']

        clean_json = raw_content.replace("```json", "").replace("```", "").strip()
        ai_data = json.loads(clean_json)

        rubric = ai_data.get('rubric', {}).get('dimensions', [])
        weighted_score = 0
        if rubric:
            for dim in rubric:
                raw_total = sum(p.get('score', 0) for p in dim.get('points', []))
                weighted_score += (raw_total / 20.0) * 100 * dim.get('weight', 0.25)
        final_score = round(weighted_score)

        status = ai_data.get('status', 'green')
        try:
            hour = int(client_time.split(' ')[1].split(':')[0]) if client_time else 12
        except Exception:
            hour = datetime.now().hour
        if hour >= 1 and hour < 6 and logs_data and logs_data[0] != "(No activity logged yet today)":
            status = 'red'
        elif final_score >= 70:
            status = 'green'
        elif final_score >= 40:
            status = 'yellow'
        else:
            status = 'red'

        return jsonify({
            "score": final_score,
            "status": status,
            "insight": ai_data.get('insight', ''),
            "warning": ai_data.get('warning', 'None'),
            "rubric": rubric,
        })

    except Exception as e:
        print(f"DeepSeek Error: {str(e)}")
        return jsonify({
            "score": 0,
            "status": "red",
            "insight": "DeepSeek Connection Failed",
            "warning": f"Technical details: {str(e)}"
        })


@bp.route('/api/visualize', methods=['POST'])
@login_required
def visualize_data():
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()

    if not active_items:
        return jsonify({
            "labels": ["No Data Yet"],
            "data": [0],
            "total_minutes": 0,
            "message": "No data to analyze"
        }), 200

    existing_tags = []
    try:
        recent_tags_query = db.session.query(Expenses.category).filter(
            Expenses.user_id == current_user.id,
            Expenses.category != "Uncategorized",
            Expenses.category != None
        ).distinct().limit(20).all()
        existing_tags = [row[0] for row in recent_tags_query if row[0]]
    except Exception:
        pass

    tags_context = ", ".join(existing_tags) if existing_tags else "None yet"

    entries_text = "\n".join([f"ID_{item.id}: [{item.start_time}-{item.end_time}] {item.desc}" for item in active_items])

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

    deepseek_api_key = current_app.config.get('DEEPSEEK_API_KEY')

    try:
        payload = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Output strictly JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "stream": False,
            "thinking": {"type": "disabled"}
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {deepseek_api_key}"
        }

        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        ai_content = response.json()['choices'][0]['message']['content']
        clean_json = ai_content.replace("```json", "").replace("```", "").strip()
        mapping = json.loads(clean_json)

    except Exception as e:
        print(f"AI/Network Error: {e}")
        return jsonify({"error": "Taxonomy Engine Failed"}), 500

    stats = {}

    for item in active_items:
        key = f"ID_{item.id}"
        category = mapping.get(key, "Uncategorized")

        item.category = category

        duration = calculate_duration(item.start_time, item.end_time)
        stats[category] = stats.get(category, 0) + duration

    db.session.commit()

    return jsonify({
        "labels": list(stats.keys()),
        "data": list(stats.values()),
        "total_minutes": sum(stats.values())
    })


@bp.route('/api/insights/weekly', methods=['POST'])
@login_required
def generate_weekly_insight():
    end_date = date.today()
    start_date = end_date - timedelta(days=6)

    logs = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        Expenses.is_archived == True,
        Expenses.archive_date >= start_date,
        Expenses.archive_date <= end_date
    ).all()

    if len(logs) < 1:
        return jsonify({
            "status": "error",
            "message": "Insufficient data fragments. Please log more activity."
        }), 400

    negative_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=1
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()

    positive_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=5
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()

    rlhf_context = ""

    if negative_feedbacks:
        rlhf_context += "\n[⚠️ HISTORY WARNING - USER DISLIKED THESE PREVIOUS ANALYSES]:\n"
        for fb in negative_feedbacks:
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User rejected: {clean_context}...\n"

    if positive_feedbacks:
        rlhf_context += "\n[✅ HISTORY SUCCESS - USER LIKED THESE PATTERNS]:\n"
        for fb in positive_feedbacks:
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User approved: {clean_context}...\n"

    log_summary = "\n".join([
        f"[{l.archive_date} {l.start_time}-{l.end_time}] {l.category}: {l.desc}"
        for l in logs
    ])

    system_prompt = get_weekly_audit_prompt(log_summary, rlhf_context)

    try:
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

        return jsonify(ai_data)

    except Exception as e:
        print(f"Neural Link Error: {e}")
        return jsonify({"status": "error", "message": f"Neural Link Severed: {str(e)}"}), 500
