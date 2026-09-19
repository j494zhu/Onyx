import json
import re as _re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import current_app, request, has_request_context
from model import db

# --- Event constants ---
EVENT_ENTRY_CREATED = 'entry_created'
EVENT_ENTRY_DELETED = 'entry_deleted'
EVENT_NOTEBOOKS_UPDATED = 'notebooks_updated'
EVENT_TODO_LISTS_UPDATED = 'todolists_updated'
EVENT_HEARTBEAT = 'heartbeat'

EVENT_PAYLOAD_SCHEMA = {
    EVENT_ENTRY_CREATED: ('id', 'desc', 'start_time', 'end_time', 'timestamp'),
    EVENT_ENTRY_DELETED: ('id',),
    EVENT_NOTEBOOKS_UPDATED: ('notebooks', 'active_id', 'saved_at'),
    EVENT_TODO_LISTS_UPDATED: ('lists', 'active_id', 'saved_at'),
}

SSE_EVENT_NAMES = set(EVENT_PAYLOAD_SCHEMA.keys())


def serialize_entry(entry):
    return {
        'id': entry.id,
        'desc': entry.desc,
        'start_time': entry.start_time,
        'end_time': entry.end_time,
        'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
    }


def is_ajax_request(req):
    return (
        req.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in req.headers.get('Accept', '')
    )


def user_event_channel(user_id):
    return f"{current_app.config.get('REDIS_CHANNEL_PREFIX', 'onyx:user')}:{user_id}"


def publish_user_event(user_id, event_name, payload):
    if event_name not in SSE_EVENT_NAMES:
        current_app.logger.warning('SSE publish skipped: unknown event=%s', event_name)
        return False

    redis_client = getattr(current_app, 'redis_client', None)
    if redis_client is None:
        current_app.logger.warning('SSE publish skipped: Redis unavailable event=%s user_id=%s', event_name, user_id)
        return False

    message = {
        'event': event_name,
        'data': payload,
        'sent_at': datetime.utcnow().isoformat() + 'Z',
    }

    try:
        channel = user_event_channel(user_id)
        redis_client.publish(channel, json.dumps(message))
        return True
    except Exception as e:
        current_app.logger.exception('SSE publish failed event=%s user_id=%s error=%s', event_name, user_id, str(e))
        return False


def format_sse(event_name, data):
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


# --- To-Do helpers ---

def load_todos(user):
    raw = user.todos or "[]"
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        items = []

    clean = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            text_val = str(it.get('text', '')).strip()
            if not text_val:
                continue
            clean.append({
                'id': str(it.get('id') or len(clean) + 1),
                'text': text_val[:500],
                'done': bool(it.get('done', False)),
            })
    return clean


def sanitize_todos(items):
    clean = []
    if not isinstance(items, list):
        return clean
    for it in items[:200]:
        if not isinstance(it, dict):
            continue
        text_val = str(it.get('text', '')).strip()
        if not text_val:
            continue
        clean.append({
            'id': str(it.get('id') or len(clean) + 1),
            'text': text_val[:500],
            'done': bool(it.get('done', False)),
        })
    return clean


def migrate_quick_note_to_todos(quick_note):
    if not quick_note:
        return []

    marker = _re.compile(r'^\s*(?:\d+[.、)]|[-*•])\s+')
    items = []
    for line in quick_note.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if marker.match(line) or not items:
            text_val = marker.sub('', stripped).strip()
            if text_val:
                items.append(text_val)
        else:
            items[-1] = (items[-1] + ' ' + stripped).strip()

    return [
        {'id': str(i + 1), 'text': t[:500], 'done': False}
        for i, t in enumerate(items) if t
    ]


def todos_to_text(todos):
    if not todos:
        return ""
    lines = []
    for t in todos:
        mark = '[x]' if t.get('done') else '[ ]'
        lines.append(f"{mark} {t.get('text', '')}")
    return "\n".join(lines)


# --- Multi To-Do list helpers ---
# 多 To-Do list 存成 JSON 数组 [{id, name, todos}]，放在 User.todo_lists 这个 Text 列里。
# 结构和多 notebook 完全一致：至少永远保留一个，删到只剩一个时后端拒绝、
# 前端隐藏删除按钮，这样 load_todo_lists() 的迁移分支不会被二次触发。

TODO_LIST_NAME_MAX = 40
TODO_LIST_MAX_COUNT = 30
DEFAULT_TODO_LIST_NAME = 'To-Do List'


