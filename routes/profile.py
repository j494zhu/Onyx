import json

from flask import Blueprint, render_template, request, redirect, jsonify
from flask_login import login_required, current_user

from routes.common import load_user_profile, _update_profile_from_form

bp = Blueprint('profile', __name__)


@bp.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if request.method == 'POST':
        profile = load_user_profile(current_user)
        data = request.get_json() or {}
        _update_profile_from_form(profile, data)
        from model import db
        db.session.commit()
        return jsonify({"status": "success", "redirect": "/"})

    return render_template('onboarding.html')


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    profile = load_user_profile(current_user)

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            _update_profile_from_form(profile, data)
            from model import db
            db.session.commit()
            return jsonify({"status": "success"})
        _update_profile_from_form(profile, request.form.to_dict())
        from model import db
        db.session.commit()
        return redirect('/')

    profile.work_style_obj = json.loads(profile.work_style or '["solo"]')
    profile.interests_obj = json.loads(profile.interests or '[]')
    profile.ai_role_obj = json.loads(profile.ai_role or '["general"]')
    profile.tracked_habits_obj = json.loads(profile.tracked_habits or '[]')
    sgs = json.loads(profile.secondary_goals or '[]')
    profile.secondary_goals_text = ', '.join(sgs)

    return render_template('settings.html', profile=profile)


@bp.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    profile = load_user_profile(current_user)
    return jsonify({
        'typical_wakeup': profile.typical_wakeup,
        'typical_bedtime': profile.typical_bedtime,
        'breakfast_window_start': profile.breakfast_window_start,
        'breakfast_window_end': profile.breakfast_window_end,
        'lunch_window_start': profile.lunch_window_start,
        'lunch_window_end': profile.lunch_window_end,
        'dinner_window_start': profile.dinner_window_start,
        'dinner_window_end': profile.dinner_window_end,
        'chronotype': profile.chronotype,
        'peak_start': profile.peak_start,
        'peak_end': profile.peak_end,
        'daily_burden': profile.daily_burden,
        'work_style': json.loads(profile.work_style or '["solo"]'),
        'primary_goal': profile.primary_goal,
        'secondary_goals': json.loads(profile.secondary_goals or '[]'),
        'interests': json.loads(profile.interests or '[]'),
        'ai_role': json.loads(profile.ai_role or '["general"]'),
        'exercise_goal': profile.exercise_goal,
        'tracked_habits': json.loads(profile.tracked_habits or '[]'),
        'health_note': profile.health_note,
    })


@bp.route('/api/profile', methods=['POST'])
@login_required
def update_profile():
    profile = load_user_profile(current_user)
    data = request.get_json() or {}
    _update_profile_from_form(profile, data)
    from model import db
    db.session.commit()
    return jsonify({"status": "success"})
