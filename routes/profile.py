
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from model import db
from routes.common import (
    BG_DIR, BG_LOCAL, DEFAULT_BG, FONT_ROLES, FONT_STACKS, UI_RANGES,
    builtin_backgrounds, load_ui_prefs, sanitize_ui_prefs, ui_prefs_to_text,
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