def sanitize_todo_lists(items):
    """把任意输入整理成合法的 to-do list 数组；非法项直接丢弃。"""
    clean = []
    if not isinstance(items, list):
        return clean
    seen_ids = set()
    for it in items[:TODO_LIST_MAX_COUNT]:
        if not isinstance(it, dict):
            continue
        list_id = str(it.get('id') or '').strip()
        if not list_id or list_id in seen_ids:
            list_id = str(len(clean) + 1)
            while list_id in seen_ids:
                list_id = str(int(list_id) + 1)
        seen_ids.add(list_id)

        name = str(it.get('name', '')).strip()[:TODO_LIST_NAME_MAX] or DEFAULT_TODO_LIST_NAME
        clean.append({
            'id': list_id,
            'name': name,
            'todos': sanitize_todos(it.get('todos', [])),
        })
    return clean


def load_todo_lists(user):
    """
    读出该用户的 to-do list 数组，保证至少有一个。

    首次读取（todo_lists 列还是空的）时，把旧的单栏 user.todos 迁成第一个。
    旧列本身不清空，留作迁移前的备份。
    """
    raw = user.todo_lists
    lists = []
    if raw:
        try:
            lists = sanitize_todo_lists(json.loads(raw))
        except (ValueError, TypeError):
            lists = []

    if not lists:
        lists = [{
            'id': '1',
            'name': DEFAULT_TODO_LIST_NAME,
            'todos': load_todos(user),
        }]
    return lists


def next_list_id(items):
    """取一个当前没被占用的数字 id（notebook 和 to-do list 共用）。"""
    used = {b.get('id') for b in items}
    n = len(items) + 1
    while str(n) in used:
        n += 1
    return str(n)


# --- Notebook helpers ---
# 多笔记本存成 JSON 数组 [{id, name, content}]，放在 User.notebooks 这个 Text 列里。
# 至少永远保留一本：删到只剩一本时后端会拒绝，前端也不显示删除按钮，
# 这样 load_notebooks() 的迁移分支就不会在清空后被二次触发。

NOTEBOOK_NAME_MAX = 40
NOTEBOOK_CONTENT_MAX = 100_000
NOTEBOOK_MAX_COUNT = 30
DEFAULT_NOTEBOOK_NAME = 'Notebook'


def sanitize_notebooks(items):
    """把任意输入整理成合法的 notebook 列表；非法项直接丢弃。"""
    clean = []
    if not isinstance(items, list):
        return clean
    seen_ids = set()
    for it in items[:NOTEBOOK_MAX_COUNT]:
        if not isinstance(it, dict):
            continue
        nb_id = str(it.get('id') or '').strip()
        if not nb_id or nb_id in seen_ids:
            nb_id = str(len(clean) + 1)
            while nb_id in seen_ids:
                nb_id = str(int(nb_id) + 1)
        seen_ids.add(nb_id)

        name = str(it.get('name', '')).strip()[:NOTEBOOK_NAME_MAX] or DEFAULT_NOTEBOOK_NAME
        content = it.get('content', '')
        if not isinstance(content, str):
            content = ''

        clean.append({
            'id': nb_id,
            'name': name,
            'content': content[:NOTEBOOK_CONTENT_MAX],
        })
    return clean


def load_notebooks(user):
    """
    读出该用户的 notebook 列表，保证至少有一本。

    首次读取（notebooks 列还是空的）时，把旧的单栏 user.notebook 迁成第一本。
    旧列本身不清空，留作迁移前的备份。
    """
    raw = user.notebooks
    books = []
    if raw:
        try:
            books = sanitize_notebooks(json.loads(raw))
        except (ValueError, TypeError):
            books = []

    if not books:
        legacy = user.notebook or ''
        books = [{
            'id': '1',
            'name': DEFAULT_NOTEBOOK_NAME,
            'content': legacy[:NOTEBOOK_CONTENT_MAX],
        }]
    return books


def next_notebook_id(books):
    return next_list_id(books)


# --- Logical date helper ---

def get_logical_date(dt_obj):
    if dt_obj.hour < 6:
        return (dt_obj - timedelta(days=1)).date()
    return dt_obj.date()


