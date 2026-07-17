from datetime import date, datetime
from types import SimpleNamespace

from services.streak import update_user_streak


def _user(streak=0, last=None):
    return SimpleNamespace(streak=streak, last_check_in=last)


def test_first_check_in_sets_streak_1():
    user = _user()
    assert update_user_streak(user, date(2026, 7, 16)) is True
    assert user.streak == 1
    assert user.last_check_in == '2026-07-16'


def test_same_day_no_change():
    user = _user(streak=5, last='2026-07-16')
    assert update_user_streak(user, date(2026, 7, 16)) is False
    assert user.streak == 5


def test_consecutive_day_increments():
    user = _user(streak=5, last='2026-07-15')
    update_user_streak(user, date(2026, 7, 16))
    assert user.streak == 6


def test_gap_resets_streak():
    user = _user(streak=5, last='2026-07-10')
    update_user_streak(user, date(2026, 7, 16))
    assert user.streak == 1


def test_backwards_date_resets_streak():
    user = _user(streak=5, last='2026-07-20')
    update_user_streak(user, date(2026, 7, 16))
    assert user.streak == 1


def test_corrupt_last_check_in_resets():
    user = _user(streak=5, last='not-a-date')
    assert update_user_streak(user, date(2026, 7, 16)) is True
    assert user.streak == 1


def test_accepts_string_date_input():
    user = _user(streak=1, last='2026-07-15')
    update_user_streak(user, '2026-07-16')
    assert user.streak == 2


def test_accepts_datetime_input():
    user = _user(streak=1, last='2026-07-15')
    update_user_streak(user, datetime(2026, 7, 16, 14, 30))
    assert user.streak == 2


def test_unknown_input_type_returns_false():
    user = _user(streak=5, last='2026-07-15')
    assert update_user_streak(user, 12345) is False
    assert user.streak == 5
