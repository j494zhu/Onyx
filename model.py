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

    # 外观设置（亮度系数、背景图/模糊/压暗、四档字体），存 JSON 文本；
    # 校验与默认值见 routes/common.py 的 load_ui_prefs() / sanitize_ui_prefs()。
    # 用户自己上传的背景图不在这里 —— 它只存在浏览器的 IndexedDB 里，
    # 这里记的只有 "local" 这个标记和跨设备时的回退图。
    ui_prefs = db.Column(db.Text, default=None)

    # 访客账号（登录页 "Continue without account" 创建），登出即删除；
    # 逻辑见 routes/guest.py。
    is_guest = db.Column(db.Boolean, default=False)

    profile = db.relationship('UserProfile', uselist=False, back_populates='user',
                              cascade='all, delete-orphan')


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True,
                        nullable=False)

    # 原先的问卷字段（作息、目标、习惯等）已随 Settings 内容一起删除，
    # 旧库里的列由 app.py 的 drop_profile_columns() 在启动时清掉。
    # 这张表只剩 created_at：访客账号靠它判断是否过期（routes/guest.py）。
    created_at = db.Column(db.DateTime, default=datetime.now)

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
