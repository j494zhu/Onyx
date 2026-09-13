import json
import secrets
from datetime import datetime, timedelta, time

from flask import Blueprint, redirect
from flask_login import login_user
from werkzeug.security import generate_password_hash

from model import db, User, UserProfile, TimeEntry, AlignmentSignal
from routes.common import (
    get_logical_date, now_local,
    DEFAULT_TODO_LIST_NAME, DEFAULT_NOTEBOOK_NAME,
)

bp = Blueprint('guest', __name__)

# 访客模式：登录页的 "Continue without account"，给面试官免注册直接体验用。
# 每点一次就新建一个独立的访客账号并灌入示例数据，访客之间互不干扰。
# 访客没有可用的密码，登出后再也回不来，所以登出即删除（见 routes/auth.py）；
# 没登出就关掉浏览器的，超过 GUEST_TTL 后由下一位访客进来时顺手清理。
GUEST_TTL = timedelta(hours=24)

# 过去几天的示例记录，按天循环使用，全部已归档，用来填 History 页。
# desc 故意混着 DEEP_KEYWORDS 命中和不命中的，这样 Focus % 不会是 0 或 100。
SAMPLE_HISTORY_DAYS = 6
SAMPLE_DAY_TEMPLATES = [
    [
        ('09:00', '10:30', 'Coding: real-time sync for notebooks'),
        ('10:45', '12:00', 'Study: Postgres indexing'),
        ('12:00', '12:45', 'Lunch'),
        ('13:30', '15:00', 'Algo practice - graphs'),
        ('15:15', '16:00', 'Gym'),
        ('20:00', '21:00', 'Reading'),
    ],
    [
        ('08:30', '09:15', 'Morning walk'),
        ('09:30', '11:30', 'Implement to-do list tabs'),
        ('11:30', '12:15', 'Lunch'),
        ('13:00', '14:30', 'Write unit tests'),
        ('14:30', '15:00', 'Coffee break'),
        ('15:00', '16:30', 'Data structures review'),
    ],
    [
        ('10:00', '11:00', 'Math: linear algebra'),
        ('11:15', '12:30', 'Code review'),
        ('12:30', '13:30', 'Lunch with friends'),
        ('14:00', '16:00', 'Coding: history page stats'),
        ('19:30', '20:30', 'Guitar practice'),
    ],
]

# 今天的示例记录 (desc, 分钟)，按时间顺序；从"现在"往回排，排不进今天
# 06:00 之后的就丢掉，保证不会出现未来的时间，也不会被首页当成旧记录自动归档。
SAMPLE_TODAY = [
    ('Study: system design notes', 60),
    ('Coffee break', 15),
    ('Coding: export feature', 90),
]

SAMPLE_TODO_LISTS = [
    {'id': '1', 'name': DEFAULT_TODO_LIST_NAME, 'todos': [
        {'id': '1', 'text': 'Review pull request feedback', 'done': True},
        {'id': '2', 'text': "Log today's sessions", 'done': True},
        {'id': '3', 'text': 'Finish system design notes', 'done': False},
        {'id': '4', 'text': '30 min algorithm practice', 'done': False},
        {'id': '5', 'text': "Plan tomorrow's priorities", 'done': False},
    ]},
    {'id': '2', 'name': f'{DEFAULT_TODO_LIST_NAME} 2', 'todos': [
        {'id': '1', 'text': 'Call family', 'done': True},
        {'id': '2', 'text': 'Read one chapter of DDIA', 'done': False},
        {'id': '3', 'text': 'Groceries', 'done': False},
    ]},
]

SAMPLE_NOTEBOOKS = [
    {'id': '1', 'name': DEFAULT_NOTEBOOK_NAME, 'content': (
        "Welcome to Onyx!\n"
        "\n"
        "You're using a guest account. Everything here is sample data, "
        "and it is deleted when you log out.\n"
        "\n"
        "Things to try:\n"
        "- Start Session, then Confirm Log: the session lands in History Flow.\n"
        "- Check off tasks. Each to-do tab has its own progress bar.\n"
        "- Open this page in a second tab and edit something: "
        "changes sync live between tabs.\n"
        "- View History: the past week of sample sessions, with daily totals and Focus %.\n"
        "- Archive Day moves today's sessions into History.\n"
    )},
    {'id': '2', 'name': f'{DEFAULT_NOTEBOOK_NAME} 2', 'content': (
        "Ideas\n"
        "- Weekly review every Sunday evening\n"
        "- Try 90-minute focus blocks before lunch\n"
    )},
]


@bp.route('/guest', methods=['POST'])
def guest_login():
    purge_expired_guests()
    user = create_guest_user(now_local())
    login_user(user)
    # 不走 onboarding：面试官是来看功能的，不是来填问卷的
    return redirect('/')


def create_guest_user(now):
    """新建一个带示例数据的访客账号并提交。now 为用户本地时间（naive）。"""
    user = User(
        username=_unused_guest_username(),
        # 随机密码且不告诉任何人：访客账号无法通过登录表单进入
        password=generate_password_hash(secrets.token_urlsafe(32), method='pbkdf2:sha256'),
        is_guest=True,
        todo_lists=json.dumps(SAMPLE_TODO_LISTS),
        notebooks=json.dumps(SAMPLE_NOTEBOOKS),
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(UserProfile(user_id=user.id))

    today = get_logical_date(now)

    for days_ago in range(1, SAMPLE_HISTORY_DAYS + 1):
        day = today - timedelta(days=days_ago)
        template = SAMPLE_DAY_TEMPLATES[(days_ago - 1) % len(SAMPLE_DAY_TEMPLATES)]
        for start, end, desc in template:
            db.session.add(TimeEntry(
                desc=desc, start_time=start, end_time=end, user_id=user.id,
                is_archived=True, archive_date=day,
                timestamp=datetime.combine(day, time.fromisoformat(end)),
            ))

    day_start = datetime.combine(today, time(6, 0))
    cursor = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
    for desc, minutes in reversed(SAMPLE_TODAY):
        start = cursor - timedelta(minutes=minutes)
        if start < day_start:
            break
        db.session.add(TimeEntry(
            desc=desc, start_time=start.strftime('%H:%M'), end_time=cursor.strftime('%H:%M'),
            user_id=user.id, is_archived=False, archive_date=today, timestamp=cursor,
        ))
        cursor = start - timedelta(minutes=10)

    db.session.commit()
    return user


def _unused_guest_username():
    while True:
        username = f'guest-{secrets.token_hex(4)}'
        if not User.query.filter_by(username=username).first():
            return username


def purge_expired_guests():
    # User 表没有创建时间，用同时建出来的 UserProfile.created_at（服务器时间）代替
    cutoff = datetime.now() - GUEST_TTL
    expired = db.session.query(User.id).join(UserProfile).filter(
        User.is_guest == True,
        UserProfile.created_at < cutoff,
    ).all()
    delete_guest_users([user_id for (user_id,) in expired])


def delete_guest_users(user_ids):
    """删除访客账号及其名下所有数据。只认 is_guest 的账号，传进真实用户的 id 不会误删。"""
    if not user_ids:
        return
    ids = [user_id for (user_id,) in db.session.query(User.id).filter(
        User.id.in_(user_ids),
        User.is_guest == True,
    )]
    if not ids:
        return
    # 先删子表再删 user，Postgres 上外键才不会拦
    for model in (TimeEntry, AlignmentSignal, UserProfile):
        model.query.filter(model.user_id.in_(ids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
