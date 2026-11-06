import json

from sqlalchemy import text

from app import drop_profile_columns, REMOVED_PROFILE_COLUMNS
from model import db, User
from routes.common import (
    BG_LOCAL, BG_LOCAL_LEGACY_ID, BG_LOCAL_PREFIX, BG_NONE, DEFAULT_BG, FONT_ROLES, UI_RANGES,
    default_ui_prefs, sanitize_ui_prefs, ui_prefs_style,
)


def test_settings_page_renders_appearance_controls(auth_client):
    resp = auth_client.get('/settings')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="lum"' in html
    assert 'id="bg-blur"' in html
    assert 'id="bg-dim"' in html
    for role in FONT_ROLES:
        assert f'id="font-{role}"' in html
    # 深色模式下背景图不渲染，页面上必须写明
    assert 'Background image is not visible in dark mode.' in html


def test_dashboard_keeps_settings_link(auth_client):
    html = auth_client.get('/').get_data(as_text=True)
    assert 'href="/settings"' in html


def test_old_settings_endpoints_are_gone(auth_client):
    assert auth_client.post('/settings', json={}).status_code == 405
    assert auth_client.get('/api/profile').status_code == 404
    assert auth_client.get('/onboarding').status_code == 404


def _profile_columns():
    return {c['name'] for c in db.inspect(db.engine).get_columns('user_profile')}


def test_drop_profile_columns_removes_legacy_columns(app):
    # 模拟旧库：user_profile 上还挂着问卷字段
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE user_profile ADD COLUMN primary_goal TEXT DEFAULT ''"))
        conn.execute(text("ALTER TABLE user_profile ADD COLUMN interests TEXT DEFAULT '[]'"))
    assert {'primary_goal', 'interests'} <= _profile_columns()

    drop_profile_columns()

    cols = _profile_columns()
    assert cols.isdisjoint(REMOVED_PROFILE_COLUMNS)
    assert {'id', 'user_id', 'created_at'} <= cols

    drop_profile_columns()  # 再跑一次是 no-op


# ─── 外观设置（User.ui_prefs）────────────────────────────────────

def test_defaults_match_the_pre_settings_look():
    """默认值就是"改造前的原始视觉"——三个连续量都在基准位，字体是原来那几档。"""
    prefs = default_ui_prefs()
    assert prefs['lum'] == 1.0
    assert prefs['bg'] == {'src': DEFAULT_BG, 'blur': 0.0, 'dim': 1.0}
    assert prefs['fonts']['clock'] == 'consolas'
    assert prefs['fonts']['ui'] == 'inter'
    assert prefs['fonts']['display'] == 'times'


def test_sanitize_clamps_out_of_range_numbers(app):
    with app.test_request_context():
        prefs = sanitize_ui_prefs({'lum': 99, 'bg': {'blur': -5, 'dim': 1000}})
    assert prefs['lum'] == UI_RANGES['lum']['max']
    assert prefs['bg']['blur'] == UI_RANGES['blur']['min']
    assert prefs['bg']['dim'] == UI_RANGES['dim']['max']


def test_sanitize_rejects_unknown_fonts_and_images(app):
    """这些值会被渲染进 <html style="...">，白名单之外的一律换成默认值。"""
    with app.test_request_context():
        prefs = sanitize_ui_prefs({
            'fonts': {'ui': 'comic-sans'},
            'bg': {'src': '../../../etc/passwd'},
        })
    assert prefs['fonts']['ui'] == 'inter'
    assert prefs['bg']['src'] == DEFAULT_BG


def test_sanitize_accepts_a_local_image_id(app):
    """自定义图只存在浏览器里，库里记的是 'local:<id>'，告诉前端用哪一张。"""
    with app.test_request_context():
        prefs = sanitize_ui_prefs({'bg': {'src': 'local:mhx1k2abc123'}})
    assert prefs['bg']['src'] == 'local:mhx1k2abc123'


def test_sanitize_maps_the_legacy_local_marker(app):
    """旧版只有一张图，存的是裸 'local'；那张图在 IndexedDB 里的 key 是 'custom'。"""
    with app.test_request_context():
        prefs = sanitize_ui_prefs({'bg': {'src': BG_LOCAL}})
    assert prefs['bg']['src'] == BG_LOCAL_PREFIX + BG_LOCAL_LEGACY_ID


def test_sanitize_rejects_bad_local_ids(app):
    """id 会被渲染进 data-bg-local 属性，只放行 [a-z0-9]{1,32}。"""
    with app.test_request_context():
        for bad in ('local:', 'local:ABC', "local:a'b", 'local:a b', 'local:abc\ndef',
                    'local:../x', 'local:' + 'a' * 33):
            assert sanitize_ui_prefs({'bg': {'src': bad}})['bg']['src'] == DEFAULT_BG, bad


def test_sanitize_accepts_black(app):
    with app.test_request_context():
        assert sanitize_ui_prefs({'bg': {'src': BG_NONE}})['bg']['src'] == BG_NONE


