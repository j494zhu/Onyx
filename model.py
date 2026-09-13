from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    time_entries = db.relationship('TimeEntry', backref='user', lazy=True)

    quick_note = db.Column(db.Text, default="")

    # 旧的单栏笔记本。已被 notebooks 取代，仅作为迁移前的备份保留，
    # 不再有任何写入方；迁移逻辑见 routes/common.py 的 load_notebooks()。
    notebook = db.Column(db.Text, default="")

    # 多笔记本，存 JSON 数组 [{id, name, content}]；助手函数在 routes/common.py。
    notebooks = db.Column(db.Text, default=None)

    # 旧的单栏 To-Do。已被 todo_lists 取代，仅作为迁移前的备份保留，
    # 不再有任何写入方；迁移逻辑见 routes/common.py 的 load_todo_lists()。
    todos = db.Column(db.Text, default="[]")

    # 多 To-Do list，存 JSON 数组 [{id, name, todos: [{id, text, done}]}]；
    # 助手函数在 routes/common.py。
    todo_lists = db.Column(db.Text, default=None)

    streak = db.Column(db.Integer, default=0)
    last_check_in = db.Column(db.String(20), default=None)

    pomodoro_state = db.Column(db.Text, default=None)

    # 访客账号（登录页 "Continue without account" 创建），登出即删除；
    # 逻辑见 routes/guest.py。
    is_guest = db.Column(db.Boolean, default=False)

    profile = db.relationship('UserProfile', uselist=False, back_populates='user',
                              cascade='all, delete-orphan')


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True,
                        nullable=False)

    # ── Category 1: Daily Rhythm ──
    typical_wakeup = db.Column(db.String(5), default='08:00')
    typical_bedtime = db.Column(db.String(5), default='23:30')
    breakfast_window_start = db.Column(db.String(5), default='07:00')
    breakfast_window_end = db.Column(db.String(5), default='09:00')
    lunch_window_start = db.Column(db.String(5), default='12:00')
    lunch_window_end = db.Column(db.String(5), default='13:30')
    dinner_window_start = db.Column(db.String(5), default='18:00')
    dinner_window_end = db.Column(db.String(5), default='20:00')

    # ── Category 2: Work Style ──
    chronotype = db.Column(db.String(20), default='morning')
    peak_start = db.Column(db.String(5), default='09:00')
    peak_end = db.Column(db.String(5), default='12:00')
    daily_burden = db.Column(db.String(10), default='medium')
    work_style = db.Column(db.Text, default='["solo"]')  # JSON array

    # ── Category 3: Goals & Focus ──
    primary_goal = db.Column(db.Text, default='')
    secondary_goals = db.Column(db.Text, default='[]')   # JSON array
    interests = db.Column(db.Text, default='[]')          # JSON array
    ai_role = db.Column(db.Text, default='["general"]')   # JSON array

    # ── Category 4: Habits & Wellness ──
    exercise_goal = db.Column(db.String(10), default='light')
    tracked_habits = db.Column(db.Text, default='[]')     # JSON array
    health_note = db.Column(db.Text, default='')

    # ── Metadata ──
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now)

    user = db.relationship('User', back_populates='profile')


class TimeEntry(db.Model):
    # 表名保留历史名 'expenses'：生产库已有数据且项目没有迁移框架，只重命名代码层的类名
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    desc = db.Column(db.String, nullable=False)
    start_time = db.Column(db.String, nullable=False)
    end_time = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

    is_archived = db.Column(db.Boolean, default=False)
    archive_date = db.Column(db.Date, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    category = db.Column(db.String(50), default="Uncategorized")


class AlignmentSignal(db.Model):
    # Store Human-in-the-Loop feedback samples for model alignment.
    id = db.Column(db.Integer, primary_key=True)

    # Link each annotation to the user who provided feedback.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Input context sent to the AI model.
    input_context = db.Column(db.Text, nullable=False)

    # AI output captured at the time of feedback.
    ai_response = db.Column(db.Text, nullable=False)

    # Scalar reward signal from human feedback.
    reward_score = db.Column(db.Integer, nullable=False)

    # Optional user correction text for SFT-style data.
    human_correction = db.Column(db.Text, nullable=True)

    timestamp = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref=db.backref('alignment_signals', lazy=True))
