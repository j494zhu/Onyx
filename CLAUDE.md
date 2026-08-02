# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Onyx is a Flask time-tracking/productivity web app with AI-generated daily audits and weekly reports (DeepSeek API), real-time cross-tab sync (SSE + Redis pub/sub), and Chart.js visualizations. Frontend is vanilla JS + Jinja templates — no build step, no bundler.

## Commands

```bash
# Local development (uses SQLite at data/site.db when DATABASE_URL is unset;
# Redis optional — app degrades gracefully without it)
venv/Scripts/activate            # Windows venv is checked into the workspace
pip install -r requirements-dev.txt   # = requirements.txt + pytest
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

- **`main` is the working branch, `master` is the deploy branch.** `origin/HEAD` points at `main` and that is what's normally checked out, but the workflow only triggers on `master`. Pushing to `main` deploys nothing; the two branches drift (as of this writing `origin/master` is 2 commits ahead of `origin/main`). Confirm which branch the user wants before pushing.
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
- **Logical date**: the day boundary is 06:00, not midnight — `get_logical_date()` assigns pre-6am activity to the previous day. Use it for anything date-scoped. **Two implementations exist with different return types**: [routes/common.py:152](routes/common.py#L152) returns a `date` (this is the one routes use, and what `TimeEntry.archive_date` expects), [services/stats.py:3](services/stats.py#L3) returns a `'%Y-%m-%d'` string. `tests/test_logical_date.py` guards that they agree; import the right one.
- **Deleting an entry is `POST /api/entries/<id>`**, not `DELETE` — the form-post path and the AJAX path share one route ([routes/main.py:135](routes/main.py#L135)).
- **"Deep work" is a hardcoded keyword list**, not AI — `deep_keywords` in [services/stats.py](services/stats.py) substring-matches `desc`. Separate from the AI category taxonomy stored in `TimeEntry.category`.
- **Schema migration**: there is no migration framework. `db.create_all()` plus `ensure_user_columns()` in app.py, which idempotently `ALTER TABLE`s new `user` columns at startup (Postgres advisory lock guards multi-worker races). Adding a column to an existing table means adding it both to model.py and to `ensure_user_columns()`.
- **JSON-in-Text columns**: `User.todos`, `User.pomodoro_state`, and several `UserProfile` fields store JSON as text; use the sanitize/load helpers in routes/common.py.

### Real-time sync (SSE)

Production runs 4 gevent Gunicorn workers ([Dockerfile](Dockerfile)), so a user's browser tabs land on different workers — hence the Redis pub/sub fan-out rather than in-process broadcast. Mutations publish to Redis channel `onyx:user:<user_id>` via `publish_user_event()`; every worker holding that user's `GET /api/events` stream forwards the event to the browser. New event types must be added to `EVENT_PAYLOAD_SCHEMA` in routes/common.py or publishing is silently skipped. All Redis-dependent features (SSE, rate limiting) no-op gracefully when `app.redis_client` is `None`.

### AI endpoints

`routes/ai.py` calls DeepSeek (`deepseek-v4-flash`) via raw `requests` POST in OpenAI-compatible format; prompts live in `services/prompts.py`. Three endpoints:

- **`POST /api/ai/audit`** — daily audit. Per-user Redis rate limiting (3/min, 20/hour, set in app.py) plus a 15s session cooldown; user `juncheng` is exempt from both. The AI returns a rubric of weighted dimensions and the server recomputes `final_score` from it, then overrides `status` by score band (and forces `red` for 01:00–06:00 activity).
- **`POST /api/visualize`** — taxonomy engine. Asks the model to bucket unarchived entries into 3–6 categories, then **writes the result back to `TimeEntry.category` and commits** — this endpoint mutates data, it isn't read-only.
- **`POST /api/insights/weekly`** — weekly report. Still gathers logs and builds the real prompt, then **discards it and returns hardcoded mock data** after a `gevent.sleep(1.5)`; the live API call was never wired up ([routes/ai.py:307](routes/ai.py#L307)).

User feedback on AI output is stored in `AlignmentSignal` (`reward_score` 1 = disliked, 5 = liked) and injected into the weekly prompt as few-shot examples.

## Gotchas

- README.md documents features well, but its `app.py:NNN` line references are stale — the code was since split into `routes/`.
- `SERVER_HANDOFF.md` (in Chinese) documents server deployment pitfalls, especially around `.env` and DB passwords.
- `issues.txt` (in Chinese) is the running feature backlog, tagged `[resolved]` / `[unresolved]` / `[lesson]` / `[cancelled]` — the best source for what the owner intends to build next and why past decisions were made.
- Much of the inline comment prose is Chinese; match the surrounding language when editing a file.
