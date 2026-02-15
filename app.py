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

from services.prompts import get_audit_prompt
from services.stats import calculate_stats_from_logs, calculate_duration
from services.streak import update_user_streak

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
        
        return render_template('index.html', expenses=expenses, total_hours=total_h, deep_hours=deep_h)

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
    """历史记录页面：按日期分组显示"""
    archived_items = Expenses.query.filter_by(
        user_id=current_user.id, 
        is_archived=True
    ).filter(
        Expenses.archive_date.isnot(None)  # ✅ 过滤掉 archive_date 为 None 的脏数据
    ).order_by(
        Expenses.archive_date.desc(), 
        Expenses.timestamp.desc()
    ).all()

    # groupby 要求数据已按 key 排序（上面的 order_by 已保证）
    grouped_history = OrderedDict()
    for archive_date, items in groupby(archived_items, key=lambda x: x.archive_date):
        grouped_history[archive_date] = list(items)

    return render_template('history.html', grouped_history=grouped_history)

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

if __name__ == '__main__':
    app.run(debug=True)


#  git checkout -b ai-integration