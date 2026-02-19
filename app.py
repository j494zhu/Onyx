import os
import json
import requests
from groq import Groq

from flask import Flask, render_template, request, redirect, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from itertools import groupby
from collections import OrderedDict
from sqlalchemy import and_, or_

from services.prompts import get_audit_prompt, get_weekly_audit_prompt
from services.stats import calculate_stats_from_logs, calculate_duration
from services.streak import update_user_streak
from services.history_helper import calculate_duration_minutes, build_day_stats

from dotenv import load_dotenv
load_dotenv()  # ✅ 自动读取 .env 文件中的变量

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
XAI_API_KEY = os.environ.get('XAI_API_KEY')

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///site.db'


db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 辅助函数：计算“逻辑日期” ---
def get_logical_date(dt_obj):
    """
    如果时间在 00:00 到 06:00 之间，算作前一天。
    例如: 1月30日 03:00 -> 逻辑上是 1月29日
    """
    if dt_obj.hour < 6:
        return (dt_obj - timedelta(days=1)).date()
    return dt_obj.date()

# --- 数据库模型 ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    expenses = db.relationship('Expenses', backref='user', lazy=True)

    quick_note = db.Column(db.Text, default="")
    notebook = db.Column(db.Text, default="")

    streak = db.Column(db.Integer, default=0)
    last_check_in = db.Column(db.String(20), default=None)

