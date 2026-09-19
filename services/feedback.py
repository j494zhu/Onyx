"""
Send Feedback 的存储：追加写一个 JSONL 文件，一条消息一行。

不进数据库：消息不挂在任何用户上，所以访客登出删号时不会被一起删掉；
作者直接在服务器上 `tail feedback/feedback.jsonl` 就能看。

部署注意：容器每次部署都会重建，文件必须落在挂载进来的目录里
（docker-compose.yml 把宿主机的 ./feedback 挂到 /app/feedback）。
"""
import json
import os
import re
from datetime import datetime, timezone

try:
    import fcntl  # 只有 Linux/macOS 有；生产是 Linux
except ImportError:  # Windows 本地开发
    fcntl = None


MESSAGE_MAX = 2000
NAME_MAX = 80
EMAIL_MAX = 120

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class FeedbackError(ValueError):
    """用户输入不合法；message 可以直接展示给用户。"""


def clean_feedback(payload):
    """
    校验并整理一条反馈，返回要落盘的字段。不合法时抛 FeedbackError。

    长度超限直接报错而不是截断：前端已经用 maxlength 挡住了，能超限的只有
    绕过前端的请求，没必要替它保留内容。
    """
    if not isinstance(payload, dict):
        raise FeedbackError('Invalid payload.')

    message = str(payload.get('message') or '').strip()
    name = str(payload.get('name') or '').strip()
    email = str(payload.get('email') or '').strip()

    if not message:
        raise FeedbackError('Please write a message.')
    if len(message) > MESSAGE_MAX:
        raise FeedbackError(f'Message is longer than {MESSAGE_MAX} characters.')
    if len(name) > NAME_MAX:
        raise FeedbackError(f'Name is longer than {NAME_MAX} characters.')
    if len(email) > EMAIL_MAX:
        raise FeedbackError(f'Email is longer than {EMAIL_MAX} characters.')
    if email and not _EMAIL_RE.match(email):
        raise FeedbackError("That doesn't look like an email address.")

    return {'message': message, 'name': name or None, 'email': email or None}


def append_feedback(path, record):
    """
    把一条记录追加成一行 JSON。

    生产有 4 个 gunicorn worker 同时可能写同一个文件：整行拼好后一次 write，
    外面再加一把排他锁，保证两条消息不会交错成一行坏数据。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + '\n'
    with open(path, 'a', encoding='utf-8') as f:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
        finally:
            if fcntl is not None:
                fcntl.flock(f, fcntl.LOCK_UN)


def build_record(cleaned, is_guest):
    """
    落盘的一行。刻意不存 user_id：名字和邮箱是"可选"的，如果后台还悄悄记着
    是哪个账号发的，那个"可选"就是假的。只留一个 is_guest，方便区分
    面试官试用和真实用户。
    """
    return {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'is_guest': bool(is_guest),
        **cleaned,
    }
