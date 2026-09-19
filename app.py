import gevent
from gevent import monkey
monkey.patch_all()
import os
import json
import time

import redis
from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response, stream_with_context
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date, timezone

from sqlalchemy import text as sa_text
from model import db, User, TimeEntry, AlignmentSignal, UserProfile

from dotenv import load_dotenv
load_dotenv()

import click
from flask.cli import with_appcontext

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
REDIS_CHANNEL_PREFIX = os.environ.get('REDIS_CHANNEL_PREFIX', 'onyx:user')
SSE_HEARTBEAT_SECONDS = int(os.environ.get('SSE_HEARTBEAT_SECONDS', '25'))

RATE_LIMIT_PER_MINUTE = 3
RATE_LIMIT_PER_HOUR = 20

# Store config values on the app for access by blueprints via current_app
app.config['REDIS_CHANNEL_PREFIX'] = REDIS_CHANNEL_PREFIX
app.config['SSE_HEARTBEAT_SECONDS'] = SSE_HEARTBEAT_SECONDS
app.config['RATE_LIMIT_PER_MINUTE'] = RATE_LIMIT_PER_MINUTE
app.config['RATE_LIMIT_PER_HOUR'] = RATE_LIMIT_PER_HOUR

# Send Feedback 追加写的 JSONL。生产里 ./feedback 由 docker-compose 挂进容器，
# 否则每次部署重建容器都会把它清空（见 services/feedback.py）。
app.config['FEEDBACK_FILE'] = os.environ.get(
    'FEEDBACK_FILE', os.path.join(app.root_path, 'feedback', 'feedback.jsonl'))

# --- Redis setup ---
redis_client = None
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
except Exception as redis_error:
    print(f"Redis init failed at {REDIS_URL}: {redis_error}")
    redis_client = None

app.redis_client = redis_client

# --- Database setup ---
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
if not database_url:
    sqlite_db_path = os.path.join(app.root_path, 'data', 'site.db')
    os.makedirs(os.path.dirname(sqlite_db_path), exist_ok=True)
    database_url = f"sqlite:///{sqlite_db_path}"
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

db.init_app(app)

# --- Login manager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'


@app.url_defaults
def _static_cache_bust(endpoint, values):
    if endpoint != 'static':
        return
    filename = values.get('filename')
    if not filename:
        return
    try:
        path = os.path.join(app.static_folder, filename)
        values['v'] = int(os.stat(path).st_mtime)
    except OSError:
        pass


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def ensure_user_columns():
    engine = db.engine
    try:
        inspector = db.inspect(engine)
        existing_cols = {col['name'] for col in inspector.get_columns('user')}
    except Exception as exc:
        app.logger.warning('Schema inspection failed: %s', exc)
        return

    if 'todos' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN todos TEXT DEFAULT '[]'"))
            app.logger.info('Added missing column user.todos')
        except Exception as exc:
            app.logger.info('Skipping adding user.todos (likely a concurrent worker won the race): %s', exc)

    if 'pomodoro_state' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN pomodoro_state TEXT DEFAULT NULL"))
            app.logger.info('Added missing column user.pomodoro_state')
        except Exception as exc:
            app.logger.info('Skipping adding user.pomodoro_state (likely a concurrent worker won the race): %s', exc)

    if 'notebooks' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN notebooks TEXT DEFAULT NULL"))
            app.logger.info('Added missing column user.notebooks')
        except Exception as exc:
            app.logger.info('Skipping adding user.notebooks (likely a concurrent worker won the race): %s', exc)

    if 'todo_lists' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN todo_lists TEXT DEFAULT NULL"))
            app.logger.info('Added missing column user.todo_lists')
        except Exception as exc:
            app.logger.info('Skipping adding user.todo_lists (likely a concurrent worker won the race): %s', exc)

    if 'ui_prefs' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN ui_prefs TEXT DEFAULT NULL"))
            app.logger.info('Added missing column user.ui_prefs')
        except Exception as exc:
            app.logger.info('Skipping adding user.ui_prefs (likely a concurrent worker won the race): %s', exc)

    if 'is_guest' not in existing_cols:
        try:
            with engine.begin() as conn:
                conn.execute(sa_text("ALTER TABLE \"user\" ADD COLUMN is_guest BOOLEAN DEFAULT FALSE"))
            app.logger.info('Added missing column user.is_guest')
        except Exception as exc:
            app.logger.info('Skipping adding user.is_guest (likely a concurrent worker won the race): %s', exc)