# --- 用户本地时间 ---
#
# 生产容器（python:3.12-slim）的系统时区是 UTC，直接用 datetime.now() 会让
# 仪表盘的日期/星期在多伦多晚上 8 点左右就翻到第二天。这里改成：
#   1. 浏览器把自己的 IANA 时区写进 cookie（见 templates/index.html 头部脚本）
#   2. 后端校验后按该时区取"现在"
#   3. 没有 cookie 或时区名非法，回落到多伦多
# 返回 naive datetime，和库里 TimeEntry.timestamp（也是 naive 本地时间）保持一致，
# get_logical_date() 可以直接吃。

TZ_COOKIE = 'onyx_tz'
DEFAULT_TZ = 'America/Toronto'
_TZ_NAME_RE = _re.compile(r'^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,3}$')


def resolve_user_tz(name=None):
    """把时区名解析成 ZoneInfo；name 为空时读 cookie；非法一律回落多伦多。"""
    if name is None and has_request_context():
        name = request.cookies.get(TZ_COOKIE)
    if name and len(name) <= 64 and _TZ_NAME_RE.match(name):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo(DEFAULT_TZ)


def now_local():
    """当前用户时区下的"现在"（naive datetime）。"""
    return datetime.now(resolve_user_tz()).replace(tzinfo=None)


# --- 外观设置（User.ui_prefs）---
#
# 存的是一个小 JSON：亮度系数、背景（图/模糊/压暗）、四档字体。渲染时被翻成
# 一串 CSS 自定义属性写进 <html style="...">，所以服务端**必须**把每个值
# 收进白名单/区间里 —— 否则这里就是一条 CSS 注入路径。
#
# 用户自己上传的背景图不经过服务器：它躺在浏览器的 IndexedDB 里，库里只记
# bg.src == 'local' 这个标记。换一台设备读不到那张图时，自动回落到 DEFAULT_BG。

BG_DIR = 'images/Obsidian'
DEFAULT_BG = '4k-forest-7sfd6znw2ry6hnlt.jpg'
BG_LOCAL = 'local'
_BG_EXTS = ('.jpg', '.jpeg', '.png', '.webp')

# 四档字体各自的可选项。值是完整的 font-family 栈，全部走系统字体，
# 不引入新的 Google Fonts 请求（Inter 本来就已经在加载）。
FONT_STACKS = {
    'inter':     "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    'system':    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    'verdana':   "Verdana, Geneva, sans-serif",
    'trebuchet': "'Trebuchet MS', 'Lucida Grande', sans-serif",
    'times':     "'Times New Roman', Times, serif",
    'georgia':   "Georgia, Cambria, 'Times New Roman', serif",
    'palatino':  "'Palatino Linotype', 'Book Antiqua', Palatino, serif",
    'consolas':  "'Consolas', 'Monaco', 'Courier New', monospace",
    'monoui':    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
    'courier':   "'Courier New', Courier, monospace",
}

# 每档允许的选项 + 默认值（默认值一律等于改造前的现状，"以现在作为基准"）。
FONT_ROLES = {
    'clock':   {'default': 'consolas', 'options': ('consolas', 'monoui', 'courier', 'times', 'georgia', 'inter')},
    'ui':      {'default': 'inter',    'options': ('inter', 'system', 'verdana', 'trebuchet', 'georgia')},
    'display': {'default': 'times',    'options': ('times', 'georgia', 'palatino', 'inter', 'consolas')},
    'content': {'default': 'inter',    'options': ('inter', 'system', 'georgia', 'times', 'monoui', 'trebuchet')},
}

# 连续量的区间与基准。基准值即当前视觉，滑块居中就是"不改"。
UI_RANGES = {
    'lum':  {'default': 1.0, 'min': 0.75, 'max': 1.35},
    'blur': {'default': 0.0, 'min': 0.0,  'max': 24.0},
    'dim':  {'default': 1.0, 'min': 0.5,  'max': 1.6},
}


def builtin_backgrounds():
    """static/images/Obsidian 下的内置背景图文件名，排序后返回。"""
    import os
    folder = os.path.join(current_app.static_folder, *BG_DIR.split('/'))
    try:
        names = os.listdir(folder)
    except OSError:
        return [DEFAULT_BG]
    return sorted(n for n in names if n.lower().endswith(_BG_EXTS))


def _clamp_num(value, spec):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return spec['default']
    if num != num:  # NaN
        return spec['default']
    return max(spec['min'], min(spec['max'], num))


