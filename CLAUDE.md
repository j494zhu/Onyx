# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Onyx is a Flask time-tracking/productivity web app with AI-generated daily audits and weekly reports (DeepSeek API), real-time cross-tab sync (SSE + Redis pub/sub), and Chart.js visualizations. Frontend is vanilla JS + Jinja templates — no build step, no bundler.

## Commands

```bash
# Local development (uses SQLite at data/site.db when DATABASE_URL is unset;
# Redis optional — app degrades gracefully without it)
venv/Scripts/activate            # Windows venv is checked into the workspace
pip install -r requirements.txt
python app.py                    # gevent WSGIServer on http://127.0.0.1:5000

# Flask CLI
flask count-users

# Tests (pytest; uses a throwaway SQLite DB, needs no Redis)
venv/Scripts/python.exe -m pytest              # full suite
venv/Scripts/python.exe -m pytest tests/test_entries.py           # one file
venv/Scripts/python.exe -m pytest tests/test_entries.py::test_create_entry_via_form  # one test

# Production stack (Postgres + Redis + Gunicorn)
docker compose up -d --build
```

No linter is configured. Tests live in [tests/](tests/); `tests/conftest.py` sets env vars (temp SQLite, unreachable Redis) **before** importing `app`, so the suite never touches `data/site.db` or needs external services. `FakeRedis` in conftest covers SSE-publish and rate-limit tests.

### Deployment

Pushing to `master` auto-deploys: GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) SSHes to the server, runs `git reset --hard origin/master` and `docker compose up -d --build`. **Every push to master goes live.**

- `.env` is NOT tracked by git — the server maintains its own copy with its own secrets. Compose fails fast if `POSTGRES_PASSWORD` / `REDIS_PASSWORD` are missing.
- Never run `docker compose down -v` on the server — it deletes the data volumes.
- Changing `POSTGRES_PASSWORD` in `.env` does not change the real DB password in an existing volume (see SERVER_HANDOFF.md).
- After deploy, Nginx may serve stale CSS/JS; the app appends `?v=<mtime>` cache-busting to static URLs (`_static_cache_bust` in app.py), but hard-refresh may still be needed.

## Architecture

- **[app.py](app.py)** — single Flask app (no factory). The first three lines are gevent monkey-patching and **must stay first**. Sets up Redis client (`app.redis_client`, may be `None`), DB, login manager, then registers all blueprints. Also runs schema setup at import time.
- **[model.py](model.py)** — SQLAlchemy models: `User`, `UserProfile`, `TimeEntry`, `AlignmentSignal`.
- **[routes/](routes/)** — Flask blueprints, exported via [routes/__init__.py](routes/__init__.py): `auth`, `main` (dashboard + entry CRUD + end_day), `profile`, `notes`, `sse`, `ai` (DeepSeek endpoints), `data` (charts/stats).
- **[routes/common.py](routes/common.py)** — shared helpers: SSE event constants/publishing, todo (de)serialization, logical-date, profile loading, Redis rate limiting.
- **[services/](services/)** — `prompts.py` (all DeepSeek prompt builders), `stats.py`, `streak.py`, `history_helper.py`.
- **[static/scripts/](static/scripts/)** — vanilla JS modules; `dashboard.js` is the main one. **[templates/](templates/)** — Jinja pages.

### Domain quirks

- **`TimeEntry` maps to the legacy DB table `expenses`** (`__tablename__ = 'expenses'`) — the production database predates the rename and there is no migration framework. Never change this mapping without a data-migration plan; a test guards it.
- **Logical date**: the day boundary is 06:00, not midnight — `get_logical_date()` in routes/common.py assigns pre-6am activity to the previous day. Use it for anything date-scoped.
- **Schema migration**: there is no migration framework. `db.create_all()` plus `ensure_user_columns()` in app.py, which idempotently `ALTER TABLE`s new `user` columns at startup (Postgres advisory lock guards multi-worker races). Adding a column to an existing table means adding it both to model.py and to `ensure_user_columns()`.
- **JSON-in-Text columns**: `User.todos`, `User.pomodoro_state`, and several `UserProfile` fields store JSON as text; use the sanitize/load helpers in routes/common.py.

### Real-time sync (SSE)

Mutations publish to Redis channel `onyx:user:<user_id>` via `publish_user_event()`; every Gunicorn worker holding that user's `GET /api/events` stream forwards the event to the browser. New event types must be added to `EVENT_PAYLOAD_SCHEMA` in routes/common.py or publishing is silently skipped. All Redis-dependent features (SSE, rate limiting) no-op gracefully when `app.redis_client` is `None`.

### AI endpoints

`routes/ai.py` calls DeepSeek (`deepseek-v4-flash`) via raw `requests` POST in OpenAI-compatible format; prompts live in `services/prompts.py`. Daily audit (`/api/ai/audit`) has per-user Redis rate limiting plus a 15s session cooldown (user `juncheng` is exempt). `/api/generate_weekly_insight` currently returns hardcoded mock data — the real API call is commented out. User feedback on AI output is stored in `AlignmentSignal` and injected into later prompts as few-shot examples.

## Gotchas

- README.md documents features well, but its `app.py:NNN` line references are stale — the code was since split into `routes/`.
- `SERVER_HANDOFF.md` (in Chinese) documents server deployment pitfalls, especially around `.env` and DB passwords.
