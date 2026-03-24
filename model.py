from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    expenses = db.relationship('Expenses', backref='user', lazy=True)

    quick_note = db.Column(db.Text, default="")
    notebook = db.Column(db.Text, default="")

    streak = db.Column(db.Integer, default=0)
    last_check_in = db.Column(db.String(20), default=None)


class Expenses(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    desc = db.Column(db.String, nullable=False)
    start_time = db.Column(db.String, nullable=False)
    end_time = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

    is_archived = db.Column(db.Boolean, default=False)
    archive_date = db.Column(db.Date, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    category = db.Column(db.String(50), default="Uncategorized")


class AlignmentSignal(db.Model):
    # Store Human-in-the-Loop feedback samples for model alignment.
    id = db.Column(db.Integer, primary_key=True)

    # Link each annotation to the user who provided feedback.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Input context sent to the AI model.
    input_context = db.Column(db.Text, nullable=False)

    # AI output captured at the time of feedback.
    ai_response = db.Column(db.Text, nullable=False)

    # Scalar reward signal from human feedback.
    reward_score = db.Column(db.Integer, nullable=False)

    # Optional user correction text for SFT-style data.
    human_correction = db.Column(db.Text, nullable=True)

    timestamp = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref=db.backref('alignment_signals', lazy=True))