def _pick_font(value, role):
    spec = FONT_ROLES[role]
    return value if value in spec['options'] else spec['default']


def default_ui_prefs():
    return {
        'lum': UI_RANGES['lum']['default'],
        'bg': {
            'src': DEFAULT_BG,
            'blur': UI_RANGES['blur']['default'],
            'dim': UI_RANGES['dim']['default'],
        },
        'fonts': {role: spec['default'] for role, spec in FONT_ROLES.items()},
    }


def sanitize_ui_prefs(raw):
    """把任意输入收成一份合法的外观设置；缺的补默认值，越界的夹回区间。"""
    prefs = default_ui_prefs()
    if not isinstance(raw, dict):
        return prefs

    prefs['lum'] = round(_clamp_num(raw.get('lum'), UI_RANGES['lum']), 3)

    bg = raw.get('bg')
    if isinstance(bg, dict):
        src = str(bg.get('src') or '').strip()
        if src == BG_LOCAL or src in builtin_backgrounds():
            prefs['bg']['src'] = src
        prefs['bg']['blur'] = round(_clamp_num(bg.get('blur'), UI_RANGES['blur']), 1)
        prefs['bg']['dim'] = round(_clamp_num(bg.get('dim'), UI_RANGES['dim']), 3)

    fonts = raw.get('fonts')
    if isinstance(fonts, dict):
        for role in FONT_ROLES:
            prefs['fonts'][role] = _pick_font(fonts.get(role), role)

    return prefs


def load_ui_prefs(user):
    """读出该用户的外观设置；没存过或存坏了都回落到默认（= 当前视觉）。"""
    raw = getattr(user, 'ui_prefs', None)
    if not raw:
        return default_ui_prefs()
    try:
        return sanitize_ui_prefs(json.loads(raw))
    except (ValueError, TypeError):
        return default_ui_prefs()


def ui_prefs_to_text(prefs):
    return json.dumps(prefs, ensure_ascii=False)


def ui_prefs_style(prefs, bg_url):
    """
    把设置翻成 <html style="..."> 里的那串 CSS 自定义属性。

    只输出数字和白名单里的字体栈，所以这串东西是安全的；Jinja 的自动转义
    会把字体栈里的单引号转成实体，浏览器解回来再交给 CSS，语义不变。
    """
    fonts = prefs['fonts']
    parts = [
        f"--lum:{prefs['lum']:g}",
        f"--bg-blur:{prefs['bg']['blur']:g}px",
        f"--bg-dim:{prefs['bg']['dim']:g}",
        f"--bg-image:url('{bg_url}')",
    ]
    for role in FONT_ROLES:
        parts.append(f"--font-{role}:{FONT_STACKS[fonts[role]]}")
    return ';'.join(parts) + ';'


# --- Rate-limit helper ---

def _check_rate_limit(user_id, scope='audit', per_minute=None, per_hour=None):
    """
    Redis 计数限流，按 (scope, user_id) 分桶。没有 Redis 时一律放行。

    scope 默认 'audit'、限额默认读 RATE_LIMIT_PER_MINUTE/_PER_HOUR —— 这是它
    给已删除的 Neural Audit 用时的原始行为，保持不变；新接口传自己的 scope 和限额。
    """
    redis_client = getattr(current_app, 'redis_client', None)
    if redis_client is None:
        return False, ""

    if per_minute is None:
        per_minute = current_app.config.get('RATE_LIMIT_PER_MINUTE', 3)
    if per_hour is None:
        per_hour = current_app.config.get('RATE_LIMIT_PER_HOUR', 20)
    rate_limit_per_minute = per_minute
    rate_limit_per_hour = per_hour

    try:
        minute_key = f"rate:{scope}:{user_id}:minute"
        hour_key = f"rate:{scope}:{user_id}:hour"

        with redis_client.pipeline() as pipe:
            pipe.incr(minute_key)
            pipe.incr(hour_key)
            pipe.expire(minute_key, 60, nx=True)
            pipe.expire(hour_key, 3600, nx=True)
            minute_count, hour_count, _, _ = pipe.execute()

        if minute_count > rate_limit_per_minute:
            return True, f"Rate limit: {rate_limit_per_minute}/minute. Slow down."
        if hour_count > rate_limit_per_hour:
            return True, f"Rate limit: {rate_limit_per_hour}/hour. Try again later."
        return False, ""
    except Exception:
        return False, ""