class Expenses(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    desc = db.Column(db.String, nullable=False)
    start_time = db.Column(db.String, nullable=False)
    end_time = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

    is_archived = db.Column(db.Boolean, default=False) 
    archive_date = db.Column(db.Date, nullable=True)   # 记录这条数据属于哪一个"逻辑日"
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    category = db.Column(db.String(50), default="Uncategorized")

class AlignmentSignal(db.Model):
    # 这是你的核心资产表：用于存储 Human-in-the-Loop 的训练数据
    id = db.Column(db.Integer, primary_key=True)
    
    # 1. 关联用户 (这就是你的 "Annotator")
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # 2. Input (Context): 当时喂给 AI 的数据快照
    # 这里存储你发送给 DeepSeek/Gemini 的 Prompt 上下文（比如当天的任务列表 JSON）
    # 以后训练模型时，这就是 "User Prompt"
    input_context = db.Column(db.Text, nullable=False)
    
    # 3. Output (Prediction): AI 给出的建议/总结
    # 这就是 "Model Completion"
    ai_response = db.Column(db.Text, nullable=False)
    
    # 4. Reward Signal (Ground Truth): 你的反馈
    # 1-5 分，或者 0/1 (二元分类)。这是 RLHF 算法最需要的 "Scalar Reward"
    reward_score = db.Column(db.Integer, nullable=False)
    
    # 5. Correction (Optional): 如果你觉得 AI 说得不对，你写的修正建议
    # 这属于 SFT (Supervised Fine-Tuning) 数据
    human_correction = db.Column(db.Text, nullable=True)
    
    # 元数据
    timestamp = db.Column(db.DateTime, default=datetime.now)

    # 建立关系，方便从 User 查询
    user = db.relationship('User', backref=db.backref('alignment_signals', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 每次应用启动自动建表（省去手动create_all）
with app.app_context():
    db.create_all()

# --- 路由逻辑 ---

@app.route('/', methods=["POST", "GET"])
@login_required
def index(): # get user lgo entry; 
# it is one of the only three routings when the project was initially built :D
    # 1. POST: 添加新记录
    if request.method == 'POST':
        item_desc = request.form.get('desc')
        item_start = request.form.get('start_time')
        item_end = request.form.get('end_time')
        
        # 新增的记录，默认属于当前的"逻辑日"
        logical_date = get_logical_date(datetime.now())
        
        try:
            item = Expenses(
                desc=item_desc, 
                start_time=item_start, 
                end_time=item_end, 
                user_id=current_user.id,
                is_archived=False,           # 默认在首页显示
                archive_date=logical_date    # 标记它属于哪一天
            )
            db.session.add(item)
            update_user_streak(current_user, logical_date)
            db.session.commit()
            return redirect('/')
        except Exception as e:
            return f'Error: {str(e)}'

    # 2. GET: 首页展示
    else:
        # [核心逻辑] 自动检查：是否已经是"新的一天"了？
        # 如果现在的逻辑日期 > 某些未归档记录的逻辑日期，说明那些记录该过期了
        now = datetime.now()
        current_logical_date = get_logical_date(now)
        
        # 查出所有还停留在首页(is_archived=False)的记录
        active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
        
        items_to_archive = False
        for item in active_items:
            # 计算这条记录属于哪一天
            item_logical_date = get_logical_date(item.timestamp)
            
            # 如果这条记录属于"昨天"或更早，且现在已经过了凌晨6点(也就是进入了新的逻辑日)
            if item_logical_date < current_logical_date:
                item.is_archived = True
                item.archive_date = item_logical_date # 确保它的归档日期正确
                items_to_archive = True
        
        if items_to_archive:
            db.session.commit()
        
        # 重新获取剩下的、属于今天的记录
        expenses = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Expenses.timestamp.desc()).all()

        total_h, deep_h = calculate_stats_from_logs(expenses)

        # [NEW] 获取当前用户的 RLHF 样本数量
        rlhf_count = AlignmentSignal.query.filter_by(user_id=current_user.id).count()
        
        # [NEW] 稍微加点戏：计算一个假的 "Model Confidence" (模型置信度)
        # 逻辑：样本越多，置信度越高。比如每 10 个样本涨 1%，起步 75%
        model_confidence = min(99, 75 + int(rlhf_count / 5))
            
        return render_template('index.html', expenses=expenses, total_hours=total_h, deep_hours=deep_h, rlhf_count=rlhf_count, model_confidence=model_confidence)

@app.route('/end_day', methods=['POST'])
@login_required
def end_day():
    """手动结束今天：把首页所有内容强制归档"""
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    
    current_logical_date = get_logical_date(datetime.now())
    
    for item in active_items:
        item.is_archived = True
        # 如果是手动结束，归档日期就按当前的逻辑日期算
        item.archive_date = current_logical_date

    # empty quick_note
    current_user.quick_note = ""
    # and do NOT change notebook
        
    db.session.commit()
    return redirect('/')


@app.route('/history')
@login_required
def history():
    """历史记录页面：按日/周分页，时间轴导航，带每日统计"""

    # ── 1. 解析参数 ──────────────────────────────────
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

    # ── 2. 数据库查询 ───────────────────────────────
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

    # ── 3. 按日期分组 + 计算每日统计 ────────────────
    grouped_history = OrderedDict()  # { date: { 'items': [...], 'stats': {...} } }

    for archive_date, group in groupby(items, key=lambda x: x.archive_date):
        day_items = list(group)
        grouped_history[archive_date] = {
            'items': day_items,
            'stats': build_day_stats(day_items),
        }

    # ── 4. 范围级汇总统计（顶部显示） ───────────────
    total_entries = len(items)
    range_total_min = sum(d['stats']['total_minutes'] for d in grouped_history.values())
    range_total_hours = f"{range_total_min / 60:.1f}h"
    range_days = len(grouped_history)

    # ── 5. 导航边界 ─────────────────────────────────
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

# delete log
@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    del_item = Expenses.query.get_or_404(id)
    if (del_item.user_id != current_user.id):
        return "Unauthorized"
    try:
        db.session.delete(del_item)
        db.session.commit()
        return redirect('/')
    except Exception as e:
        return f"Error deleting item: {e}"

@app.route('/register', methods=['POST', 'GET'])
def register():
    # ... (保持原来的代码) ...
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
    # ... (保持原来的代码) ...
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
    return jsonify({"status": "success", "saved_at": datetime.now().strftime("%H:%M:%S")})


@app.route('/api/ai/audit', methods=['POST'])
@login_required
def ai_audit():
    # --- 1. 速率限制逻辑 (保持不变) ---
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

    # --- 2. 收集数据 (保持不变) ---
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

    # 获取 Prompt 文本
    prompt_text = get_audit_prompt(notebook, quick_note, logs_data, tone=user_tone)

    # --- 3. 调用 Grok API (核心修改点) ---
    # 这里的 Key 建议之后换成环境变量，今晚先跑通

    
    # 构建适配 x.ai 的 OpenAI 兼容格式请求体
    payload = {
        # 👑 冠军选择：比 Mini 更便宜，速度极快
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
        "temperature": 0.1, # 分类任务保持低温，确保稳定
        "stream": False
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {XAI_API_KEY}"
    }

    try:
        # 使用 requests 发送 POST 请求
        response = requests.post(
            "https://api.x.ai/v1/chat/completions", 
            headers=headers, 
            json=payload,
            timeout=30 # 增加超时保护
        )
        response.raise_for_status() # 如果 4xx 或 5xx 则抛出异常
        
        full_res = response.json()
        raw_content = full_res['choices'][0]['message']['content']

        # 清洗并解析 JSON
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
    # A. 获取今日有效数据 (Raw Data)
    active_items = Expenses.query.filter_by(user_id=current_user.id, is_archived=False).all()
    
    if not active_items:
        return jsonify({"error": "No data to analyze"}), 400

    # B. [Context Retrieval] 获取用户历史标签 (Memory)
    # 这是为了保持分类的一致性 (Consistency)
    existing_tags = []
    try:
        # 查询最近使用的前 20 个不重复标签
        recent_tags_query = db.session.query(Expenses.category).filter(
            Expenses.user_id == current_user.id,
            Expenses.category != "Uncategorized",
            Expenses.category != None
        ).distinct().limit(20).all()
        existing_tags = [row[0] for row in recent_tags_query if row[0]]
    except Exception:
        pass # 如果数据库刚重置，这里可能为空，忽略错误

    tags_context = ", ".join(existing_tags) if existing_tags else "None yet"

    # C. 构建数据包
    entries_text = "\n".join([f"ID_{item.id}: [{item.start_time}-{item.end_time}] {item.desc}" for item in active_items])

    # D. 构建 Prompt (High-Concept: Context-Aware Taxonomy)
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

    # E. 调用 xAI (Grok)
    try:
        payload = {
            "model": "grok-4-1-fast-non-reasoning", # 或 gpt-4o-mini
            "messages": [
                {"role": "system", "content": "Output strictly JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1, # 低温以保证稳定
            "stream": False
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {XAI_API_KEY}"
        }
        
        # 发送请求
        response = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        # 解析结果
        ai_content = response.json()['choices'][0]['message']['content']
        clean_json = ai_content.replace("```json", "").replace("```", "").strip()
        mapping = json.loads(clean_json)

    except Exception as e:
        print(f"AI/Network Error: {e}")
        # 如果 AI 挂了，返回一个空的结构，防止前端崩溃
        return jsonify({"error": "Taxonomy Engine Failed"}), 500

    # F. [Data Enrichment] 更新数据库 & 计算统计
    stats = {} 
    
    for item in active_items:
        key = f"ID_{item.id}"
        # 获取分类 (如果 AI 漏了某个ID，回退到 'Uncategorized')
        category = mapping.get(key, "Uncategorized")
        
        # 存入数据库 (持久化标签)
        item.category = category
        
        # 累加时间
        duration = calculate_duration(item.start_time, item.end_time)
        stats[category] = stats.get(category, 0) + duration

    db.session.commit()

    # G. 返回前端绘图数据
    return jsonify({
        "labels": list(stats.keys()),
        "data": list(stats.values()),
        "total_minutes": sum(stats.values())
    })

@app.route('/api/submit_alignment', methods=['POST'])
@login_required
def submit_alignment():
    """接收前端的 RLHF 反馈并存入数据库"""
    try:
        data = request.json
        
        # 严格对应 AlignmentSignal 的字段名
        new_signal = AlignmentSignal(
            user_id=current_user.id,
            input_context=data.get('context', 'Unknown Context'), 
            ai_response=data.get('response', 'User Feedback'), # 修正字段名
            reward_score=data.get('score', 0)                  # 修正字段名
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
    # 1. 设定时间范围 (过去 7 天)
    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    
    # 2. 查询日志数据库
    logs = Expenses.query.filter(
        Expenses.user_id == current_user.id,
        Expenses.is_archived == True, 
        Expenses.archive_date >= start_date,
        Expenses.archive_date <= end_date
    ).all()

    # 防御性编程
    if len(logs) < 1:
        return jsonify({
            "status": "error", 
            "message": "Insufficient data fragments. Please log more activity."
        }), 400
    # =======================================================
    # [NEW] 3. 获取历史 RLHF 反馈 (The Memory Module)
    # =======================================================
    # 查询最近 3 条用户给过“差评” (reward_score=1) 的反馈
    negative_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=1  # 修正字段名
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()
    
    # 查询最近 3 条用户给过“好评” (reward_score=5) 的反馈
    positive_feedbacks = AlignmentSignal.query.filter_by(
        user_id=current_user.id,
        reward_score=5  # 修正字段名
    ).order_by(AlignmentSignal.timestamp.desc()).limit(3).all()
    
    # 构建“上下文记忆”字符串
    rlhf_context = ""
    
    if negative_feedbacks:
        rlhf_context += "\n[⚠️ HISTORY WARNING - USER DISLIKED THESE PREVIOUS ANALYSES]:\n"
        for fb in negative_feedbacks:
            # 截取前 100 个字符作为上下文参考
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User rejected: {clean_context}...\n"
            
    if positive_feedbacks:
        rlhf_context += "\n[✅ HISTORY SUCCESS - USER LIKED THESE PATTERNS]:\n"
        for fb in positive_feedbacks:
            clean_context = fb.input_context[:150].replace('\n', ' ')
            rlhf_context += f"- User approved: {clean_context}...\n"

    # =======================================================

    # 4. 数据预处理 (Log Summary)
    log_summary = "\n".join([
        f"[{l.archive_date} {l.start_time}-{l.end_time}] {l.category}: {l.desc}" 
        for l in logs
    ])
    
    # 5. 获取 Prompt (注入 RLHF 记忆)
    # 注意：确保你的 prompts.py 里的函数已经更新为接收两个参数
    system_prompt = get_weekly_audit_prompt(log_summary, rlhf_context)

    try:
        # --- 真实 AI 调用区域 ---
        # 请根据你实际使用的库 (OpenAI / DeepSeek) 解开下面的注释
        
        # response = client.chat.completions.create(
        #     model="deepseek-chat", # 或 gpt-4o
        #     messages=[{"role": "system", "content": system_prompt}],
        #     temperature=0.7,
        #     response_format={"type": "json_object"} 
        # )
        # ai_content = response.choices[0].message.content
        # ai_data = json.loads(ai_content)
        
        # --- [FALLBACK] Mock Data (为了防止你还没配好 Key 导致报错) ---
        # --- 一旦 API 调通，建议把下面这段删掉或注释掉 ---
        import time
        time.sleep(1.5) 
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
    app.run(debug=True)


#  git checkout -b ai-integration