# Settings 问卷删除后留在 user_profile 里的旧列。只删这份名单里、且库里确实还在的列，
# 删完后每次启动都是 no-op。
REMOVED_PROFILE_COLUMNS = (
    'typical_wakeup', 'typical_bedtime',
    'breakfast_window_start', 'breakfast_window_end',
    'lunch_window_start', 'lunch_window_end',
    'dinner_window_start', 'dinner_window_end',
    'chronotype', 'peak_start', 'peak_end', 'daily_burden', 'work_style',
    'primary_goal', 'secondary_goals', 'interests', 'ai_role',
    'exercise_goal', 'tracked_habits', 'health_note',
    'updated_at',
)


def drop_profile_columns():
    engine = db.engine
    try:
        existing_cols = {col['name'] for col in db.inspect(engine).get_columns('user_profile')}
    except Exception as exc:
        app.logger.warning('Schema inspection failed: %s', exc)
        return

    for col in REMOVED_PROFILE_COLUMNS:
        if col not in existing_cols:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(sa_text(f'ALTER TABLE user_profile DROP COLUMN {col}'))
            app.logger.info('Dropped column user_profile.%s', col)
        except Exception as exc:
            app.logger.info('Skipping dropping user_profile.%s (likely a concurrent worker won the race): %s', col, exc)


def initialize_database():
    with app.app_context():
        engine = db.engine
        if engine.dialect.name == 'postgresql':
            lock_id = 987654321
            with engine.connect() as conn:
                conn.execute(sa_text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
                try:
                    db.create_all()
                finally:
                    conn.execute(sa_text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
        else:
            db.create_all()
        ensure_user_columns()
        drop_profile_columns()


initialize_database()

# --- 外观设置注入 ---
#
# 把用户的 ui_prefs 翻成 CSS 自定义属性，服务端直接渲染进 <html style="...">。
# 走服务端而不是 localStorage，是为了跨设备跟随账号，顺带彻底没有首屏闪烁。
# 未登录的页面（登录/注册）拿到的是默认值，也就是改造前的原始外观。

from routes.common import load_ui_prefs, ui_prefs_style, default_ui_prefs, BG_DIR, BG_LOCAL, DEFAULT_BG


@app.context_processor
def inject_ui_prefs():
    if current_user.is_authenticated:
        prefs = load_ui_prefs(current_user)
    else:
        prefs = default_ui_prefs()

    # 自定义背景图只存在浏览器本地，服务端给不出 URL；这里始终填内置的回退图，
    # 换设备读不到 IndexedDB 时它就是兜底，读得到则由前端脚本覆盖掉。
    src = prefs['bg']['src']
    is_local = (src == BG_LOCAL)
    filename = DEFAULT_BG if is_local else src
    from flask import url_for
    bg_url = url_for('static', filename=f'{BG_DIR}/{filename}')

    return {
        'ui_prefs': prefs,
        'ui_style': ui_prefs_style(prefs, bg_url),
        'ui_bg_local': is_local,
    }


# --- Register Blueprints ---
from routes import auth_bp, guest_bp, main_bp, profile_bp, notes_bp, sse_bp, data_bp

app.register_blueprint(auth_bp)
app.register_blueprint(guest_bp)
app.register_blueprint(main_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(data_bp)

# --- CLI command ---
@app.cli.command("count-users")
@with_appcontext
def count_users():
    user_count = User.query.count()
    click.echo(f"--------------------------")
    click.echo(f" # of users: {user_count} ")
    click.echo(f"--------------------------")


if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    http_server = WSGIServer(('127.0.0.1', 5000), app)
    print("Gevent Server started on http://127.0.0.1:5000")
    http_server.serve_forever()
