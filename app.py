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
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
REDIS_CHANNEL_PREFIX = os.environ.get('REDIS_CHANNEL_PREFIX', 'onyx:user')
SSE_HEARTBEAT_SECONDS = int(os.environ.get('SSE_HEARTBEAT_SECONDS', '25'))

RATE_LIMIT_PER_MINUTE = 3
RATE_LIMIT_PER_HOUR = 20

# Store config values on the app for access by blueprints via current_app
app.config['DEEPSEEK_API_KEY'] = DEEPSEEK_API_KEY
app.config['REDIS_CHANNEL_PREFIX'] = REDIS_CHANNEL_PREFIX
app.config['SSE_HEARTBEAT_SECONDS'] = SSE_HEARTBEAT_SECONDS
app.config['RATE_LIMIT_PER_MINUTE'] = RATE_LIMIT_PER_MINUTE
app.config['RATE_LIMIT_PER_HOUR'] = RATE_LIMIT_PER_HOUR

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


initialize_database()

# --- Register Blueprints ---
from routes import auth_bp, main_bp, profile_bp, notes_bp, sse_bp, ai_bp, data_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(ai_bp)
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
