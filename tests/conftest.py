import json
import os
import sys
import tempfile

# 项目根目录加入 sys.path，保证能 import app / model
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 必须在 import app 之前设置环境变量：
# - 独立的临时 SQLite，绝不碰 data/site.db 或生产库
# - REDIS_URL 指向不可达端口，让 app 走 redis_client=None 的降级路径
# （app.py 里的 load_dotenv 不会覆盖已存在的环境变量）
_tmpdir = tempfile.mkdtemp(prefix='onyx_test_')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_tmpdir, 'test.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:1/0'
os.environ['DEEPSEEK_API_KEY'] = 'test-deepseek-key'

import pytest

from app import app as flask_app
from model import db, User, UserProfile, AlignmentSignal, TimeEntry


# --- Fake Redis（用于测试 SSE 发布和限流，不依赖真实 Redis） ---

class FakePipeline:
    def __init__(self, fake_redis):
        self._redis = fake_redis
        self._ops = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def incr(self, key):
        self._ops.append(('incr', key))
        return self

    def expire(self, key, ttl, nx=False):
        self._ops.append(('expire', key))
        return self

    def execute(self):
        results = []
        for op, key in self._ops:
            if op == 'incr':
                self._redis.counters[key] = self._redis.counters.get(key, 0) + 1
                results.append(self._redis.counters[key])
            else:
                results.append(True)
        self._ops = []
        return results


class FakeRedis:
    def __init__(self):
        self.published = []   # [(channel, message_json_str), ...]
        self.counters = {}

    def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    def pipeline(self):
        return FakePipeline(self)


# --- Fixtures ---

@pytest.fixture()
def app():
    flask_app.config['TESTING'] = True
    ctx = flask_app.app_context()
    ctx.push()
    db.drop_all()
    db.create_all()
    yield flask_app
    db.session.remove()
    ctx.pop()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def fake_redis(app, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(flask_app, 'redis_client', fake)
    return fake


@pytest.fixture()
def auth_client(client):
    """注册并登录用户 alice，client.user_id 为其 id。"""
    register(client, 'alice', 'password123')
    client.user_id = get_user('alice').id
    return client


# --- Helpers ---

def register(client, username='alice', password='password123'):
    return client.post('/register', data={
        'username': username,
        'password': password,
        'password-confirm': password,
    })


def login(client, username='alice', password='password123'):
    return client.post('/login', data={
        'username': username,
        'password': password,
    })


def get_user(username):
    return User.query.filter_by(username=username).first()


def make_entry(user_id, desc='coding session', start='10:00', end='11:00',
               archived=False, archive_date=None, timestamp=None):
    entry = TimeEntry(
        desc=desc, start_time=start, end_time=end,
        user_id=user_id, is_archived=archived, archive_date=archive_date,
    )
    if timestamp is not None:
        entry.timestamp = timestamp
    db.session.add(entry)
    db.session.commit()
    return entry


class DummyDeepSeekResponse:
    """模拟 requests.post 返回的 DeepSeek 响应。"""

    def __init__(self, content_obj):
        self._content = content_obj

    def raise_for_status(self):
        pass

    def json(self):
        return {'choices': [{'message': {'content': json.dumps(self._content)}}]}
