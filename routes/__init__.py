from routes.auth import bp as auth_bp
from routes.main import bp as main_bp
from routes.profile import bp as profile_bp
from routes.notes import bp as notes_bp
from routes.sse import bp as sse_bp
from routes.ai import bp as ai_bp
from routes.data import bp as data_bp

__all__ = [
    'auth_bp', 'main_bp', 'profile_bp', 'notes_bp',
    'sse_bp', 'ai_bp', 'data_bp',
]
