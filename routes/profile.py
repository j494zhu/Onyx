from flask import Blueprint, current_app, render_template, request, jsonify
from flask_login import login_required, current_user

from model import db
from routes.common import (
    BG_DIR, BG_LOCAL, DEFAULT_BG, FONT_ROLES, FONT_STACKS, UI_RANGES,
    _check_rate_limit, builtin_backgrounds, load_ui_prefs, sanitize_ui_prefs,
    ui_prefs_to_text,
)
from services.feedback import (
    EMAIL_MAX, MESSAGE_MAX, NAME_MAX, FeedbackError,
    append_feedback, build_record, clean_feedback,
)

bp = Blueprint('profile', __name__)


# 原来的问卷式设置已全部删除；现在这页放外观设置（亮度、背景、字体）。
@bp.route('/settings')
@login_required
def settings_page():
    return render_template(
        'settings.html',
        prefs=load_ui_prefs(current_user),
        backgrounds=builtin_backgrounds(),
        bg_dir=BG_DIR,
        bg_local=BG_LOCAL,
        default_bg=DEFAULT_BG,
        font_roles=FONT_ROLES,
        font_stacks=FONT_STACKS,
        ui_ranges=UI_RANGES,
    )


@bp.route('/api/settings/save', methods=['POST'])
@login_required
def save_settings():
    """
    整份覆盖外观设置。前端每次改动都提交完整对象，和 notebooks/todolists
    的写法一致；校验全在 sanitize_ui_prefs 里做，越界值夹回区间而不是报错。
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    prefs = sanitize_ui_prefs(payload.get('prefs', payload))
    current_user.ui_prefs = ui_prefs_to_text(prefs)
    db.session.commit()

    return jsonify({'status': 'success', 'prefs': prefs})


@bp.route('/api/settings/reset', methods=['POST'])
@login_required
def reset_settings():
    """恢复到基准外观：直接清空这一列，读的时候自然回落到默认值。"""
    current_user.ui_prefs = None
    db.session.commit()
    return jsonify({'status': 'success', 'prefs': load_ui_prefs(current_user)})


# --- Send Feedback（入口在 settings 页）---
#
# 消息追加写进 JSONL（services/feedback.py），不进数据库。

FEEDBACK_PER_MINUTE = 2
FEEDBACK_PER_HOUR = 10


@bp.route('/feedback')
@login_required
def feedback_page():
    return render_template(
        'feedback.html',
        message_max=MESSAGE_MAX,
        name_max=NAME_MAX,
        email_max=EMAIL_MAX,
    )


@bp.route('/api/feedback', methods=['POST'])
@login_required
def send_feedback():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'status': 'error', 'message': 'Invalid payload.'}), 400

    # 蜜罐字段：真人看不到这个输入框，有值就是机器人。假装成功、什么都不写，
    # 不给它任何"被识破了"的信号。
    if str(payload.get('website') or '').strip():
        return jsonify({'status': 'success'})

    limited, msg = _check_rate_limit(
        current_user.id, scope='feedback',
        per_minute=FEEDBACK_PER_MINUTE, per_hour=FEEDBACK_PER_HOUR)
    if limited:
        return jsonify({'status': 'error', 'message': msg}), 429

    try:
        cleaned = clean_feedback(payload)
    except FeedbackError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

    record = build_record(cleaned, is_guest=getattr(current_user, 'is_guest', False))
    try:
        append_feedback(current_app.config['FEEDBACK_FILE'], record)
    except OSError:
        current_app.logger.exception('Failed to write feedback')
        return jsonify({'status': 'error',
                        'message': "Couldn't send — please try again in a moment."}), 500

    return jsonify({'status': 'success'})
