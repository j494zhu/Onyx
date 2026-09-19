# Onyx

A self-hosted daily time-tracking and planning app. You log what you worked on and when, keep a few to-do lists and notebooks next to it, and review past days or weeks. Open it in two tabs (or on two devices) and edits show up in both without refreshing.

Live instance: **https://onyx.j494zhu.com** — the login page has a *Continue without account* button that creates a throwaway guest account pre-filled with sample data, so you can try everything without registering.

Backend is Flask + SQLAlchemy; frontend is Jinja templates and plain JavaScript with no build step. Production runs on Gunicorn (gevent workers), PostgreSQL and Redis inside Docker Compose, deployed automatically from `master`.

## What it does

- **Session log** – record an activity with a start and end time, either by filling in the form or by pressing *Start Session* / *Stop & Log* to capture the current time. Today's entries appear in the *History Flow* panel; each can be deleted inline.
- **Logical days** – a day rolls over at 06:00, not midnight, so a session that ends at 01:30 still belongs to the previous evening. Entries from earlier days are archived automatically when you next open the dashboard; *Archive Day* does it on demand.
- **History** – browse archived sessions by day or by week, with per-day totals and a rough "focus" percentage based on keywords in the descriptions.
- **To-do lists and notebooks** – multiple tabbed to-do lists and multiple tabbed notebooks per user. Notebook text auto-saves after a short debounce. Neither is cleared when a day is archived.
- **Daily export** – download today's sessions and to-dos as a plain-text file.
- **Dark mode** – follows the OS preference, can be overridden, and applies before first paint to avoid a white flash.
- **Guest mode** – one click creates an isolated guest account seeded with a week of sample history. Guests are deleted on logout, and stale guests (older than 24 h) are purged the next time someone enters as a guest.

## Real-time sync across tabs and workers

Every mutation (entry created or deleted, notebooks saved, to-do lists saved) is published to a per-user Redis channel (`onyx:user:<id>`). Each browser tab holds an open Server-Sent Events stream at `GET /api/events`; the handler subscribes to that user's channel and forwards events to the client.

Redis pub/sub is what makes this work with four Gunicorn workers: the tab that made the change and the tab that needs to hear about it are usually being served by different processes, so an in-process broadcast would not reach them. Heartbeats go out every 25 s to keep proxies from closing idle connections; `X-Accel-Buffering: no` stops Nginx from buffering the stream.

If Redis is unreachable the app keeps working — publishes are skipped with a warning and the SSE endpoint returns a single `redis_unavailable` heartbeat — so the dev setup does not need Redis at all.

Relevant code: `routes/sse.py` (stream), `routes/common.py` (`publish_user_event`, event schema), `static/scripts/dashboard.js` (`EventSource` handlers).

## Deployment

`docker-compose.yml` runs three services: `web` (this app, built from the `Dockerfile`, bound to `127.0.0.1:5000` and reverse-proxied by Nginx on the host), `postgres:16-alpine` with a health check, and `redis:alpine` started with `--requirepass`. Both passwords are required (`${VAR:?...}`), so a missing `.env` value aborts startup instead of falling back to a default.

Pushing to `master` triggers `.github/workflows/deploy.yml`, which SSHes to the server, resets the checkout to `origin/master` and runs `docker compose up -d --build`. `.env` is not tracked and lives only on the server. `SERVER_HANDOFF.md` documents the operational steps (password rotation, migrations, what not to run on a live volume).

Static URLs get a `?v=<mtime>` query string so browsers and Nginx pick up new CSS/JS after a deploy.

## Schema changes without a migration tool

The project has no Alembic. Instead, the schema has evolved in place against a live database:

- On startup `initialize_database()` runs `db.create_all()` under a PostgreSQL advisory lock so that four workers starting at once do not race each other.
- `ensure_user_columns()` then adds any missing columns (`todos`, `pomodoro_state`, `notebooks`, `todo_lists`, `is_guest`) with idempotent `ALTER TABLE ... ADD COLUMN`; if another worker wins the race the error is logged and ignored.
- Features that changed shape were migrated lazily on first read. The single free-text note became a list of to-dos (regex over numbered/bulleted lines); the single to-do list and single notebook each became a JSON array of named tabs. Old columns are kept as a backup and no longer written to.
- The `expenses` table name is a leftover from the project's origin and is kept because the production data lives there.

This was a deliberate trade-off for a single-developer project with a small schema. If the schema kept growing, adopting Alembic would be the next step.

## Time zones

The container runs in UTC. The browser writes its IANA time zone into a cookie on first load; the backend validates the name, resolves it with `zoneinfo`, and uses it for "now", the logical-date boundary and entry timestamps. Invalid or missing values fall back to `America/Toronto`.

## Tests

161 tests under `tests/`, run with `pytest`. `conftest.py` points the app at a throwaway SQLite file and an unreachable Redis port *before* importing it, so the suite touches neither `data/site.db` nor any external service. A small `FakeRedis` records publishes so SSE behaviour can be asserted. Coverage includes auth, entries, logical-date boundaries, to-do/notebook migration and limits, SSE publish/degrade paths, time-zone handling, the header calendar, export formatting, and the guest-account lifecycle (seeding, isolation, deletion, purge).

## Running locally

```bash
pip install -r requirements-dev.txt   # requirements.txt + pytest
cp sample.env .env                    # set SECRET_KEY; the rest has defaults
python app.py                         # http://127.0.0.1:5000, SQLite, no Redis needed
pytest
```

For the full stack:

```bash
cp sample.env .env    # set SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
docker compose up --build
```

## Layout

```
app.py                  app factory-ish setup: config, Redis, DB init, blueprint registration
model.py                User, UserProfile, TimeEntry
routes/
  main.py               dashboard, entry CRUD, archive, history, export
  notes.py              notebook and to-do list endpoints
  sse.py                /api/events stream
  auth.py, guest.py     login/register/logout, guest accounts
  profile.py            settings
  data.py               pomodoro state endpoints (backend only; the timer widget was removed from the UI)
  common.py             event publishing, JSON sanitizers, migrations, time-zone helpers
services/               day statistics, history helpers, streak counter (tracked, not shown)
templates/, static/     Jinja pages, CSS, dashboard.js
tests/                  pytest suite
```

## Limitations

- No migration framework (see above).
- No mobile layout.
- Username/password only; no OAuth.
- Frontend is a single ~1000-line `dashboard.js`; it works but would benefit from being split up.