def test_black_background_renders_no_image(auth_client):
    auth_client.post('/api/settings/save', json={'prefs': {'bg': {'src': BG_NONE}}})
    html = auth_client.get('/').get_data(as_text=True)
    assert '--bg-image:none' in html
    assert 'data-bg-local' not in html


def test_sanitize_survives_garbage(app):
    with app.test_request_context():
        assert sanitize_ui_prefs(None) == default_ui_prefs()
        assert sanitize_ui_prefs({'lum': 'bright', 'bg': 'nope'}) == default_ui_prefs()


def test_style_string_only_contains_whitelisted_values():
    style = ui_prefs_style(default_ui_prefs(), '/static/images/Obsidian/x.jpg')
    assert '--lum:1;' in style
    assert '--bg-blur:0px;' in style
    assert "--bg-image:url('/static/images/Obsidian/x.jpg')" in style
    assert '--bg-image:none' in ui_prefs_style(default_ui_prefs(), None)
    assert '--font-clock:' in style


def test_save_round_trips_and_clamps(auth_client):
    resp = auth_client.post('/api/settings/save', json={'prefs': {
        'lum': 1.2,
        'bg': {'src': 'local:abc123', 'blur': 12, 'dim': 99},
        'fonts': {'clock': 'monoui', 'ui': 'georgia'},
    }})
    assert resp.status_code == 200
    prefs = resp.get_json()['prefs']
    assert prefs['lum'] == 1.2
    assert prefs['bg']['src'] == 'local:abc123'
    assert prefs['bg']['blur'] == 12.0
    assert prefs['bg']['dim'] == UI_RANGES['dim']['max']   # 越界被夹回
    assert prefs['fonts']['clock'] == 'monoui'

    stored = json.loads(db.session.get(User, 1).ui_prefs)
    assert stored['fonts']['ui'] == 'georgia'


def test_saved_prefs_reach_the_dashboard_html(auth_client):
    auth_client.post('/api/settings/save', json={'prefs': {'lum': 1.25, 'bg': {'blur': 8}}})
    html = auth_client.get('/').get_data(as_text=True)
    assert '--lum:1.25' in html
    assert '--bg-blur:8px' in html


def test_local_background_marks_the_html_tag(auth_client):
    auth_client.post('/api/settings/save', json={'prefs': {'bg': {'src': 'local:abc123'}}})
    html = auth_client.get('/').get_data(as_text=True)
    # 服务端给不出本地图的 URL，只能标记出 id + 填内置回退图，让前端去 IndexedDB 取
    assert 'data-bg-local="abc123"' in html
    assert DEFAULT_BG in html


def test_reset_clears_the_column(auth_client):
    auth_client.post('/api/settings/save', json={'prefs': {'lum': 1.3}})
    assert db.session.get(User, 1).ui_prefs is not None

    resp = auth_client.post('/api/settings/reset')
    assert resp.status_code == 200
    assert resp.get_json()['prefs'] == default_ui_prefs()
    assert db.session.get(User, 1).ui_prefs is None


def test_settings_endpoints_require_login(client):
    assert client.post('/api/settings/save', json={}).status_code in (302, 401)
    assert client.get('/settings').status_code in (302, 401)


def test_anonymous_render_does_not_break(client):
    """context processor 每次渲染都会跑；未登录时要回落到默认值而不是炸掉。"""
    assert client.get('/login').status_code == 200


def test_context_processor_gives_anonymous_the_defaults(app):
    with app.test_request_context('/login'):
        from app import inject_ui_prefs
        ctx = inject_ui_prefs()
    assert ctx['ui_prefs'] == default_ui_prefs()
    assert ctx['ui_bg_local'] == ''
    assert '--lum:1;' in ctx['ui_style']


def test_login_and_register_use_the_dashboard_background_layers(client):
    """登录/注册页和主页走同一套背景层（tokens.css + <html style>），
    未登录时先给默认图，再由 _ui_head.html 读本机记下的背景。"""
    for path in ('/login', '/register'):
        html = client.get(path).get_data(as_text=True)
        assert 'css/tokens.css' in html, path
        assert f'--bg-image:url(&#39;/static/images/Obsidian/{DEFAULT_BG}' in html, path
        assert "localStorage.getItem('onyx-bg-last')" in html, path
        assert "localStorage.setItem('onyx-bg-last'" not in html, path
        assert 'scripts/bg_local.js' in html, path


def test_logged_in_pages_record_the_background_for_the_login_page(auth_client):
    auth_client.post('/api/settings/save', json={'prefs': {'bg': {'src': 'local:abc123', 'blur': 6, 'dim': 1.2}}})
    html = auth_client.get('/').get_data(as_text=True)
    assert "localStorage.setItem('onyx-bg-last'" in html
    assert '"local": "abc123"' in html
    assert '"blur": 6.0' in html
