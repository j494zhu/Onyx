# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Onyx is a Flask time-tracking/productivity web app: session logging, a to-do list, tabbed multi-notebooks, a history/archive view, and real-time cross-tab sync (SSE + Redis pub/sub). Frontend is vanilla JS + Jinja templates — no build step, no bundler. **There is no AI left in the app** — every DeepSeek feature has been removed (see "Removed features").

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
- **[routes/](routes/)** — Flask blueprints, exported via [routes/__init__.py](routes/__init__.py): `auth`, `guest` (demo login), `main` (dashboard + entry CRUD + end_day + history), `profile`, `notes` (notebooks + todos), `sse`, `data` (pomodoro).
- **[routes/common.py](routes/common.py)** — shared helpers: SSE event constants/publishing, todo (de)serialization, logical-date, profile loading, Redis rate limiting.
- **[services/](services/)** — `stats.py`, `streak.py`, `history_helper.py`.
- **[static/scripts/](static/scripts/)** — vanilla JS modules; `dashboard.js` is the main one. **[templates/](templates/)** — Jinja pages.

### Domain quirks

- **`TimeEntry` maps to the legacy DB table `expenses`** (`__tablename__ = 'expenses'`) — the production database predates the rename and there is no migration framework. Never change this mapping without a data-migration plan; a test guards it.
- **Logical date**: the day boundary is 06:00, not midnight — `get_logical_date()` assigns pre-6am activity to the previous day. Use it for anything date-scoped. **Two implementations exist with different return types**: [routes/common.py:152](routes/common.py#L152) returns a `date` (this is the one routes use, and what `TimeEntry.archive_date` expects), [services/stats.py:3](services/stats.py#L3) returns a `'%Y-%m-%d'` string. `tests/test_logical_date.py` guards that they agree; import the right one.
- **Deleting an entry is `POST /api/entries/<id>`**, not `DELETE` — the form-post path and the AJAX path share one route ([routes/main.py:135](routes/main.py#L135)).
- **"Deep work" is a hardcoded keyword list**, not AI — `DEEP_KEYWORDS` in [services/stats.py](services/stats.py) substring-matches `desc`. It is the single source for both the dashboard stats and the history page's `Focus %` (via `is_deep_work`); do not fork it.
- **`TimeEntry.category` is dead weight** — no writer and no reader. The AI taxonomy endpoint that populated it (`POST /api/visualize`) and every consumer (history-page `#tag` chips, the category distribution bar, `category_minutes`/`top_category` in `build_day_stats`) have been removed. The column stays in [model.py:86](model.py#L86) only because dropping it is a schema change with no migration framework behind it and the production `expenses` table may have constraints this repo cannot see. Leave it unless you are ready to verify prod.
- **Guest accounts** ([routes/guest.py](routes/guest.py)): "Continue without account" on the login page (`POST /guest`) creates a fresh `User` with `is_guest=True`, a random unusable password, and seeded sample data (6 archived past days, a few of today's sessions fitted after 06:00, two to-do lists, a welcome notebook) and lands on the dashboard. It exists so interviewers can try the app without registering. A guest is **deleted with all its rows on `/logout`**; guests that never log out are purged 24h after creation (`GUEST_TTL`, aged by `UserProfile.created_at`) whenever the next guest is created. `delete_guest_users()` re-checks `is_guest`, so it can never delete a real account.
- **`UserProfile` is a stub**: the settings questionnaire (wake-up/meal windows, chronotype, goals, habits, AI role) and the onboarding wizard were deleted. The table now only holds `id`/`user_id`/`created_at` — kept because guest expiry (`GUEST_TTL`) ages guests by `created_at`. `drop_profile_columns()` in app.py drops the old columns at startup (idempotent; the name list is `REMOVED_PROFILE_COLUMNS`). **New settings do not go here** — they go in `User.ui_prefs` (below).
- **Schema migration**: there is no migration framework. `db.create_all()` plus `ensure_user_columns()` in app.py, which idempotently `ALTER TABLE`s new `user` columns at startup (Postgres advisory lock guards multi-worker races). Adding a column to an existing table means adding it both to model.py and to `ensure_user_columns()`.
- **JSON-in-Text columns**: `User.todo_lists`, `User.todos`, `User.notebooks`, `User.pomodoro_state` and `User.ui_prefs` store JSON as text; use the sanitize/load helpers in routes/common.py.
- **Multi-notebook**: `User.notebooks` holds `[{id, name, content}]`. Four endpoints in [routes/notes.py](routes/notes.py) — `/api/notebooks/save` (per-notebook content autosave, the hot path), `/create`, `/rename`, `/delete` — each writes the whole array and publishes one `notebooks_updated` SSE event carrying the full list plus an `active_id`. **`/rename` has no UI**: tabs are anonymous bookmark glyphs, so `name` is only auto-assigned (`Notebook N`) and surfaces in the tooltip and the delete-confirm text. The endpoint and its tests are kept as the re-add point if naming ever comes back. **There is always at least one notebook**: `/delete` refuses the last one (400) and the UI hides its `×`. That invariant is what stops `load_notebooks()` from re-running its migration branch.
- **Multi to-do list mirrors multi-notebook exactly.** `User.todo_lists` holds `[{id, name, todos: [{id, text, done}]}]`. Four endpoints in [routes/notes.py](routes/notes.py) — `/api/todolists/save` (replaces the whole `todos` array of one list; every check/add/edit/delete goes through it), `/create`, `/rename` (no UI, same as notebooks), `/delete` — each write the whole array and publish one `todolists_updated` SSE event with `lists` + `active_id`. Always at least one list (`/delete` refuses the last one). The dashboard tab strip reuses the notebook `nb-tabs`/`nb-tab`/`nb-btn` CSS with `td-*` element ids; the progress bar is computed from the active list only, so each list's progress is independent. `POST /end_day` only archives time entries (History Flow); it does not touch to-do lists, notebooks or `quick_note`. `GET /api/export/today` prints one section per list when there is more than one. The old `POST /api/todos` endpoint is gone.
- **`User.todos` (flat array) is the pre-migration backup for to-do lists**, exactly like `User.notebook` below: `load_todo_lists()` seeds the first list from it once, nothing writes it any more, do not delete the column. The even older `quick_note` → `todos` regex migration still runs first in the dashboard route, but only while `todo_lists` is still empty.
- **`User.notebook` (singular) is the pre-migration backup.** `load_notebooks()` seeds the first notebook from it the first time a user loads the dashboard, then never reads it again; nothing writes it any more. Do not delete the column — it is the only copy of pre-migration note content.

### Appearance settings (`/settings`)

`/settings` is the appearance page: text brightness, background (image / blur / dimming) and four font roles. All of it lives in **`User.ui_prefs`** (JSON-in-Text), edited via `POST /api/settings/save` (whole-object overwrite) and `POST /api/settings/reset` (nulls the column). Helpers and the whitelists are in routes/common.py.

- **Prefs are rendered server-side into `<html style="...">`** by the `inject_ui_prefs` context processor in app.py — not localStorage, so they follow the account across devices and there is zero first-paint flash. `sanitize_ui_prefs()` clamps every number and whitelists every font key and image filename; **that validation is load-bearing** — the values land in a `style` attribute, so skipping it is a CSS-injection path. Defaults equal the pre-settings visuals, so an unset column renders exactly the old look.
- **[static/css/tokens.css](static/css/tokens.css) holds the shared `:root` token block** (moved out of dashboard.css) plus the background layers. **It must be linked before dashboard.css / settings.css, and after style.css + login_body.css on the history page** (there it has to override those files' `body` background). Adding a token means adding it here, not in a page stylesheet.
- **`--lum` multiplies the alpha of foreground whites only** — text, borders, hairlines. Panel/glass backgrounds are deliberately *not* scaled: brightening foreground and backdrop together leaves contrast unchanged. Any new `rgba(255,255,255,a)` on a foreground property should be written `calc(a * var(--lum))`.
- **The background is two fixed pseudo-elements on `body`** (`body::before` = image + `filter: blur()`, `body::after` = the dimming gradient). It cannot go back on `body` itself: `filter` on `body` would blur every child. `::before` uses `inset: calc(-2px - var(--bg-blur) * 2)` because blur feathers a transparent band into all four edges.
- **Dark mode hides both layers**, so background image / blur / dimming do nothing there — the settings page greys those controls out (`html.dark-mode .is-dark-disabled`, pure CSS) and says so. The `html.dark-mode` black backdrop lives in tokens.css, next to the rule that removes the layers; they have to stay together or a page loses its background and renders white.
- **A user-uploaded background never reaches the server.** [static/scripts/bg_local.js](static/scripts/bg_local.js) downsamples it (long edge 2560, WebP) into **IndexedDB** — not localStorage, whose ~5MB string-only quota cannot hold a base64 wallpaper — plus a ~1KB 96px thumbnail in localStorage that the `_ui_head.html` pre-paint script uses as a placeholder while IndexedDB resolves. The DB only stores the marker `bg.src == 'local'`; on a device with no stored image the server-rendered builtin fallback stays, and the marker is **not** overwritten.

### Real-time sync (SSE)

Production runs 4 gevent Gunicorn workers ([Dockerfile](Dockerfile)), so a user's browser tabs land on different workers — hence the Redis pub/sub fan-out rather than in-process broadcast. Mutations publish to Redis channel `onyx:user:<user_id>` via `publish_user_event()`; every worker holding that user's `GET /api/events` stream forwards the event to the browser. New event types must be added to `EVENT_PAYLOAD_SCHEMA` in routes/common.py or publishing is silently skipped. All Redis-dependent features (SSE, rate limiting) no-op gracefully when `app.redis_client` is `None`.

### Removed features

The AI layer (DeepSeek) is gone: the daily **Neural Audit** (`POST /api/ai/audit`), the **taxonomy engine** (`POST /api/visualize`), and the **Weekly Intel** report (`POST /api/insights/weekly`) were all deleted, along with `routes/ai.py`, `services/prompts.py`, the `ai` blueprint, and `DEEPSEEK_API_KEY`. The Data Visualization, Data Matrix, Neural Audit and Pomodoro widgets are gone from the dashboard too. Check `git log` before re-adding anything here.

Three things survive with **no caller** — kept deliberately, do not "clean up" without asking:

- **`AlignmentSignal` in [model.py](model.py)** — the RLHF feedback table. Its only writer (`POST /api/alignment`) and reader (the weekly prompt) are both gone, but the production table holds real collected rows and this model is the only handle on them.
- **`_check_rate_limit()` in [routes/common.py](routes/common.py)** — guarded the deleted audit endpoint; Redis keys still read `rate:audit:*` and `RATE_LIMIT_PER_MINUTE`/`_PER_HOUR` remain in app.py. It is a working, tested Redis rate limiter worth keeping for the next endpoint that needs one.
- **`GET`/`POST /api/pomodoro` in [routes/data.py](routes/data.py)** plus `User.pomodoro_state` — the widget was removed but the backend was explicitly retained for a future re-add.

## Gotchas

- README.md documents features well, but its `app.py:NNN` line references are stale — the code was since split into `routes/`.
- `SERVER_HANDOFF.md` (in Chinese) documents server deployment pitfalls, especially around `.env` and DB passwords.
- `issues.txt` (in Chinese) is the running feature backlog, tagged `[resolved]` / `[unresolved]` / `[lesson]` / `[cancelled]` — the best source for what the owner intends to build next and why past decisions were made.
- Much of the inline comment prose is Chinese; match the surrounding language when editing a file.
