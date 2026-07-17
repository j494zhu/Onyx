# Onyx — AI-Augmented Productivity & Time-Tracking Platform

Onyx is a full-stack Flask web application that blends manual time-logging with AI-powered analysis. Users track their daily activities (with start/end times and descriptions), and Onyx uses the DeepSeek API to generate personalized daily productivity audits, weekly insight reports, and automatic session categorization for data visualization.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Features](#core-features)
3. [Backend API Routes](#backend-api-routes)
4. [Database Models](#database-models)
5. [Frontend UI Components](#frontend-ui-components)
6. [AI Pipelines](#ai-pipelines)
7. [Real-Time SSE Sync](#real-time-sse-sync)
8. [Feedback Collection (RLHF Data)](#feedback-collection-rlhf-data)
9. [Infrastructure & Deployment](#infrastructure--deployment)
10. [Configuration](#configuration)
11. [Project File Structure](#project-file-structure)

---

## Architecture Overview

| Layer | Technology |
|-------|-----------|
| Web framework | Flask (Python) |
| ORM / DB | SQLAlchemy with SQLite (local) or PostgreSQL (production via Docker) |
| WSGI server | Gunicorn with gevent worker (`-k gevent -w 4`) |
| Async / pub-sub | Redis (user-scoped `onyx:user:<user_id>` channels) |
| Real-time push | Server-Sent Events (SSE) to browser clients |
| AI backends | DeepSeek API (`deepseek-v4-flash`) via OpenAI-compatible HTTP endpoint |
| Charts | Chart.js v4 (Donut + Bar) |
| Frontend | Vanilla JavaScript, CSS with glassmorphism design |

```
[Browser Client] ── POST/GET ──▶ [Gunicorn + Flask]
                                     │
                   ┌─────────────────┼─────────────────┐
                   ▼                 ▼                  ▼
             [PostgreSQL]       [Redis pub/sub]     [DeepSeek API]
             (persistence)     (cross-worker SSE)   (AI inference)
```

---

## Core Features

### 1. Session Logging

Users log time-based activities with a description, start time, and end time. Each entry is associated with the logged-in user.

**Two input modes:**
- **Manual**: fill in description, start, and end time fields, then hit "Confirm Log".
- **One-click Recorder**: press "Start Session" to auto-capture the current time, press "Stop & Log" to auto-capture the end time, then describe the activity and confirm.

Backend: `routes/main.py` — `POST /` creates a new `TimeEntry` record and publishes an SSE `entry_created` event.

---

### 2. Logical Date System

A custom "logical day" boundary at **06:00 AM**:
- Times between 00:00–05:59 are considered part of the *previous* day.
- This prevents late-night sessions from being split across two dates.

Backend: `app.py:236-243` (`get_logical_date`), also replicated in `services/stats.py`.

---

### 3. Auto-Archival & "End Day"

- **Automatic**: when the user visits the homepage and the current logical date has advanced past an entry's logical date, that entry is marked `is_archived=True`. This happens naturally on page load after 6:00 AM.
- **Manual**: the "Archive Day" button (`POST /end_day`) archives all active entries, clears the To-Do list, and resets the quick note field. The Notebook is preserved.

The Podman service in `app.py` handles this logic at `GET /` route (lines 343-363).

---

### 4. History Browser

`GET /history` provides a paginated view of all archived sessions.

- **Day mode**: displays entries for a single day, navigable via PREV/NEXT.
- **Week mode**: displays entries for a Monday–Sunday week, navigable via PREV/NEXT.
- Each day group shows:
  - Entry count, total hours, focus percentage.
  - A horizontal category distribution bar.
  - Individual log items with category tags.

Backend: `app.py:418-494`, template at `templates/history.html`.

---

### 5. To-Do Checklist

A structured task list stored as a JSON array of `[{id, text, done}]` in the `User.todos` column.

- **Add** tasks via the input field and Enter key.
- **Check/Uncheck** items to toggle completion.
- **Edit** text by double-clicking a task (inline editing).
- **Delete** items via the × button.
- **Auto-save** to backend on every change.
- **Daily-cleared**: the To-Do list is cleared when the user archives the day.
- **Legacy migration**: old `quick_note` free-text is automatically converted into todo items using regex parsing of numbered/bulleted lines.

Backend: `app.py:613-628` (`POST /save_todos`), `app.py:196-222` (`migrate_quick_note_to_todos`).

---

### 6. Permanent Notebook

A persistent text area for long-term notes, system designs, or knowledge retention. It is **not** cleared on day archival.

- Debounced auto-save (1-second inactivity), saved via `POST /save_notes`.
- Status badge shows "Saving..." → "Saved HH:MM:SS".

Backend: `app.py:590-610`.

---

### 7. Pomodoro Timer

A backend-synced focus timer with a state machine:

| Phase | Duration |
|-------|----------|
| WORK | 25 minutes |
| SHORT BREAK | 3 minutes |
| LONG BREAK | 15 minutes |

- 4 WORK cycles → 1 LONG BREAK. Otherwise WORK → SHORT BREAK.
- State (`remaining_seconds`, `phase`, `cycle_count`, `running`) is persisted per-user in `User.pomodoro_state` (JSON in DB).
- State survives page refresh — the backend returns the last saved state, and the client recalculates elapsed time since `paused_at`.
- Autosaves to backend every 15 seconds while running; saves on `beforeunload`.
- Cycle dots (4 dots) show progress through the current cycle set.
- Browser tab title reflects the current timer when running.

Backend: `app.py:1046-1075` (`POST /api/pomodoro/save`, `GET /api/pomodoro/load`).

---

### 8. Login Streak

Tracks consecutive daily usage:
- On each session log (`POST /`), `update_user_streak` checks if the current date is 1 day after `last_check_in`.
- If yes: streak increments (+1).
- If same day: no change.
- If gap > 1 day: streak resets to 1.
- Displayed in the Data Matrix on the dashboard.

Backend: `services/streak.py`.

---

### 9. Dark Mode

A complete light/dark theme system:

- **Pre-paint script** in `<head>` applies `dark-mode` class to `<html>` before any CSS renders — avoids a "white flash" on dark-mode load.
- **Auto-detection**: follows OS `prefers-color-scheme` on first visit.
- **Manual toggle**: clicking the sun/moon icon in the header overrides and persists the choice in `localStorage`.
- **Explicit choice wins**: if the user toggles manually, the OS preference is ignored until localStorage is cleared.

Implementation: `static/scripts/dark_mode.js`, pre-paint script in `templates/index.html:10-19`.

---

### 10. Data Matrix Dashboard

A compact 4-cell stats panel on the homepage showing:

| Cell | Metric | Live-updated |
|------|--------|:--:|
| Logged | Total hours tracked today | ✓ |
| Deep Work | Deep work hours (keyword-based) | ✓ |
| Streak | Consecutive login days | |
| RLHF Dataset | Feedback samples count + confidence bar | |

The "Logged" and "Deep Work" cells refresh automatically whenever a session is created or deleted (via SSE and `/api/stats`).

---

### 11. Data Visualization

`POST /api/visualize` sends today's entries to the DeepSeek API for automatic categorization:

1. **Context retrieval**: fetches up to 20 recently-used category tags from the DB.
2. **AI taxonomy**: DeepSeek assigns each entry a single category (1-2 words).
3. **Persist**: the assigned category is saved back to `TimeEntry.category`.
4. **Render**: Chart.js renders a Donut or Bar chart with the distribution.

**Chart features:**
- Toggle between Donut and Bar modes.
- Manual "Refresh" button re-pulls data without full page reload.
- Custom color palette (10 colors, assigned by index; no repeats).
- Legend with category names and percentages.
- Total tracked time footer.
- Loading spinner, empty state ("Awaiting Data Input").

Backend: `app.py:795-901`.

---

### 12. Static Cache Busting

Every static file URL is automatically versioned with a query parameter `?v=<file_mtime>`. This ensures browsers and Nginx caches are bypassed after deployments without manual intervention.

Backend: `app.py:80-97` (`_static_cache_bust`).

---

### 13. CLI Command

```
flask count-users
```

Prints the total number of registered users. Implemented at `app.py:1078-1086`.

---

## Backend API Routes

| Method | Path | Auth | Description |
|--------|------|:----:|-------------|
| `GET` | `/` | ✓ | Homepage dashboard, auto-archives old entries |
| `POST` | `/` | ✓ | Create a new session log |
| `POST` | `/end_day` | ✓ | Manually archive all active entries + clear To-Do |
| `GET` | `/history` | ✓ | History browser (day/week pagination) |
| `GET` | `/login` | | Login page |
| `POST` | `/login` | | Authenticate user |
| `GET` | `/register` | | Registration page |
| `POST` | `/register` | | Create new user account |
| `GET` | `/logout` | ✓ | Log out current user |
| `POST` | `/api/entries/<id>` | ✓ | Delete a time entry |
| `POST` | `/api/notes` | ✓ | Save notebook or quick note text |
| `POST` | `/api/todos` | ✓ | Persist To-Do checklist |
| `GET` | `/api/events` | ✓ | SSE stream for real-time sync |
| `POST` | `/api/ai/audit` | ✓ | Run daily Neural Audit (DeepSeek) |
| `POST` | `/api/visualize` | ✓ | AI-powered session categorization + chart data |
| `GET` | `/api/stats` | ✓ | Lightweight tracked-time stats (no LLM) |
| `POST` | `/api/alignment` | ✓ | Submit RLHF feedback |
| `POST` | `/api/insights/weekly` | ✓ | Generate Weekly Intel report (DeepSeek) |
| `POST` | `/api/pomodoro` | ✓ | Persist pomodoro timer state |
| `GET` | `/api/pomodoro` | ✓ | Restore pomodoro timer state |
| `GET`/`POST` | `/onboarding`, `/settings`, `/api/profile` | ✓ | User profile pages / API |

### Rate Limiting

The Neural Audit endpoint (`/api/ai/audit`) enforces a **15-second cooldown** between consecutive calls per user session, plus Redis-backed limits of 3/minute and 20/hour per user. Exceeding either returns HTTP 429.

---

## Database Models

### `User`
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `username` | String(100), unique | |
| `password` | String(255) | PBKDF2:SHA256 hashed |
| `quick_note` | Text | Daily note (cleared on archive) |
| `notebook` | Text | Permanent notes |
| `todos` | Text | JSON array `[{id, text, done}]` |
| `streak` | Integer | Consecutive days |
| `last_check_in` | String(20) | ISO date of last activity |
| `pomodoro_state` | Text | JSON state object |

### `TimeEntry`

Maps to the legacy database table `expenses` (kept for data compatibility; the project has no migration framework).

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `desc` | String | Session description |
| `start_time` | String | "HH:MM" format |
| `end_time` | String | "HH:MM" format |
| `timestamp` | DateTime | Creation time |
| `is_archived` | Boolean | False = shown on homepage |
| `archive_date` | Date | Which logical day it belongs to |
| `user_id` | Integer FK | |
| `category` | String(50) | AI-assigned, default "Uncategorized" |

### `AlignmentSignal`
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `user_id` | Integer FK | |
| `input_context` | Text | Context sent to AI (e.g., "Tone: strict") |
| `ai_response` | Text | AI output at feedback time |
| `reward_score` | Integer | 1, 2, 4, or 5 (see feedback section) |
| `human_correction` | Text | Optional correction text |
| `timestamp` | DateTime | |

### Schema Migration

The app auto-adds missing columns (`todos`, `pomodoro_state`) on startup via `ensure_user_columns()`. Uses advisory locks on PostgreSQL to prevent race conditions with multiple Gunicorn workers.

Backend: `app.py:249-281`, `app.py:284-298`.

---

## Frontend UI Components

### Layout

The dashboard uses a **bento grid** layout with glassmorphism card design. The current widgets are:

1. **Session** — digital clock + log input form + one-click recorder
2. **History Flow** — live table of today's entries with inline delete
3. **Archive Day** — "End of Watch?" button
4. **To-Do List** — interactive checklist
5. **Notebook** — permanent text area
6. **Data Visualization** — Chart.js donut/bar chart panel
7. **Neural Audit** — HUD with tone selector, score display, RLHF feedback
8. **Data Matrix** — 4-cell stats grid
9. **Pomodoro** — timer with cycle dots and phase status

### JavaScript Modules

All frontend logic is in `static/scripts/`:

| File | Purpose |
|------|---------|
| `dashboard.js` | Clock, recorder, notebook, todos, chart, HUD, modal, pomodoro (unified) |
| `dark_mode.js` | Theme toggle logic, OS preference sync |
| `chart_logic.js` | Standalone chart module (alternative to dashboard.js version) |
| `chart_theme.js` | Obsidian premium color palette definitions |
| `hud_logic.js` | Standalone Neural Audit HUD logic |
| `insight_modal.js` | Weekly Intel modal rendering |
| `notebook.js` | Standalone notebook auto-save |
| `pomodoro.js` | Standalone pomodoro state machine |

### CSS

All stylesheets are in `static/css/`:

| File | Purpose |
|------|---------|
| `dashboard.css` | Main bento grid layout, all widget styles |
| `history.css` | History page styles |
| `login_body.css` | Login page styles |
| `register_body.css` | Register page styles |
| `style.css` | Base/reset styles |
| `shake.css` | Shake animation for form errors |
| `chart_style.css` | Chart-specific overrides |
| `hud_style.css` | Neural Audit HUD styles |
| `index_body.css` | Index page body styles |
| `index_entry.css` | Entry form styles |

---

## AI Pipelines

Both AI features use the **DeepSeek API** (`deepseek-v4-flash` model) via direct HTTP POST to `https://api.deepseek.com/chat/completions` using the OpenAI-compatible format. Chain-of-thought is disabled for speed (`"thinking": {"type": "disabled"}`).

### 9a. Neural Audit (Daily)

**Trigger**: user clicks "Initialize Scan" on the dashboard.

**Input data collected:**
- Today's session logs (start–end time + description)
- Permanent notebook content
- To-Do checklist (rendered as `[x]` / `[ ]` checklist)
- User's local time (passed from browser via `client_time` parameter)

**3 Tone Personas:**

| Tone | Temperature | Persona |
|------|:-----------:|---------|
| STRICT | 0.5 | Professional executive secretary — polite, efficient, direct |
| ROAST | 0.8 | Sharp-tongued, sarcastic secretary — witty but pointed |
| GENTLE | 1.0 | Warm, devoted personal maid — nurturing, never harsh |

**Time-aware logic** (built into the prompt):
- Morning (05:00–10:00): light greeting, don't scold an empty morning.
- Meal windows: remind user to eat if no meal-like logs appear.
- Midday: friendly nudge if To-Do items are untouched.
- Afternoon/evening: push harder on undone tasks.
- Late night (after 23:00): suggest winding down.
- Past 01:00: mandate sleep.

**Output**: JSON `{score, status, insight, warning}`:
- `score`: 0–100 integer (productivity so far).
- `status`: `green` / `yellow` / `red`.
- `insight`: 1-2 sentences in persona's voice.
- `warning`: one actionable reminder, or `"None"`.

Backend: `app.py:689-792`; prompt builder: `services/prompts.py:3-94`.

---

### 9b. Weekly Intel (Weekly Report)

**Trigger**: user clicks "Weekly Intel" in the header nav.

**Input data collected:**
- Last 7 days of archived logs (with categories and descriptions).
- Recent 3 negatively-rated and 3 positively-rated feedback samples (RLHF memory).

**Output**: JSON with 8 fields:

| Field | Description |
|-------|-------------|
| `week_label` | Cryptic CS/sci-fi theme name (e.g., "The Recursive Descent") |
| `neural_phase` | Mental state: HYPER-DRIVE, PLATEAU, BURNOUT RISK, or SYSTEM FRAGMENTATION |
| `peak_window` | Most productive 2-hour window (e.g., "21:00 - 23:00") |
| `deep_work_ratio` | Estimated % time on hard vs shallow tasks (0–100 integer) |
| `primary_mood_color` | Hex color based on neural phase (mostly hardcoded JSON mock data) |
| `achievement` | One-sentence high-level accomplishment summary |
| `roast` | Ruthlessly sharp observation using CS metaphors |
| `optimization_protocol` | Concise actionable advice for next week |

The RLHF memory is injected into the system prompt: positive examples tell the AI what patterns to repeat; negative examples tell it what to avoid (Few-Shot Prompting).

**Note**: The `/api/generate_weekly_insight` endpoint currently returns **hardcoded mock data** (with a 1.5s artificial delay). The real DeepSeek API call is commented out in the source code and awaits activation.

Backend: `app.py:946-1043`; prompt builder: `services/prompts.py:98-155`.

---

### 9c. Session Categorization

**Trigger**: initial page load or clicking the chart "Refresh" button.

The DeepSeek API receives all today's active entries and up to 20 recently-used category tags as context. It returns a JSON mapping `{"ID_<n>": "CategoryName"}`. Each entry gets exactly one category.

Backend: `app.py:795-901`.

---

## Real-Time SSE Sync

Onyx supports real-time cross-tab and cross-device synchronization for the same user via **Server-Sent Events + Redis pub/sub**.

### Architecture

1. Browser opens `GET /api/events` as an EventSource stream.
2. When a user creates/deletes an expense, updates notes, or updates todos, the backend publishes a JSON event to Redis channel `onyx:user:<user_id>`.
3. Any Gunicorn worker serving that user's SSE stream receives the event from Redis and forwards it to the browser.
4. Heartbeat events are sent every ~25 seconds to keep the connection alive.

### Events Sync'd

| Event | Payload | Effect on receiving client |
|-------|---------|---------------------------|
| `entry_created` | `{id, desc, start_time, end_time, timestamp}` | Prepends row to history table |
| `entry_deleted` | `{id}` | Removes row from history table |
| `notebook_updated` | `{type, content, saved_at}` | Updates textarea content |
| `todos_updated` | `{todos, saved_at}` | Re-renders To-Do checklist |
| `heartbeat` | `{ts}` | No-op (health check) |

### Safety Guards

- Stream requires authenticated session.
- Redis unavailable? SSE gracefully returns `redis_unavailable` and the rest of the app works without real-time sync.
- SSE reconnects automatically on connection loss (native EventSource behavior).

Backend: `app.py:631-686`.

---

## Feedback Collection (RLHF Data)

Onyx collects human preference signals to build a dataset for future preference optimization — this is a data collection pipeline, not yet used for model training or active alignment.

### Feedback Points

1. **Neural Audit Feedback**: After each daily audit, a 4-dot scale appears (dislike ← → like). Scores map to `reward_score`: 1, 2, 4, 5. One vote per scan (locked after submission).

2. **Weekly Intel Feedback**: At the bottom of the weekly report modal, two buttons: "Accurate" (score 5) or "Hallucination" (score 1).

### Data Flow

```
User rates AI output  ──▶  POST /api/submit_alignment
                              │
                              ▼
                        AlignmentSignal(row):
                          user_id          = current user
                          input_context    = "Tone: strict" or "Weekly Insight Report"
                          ai_response      = the AI's insight text
                          reward_score     = 1 | 2 | 4 | 5
                              │
                              ▼
                        Stored in DB
```

### Few-Shot Prompting (Weekly Intel)

Before generating the Weekly Intel, the system queries:
- Last 3 negatively-rated signals (`reward_score=1`)
- Last 3 positively-rated signals (`reward_score=5`)

These snippets are injected into the system prompt so the AI adapts its style to what the user previously liked and avoids what they disliked. This achieves style alignment without model retraining.

Backend: `app.py:922-944` (`/api/submit_alignment`), `app.py:968-996` (feedback queries).

---

## Infrastructure & Deployment

### Docker Compose

`docker-compose.yml` defines 3 services:

| Service | Image | Purpose |
|---------|-------|---------|
| `web` | Python 3.12-slim (built from Dockerfile) | Flask + Gunicorn app, exposed at `127.0.0.1:5000` |
| `postgres` | `postgres:16-alpine` | Database, persistent volume `postgres_data` |
| `redis` | `redis:alpine` | Pub/sub for SSE, persistent volume `redis_data` |

Key details:
- Redis requires password (`--requirepass`), enforced at container start.
- `POSTGRES_PASSWORD` and `REDIS_PASSWORD` are fail-fast (`:?... is required`) — missing values abort startup.
- PostgreSQL has healthcheck (`pg_isready`); web starts only after DB is healthy.
- The `web` service uses `env_file: .env` and overrides `DATABASE_URL` and `REDIS_URL` to use Docker service names.

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-k", "gevent", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

### Database

- **Development**: SQLite at `data/site.db` (auto-created if `DATABASE_URL` not set).
- **Production**: PostgreSQL (configured via `DATABASE_URL` env var).
- The app auto-replaces `postgres://` → `postgresql://` in the URL for SQLAlchemy compatibility.
- Schema is created via `db.create_all()` on first run. Missing columns are added via `ensure_user_columns()`.

---

## Configuration

### `.env` / `sample.env`

| Variable | Default | Required | Notes |
|----------|---------|:--------:|-------|
| `SECRET_KEY` | — | ✓ | Flask session signing key |
| `DEEPSEEK_API_KEY` | — | ✓ | DeepSeek API key for AI features |
| `DATABASE_URL` | `sqlite:///data/site.db` | | PostgreSQL for production |
| `REDIS_URL` | `redis://localhost:6379/0` | | Include password: `redis://:<pwd>@host:6379/0` |
| `REDIS_CHANNEL_PREFIX` | `onyx:user` | | Redis pub/sub channel namespace |
| `SSE_HEARTBEAT_SECONDS` | 25 | | Interval between heartbeat events |
| `REDIS_PASSWORD` | — | ✓ (Docker) | Redis authentication password |
| `POSTGRES_DB` | `onyx` | | Database name |
| `POSTGRES_USER` | `onyx` | | Database user |
| `POSTGRES_PASSWORD` | — | ✓ (Docker) | Database password |

### Running Locally (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp sample.env .env
# Edit .env: add SECRET_KEY, DEEPSEEK_API_KEY

# Run (gevent WSGI)
python app.py
# => http://127.0.0.1:5000
```

### Running with Docker Compose (Production)

```bash
cp sample.env .env
# Edit .env: set DEEPSEEK_API_KEY, REDIS_PASSWORD, POSTGRES_PASSWORD
docker compose up --build
```

---

## Project File Structure

```
Onyx/
├── app.py                  # Flask application: routes, SSE, DB init
├── model.py                # SQLAlchemy models: User, TimeEntry, AlignmentSignal
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Multi-service Docker deployment
├── requirements.txt        # Python dependencies
├── sample.env              # Environment variable template
├── SERVER_HANDOFF.md       # Deployment instructions for server ops
├── issues.txt              # Issue tracking log
├── services/
│   ├── prompts.py          # AI prompt builders (daily audit + weekly intel)
│   ├── stats.py            # Time calculation, keyword-based deep work detection
│   ├── streak.py           # Login streak update logic
│   └── history_helper.py   # History page helper: duration calc, day stats
├── routes/
│   ├── __init__.py
│   ├── login_return.py     # Blueprint stub for login errors
│   └── register_return.py  # (empty)
├── templates/
│   ├── index.html          # Main dashboard (bento grid)
│   ├── history.html        # History browser (day/week pagination)
│   ├── login.html          # Login page with shake errors
│   ├── register.html       # Registration page
│   ├── base.html           # Base template (legacy)
│   ├── login_failed.html   # Countdown redirect page (legacy)
│   └── register_failed.html# Countdown redirect page (legacy)
├── static/
│   ├── css/
│   │   ├── dashboard.css   # Main dashboard + all widget styles
│   │   ├── history.css     # History page styles
│   │   ├── style.css       # Base/reset
│   │   ├── login_body.css  # Login page
│   │   ├── register_body.css# Register page
│   │   ├── shake.css       # Error shake animation
│   │   ├── chart_style.css # Chart overrides
│   │   ├── hud_style.css   # Neural Audit HUD
│   │   ├── index_body.css  # Index body styles
│   │   └── index_entry.css # Entry form styles
│   └── scripts/
│       ├── dashboard.js    # Unified: clock, recorder, notebook, todos, chart, HUD, modal, pomodoro
│       ├── dark_mode.js    # Theme toggle + OS preference sync
│       ├── chart_logic.js  # Standalone chart module
│       ├── chart_theme.js  # Color palette definitions
│       ├── hud_logic.js    # Standalone Neural Audit + RLHF feedback
│       ├── insight_modal.js# Weekly Intel modal rendering + feedback
│       ├── notebook.js     # Standalone notebook auto-save
│       └── pomodoro.js     # Standalone pomodoro state machine
├── data/
│   └── dummy.txt           # Placeholder for SQLite DB directory
├── demo_images/            # README screenshots
└── instance/               # Flask instance folder
```

---

## Known Limitations / Planned

Based on `issues.txt`:

- **Weekly Intel API** currently returns hardcoded mock data; real DeepSeek call is commented out.
- Mobile responsive layout is not yet implemented.
- No Google OAuth login (only username/password).
- No user profiles or preference-based To-Do initialization.
- No cross-device login conflict resolution.
- No global keyboard shortcuts (`Ctrl+Enter` to submit).
- RLHF data is collected but not used for model training or reward modeling yet.
- The `register_return.py` and `__init__.py` files under `routes/` are empty/stubs — the blueprints are not actually registered with the app; all route logic lives in `app.py`.
