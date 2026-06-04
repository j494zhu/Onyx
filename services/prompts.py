import datetime
import json


def build_profile_section(profile):
    """Build a concise user-profile summary block for the system prompt."""
    if not profile:
        return ""

    lines = ["The user's personal profile (use this to calibrate all judgements):"]
    lines.append(f"  Rhythm: wakes ~{profile.typical_wakeup}, sleeps ~{profile.typical_bedtime}")
    lines.append(f"  Meals: breakfast {profile.breakfast_window_start}-{profile.breakfast_window_end}, "
                 f"lunch {profile.lunch_window_start}-{profile.lunch_window_end}, "
                 f"dinner {profile.dinner_window_start}-{profile.dinner_window_end}")
    lines.append(f"  Chronotype: {profile.chronotype} "
                 f"(peak productive hours {profile.peak_start}-{profile.peak_end})")
    lines.append(f"  Daily burden: {profile.daily_burden}")

    ws = json.loads(profile.work_style or '["solo"]')
    lines.append(f"  Work style: {', '.join(ws)}")

    if profile.primary_goal:
        lines.append(f'  Primary goal: "{profile.primary_goal}"')

    sgs = json.loads(profile.secondary_goals or '[]')
    if sgs:
        lines.append(f"  Secondary goals: {', '.join(sgs)}")

    interests = json.loads(profile.interests or '[]')
    if interests:
        lines.append(f"  Interests: {', '.join(interests)}")

    lines.append(f"  Expected AI role: {profile.ai_role or 'general'}")
    lines.append(f"  Exercise goal: {profile.exercise_goal}")

    habits = json.loads(profile.tracked_habits or '[]')
    if habits:
        lines.append(f"  Tracking: {', '.join(habits)}")

    if profile.health_note:
        lines.append(f"  Health note: {profile.health_note}")

    return "\n".join(lines)


def get_audit_prompt(notebook, quick_note, logs_data, tone="strict",
                     current_time=None, user_profile=None):
    """
    Build the NEURAL AUDIT system + user prompts.
    Returns: (system_prompt: str, user_prompt: str)
    """
    # ── 1. Pre-process user data ──
    notebook_content = notebook if notebook and notebook.strip() else "No long-term goals set."
    todo_content = quick_note if quick_note and quick_note.strip() else "No tasks on the to-do list yet."

    if current_time and str(current_time).strip():
        current_time_str = str(current_time).strip()
    else:
        current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    # ── 2. Persona ──
    if tone == "roast":
        persona = (
            "You are the user's sharp-tongued, sarcastic personal secretary. "
            "You tease and roast them about slacking and bad habits — biting "
            "and witty, but every jab lands on a real point. Underneath the "
            "snark you genuinely still want them to eat and sleep properly."
        )
    elif tone == "gentle":
        persona = (
            "You are the user's warm, devoted personal maid. You speak softly "
            "and affectionately, fuss over their wellbeing, and gently encourage "
            "them. Caring and nurturing, never harsh."
        )
    else:  # strict
        persona = (
            "You are the user's professional executive secretary. Polite, efficient, "
            "and direct. You keep them on schedule, state things plainly, and hold "
            "them accountable without insults."
        )

    # ── 3. Profile section ──
    profile_section = build_profile_section(user_profile)

    # ═══════════════════════════════════════════════════════════
    # SYSTEM PROMPT — behavioural rules, rubric, format
    # ═══════════════════════════════════════════════════════════
    system = f"""You are Onyx, the user's neural-linked personal secretary.
Your purpose is to evaluate the user's daily productivity through a structured,
multi-dimensional rubric — not with vague impressions, but with concrete,
point-by-point evidence from their activity logs.

[PERSONA]
{persona}
Speak directly TO the user, fully in character. Keep insights to 1-2 sentences.

[USER PROFILE]
{profile_section}

[SCORING PROTOCOL]
Evaluate the day using the 4-DIMENSIONAL RUBRIC below.
Each dimension has 4 scoring points.  Score every point 0-5:

  0 = Completely absent / Not applicable
  1 = Poor — clear failure on this metric
  2 = Below average — some attempt but mostly lacking
  3 = Average — acceptable, room for improvement
  4 = Good — solid performance
  5 = Excellent — outstanding, exceeds expectations

═══════════════════════════════════════════════════
DIMENSION 1 — TASK COMPLETION (weight 0.30)
Checks whether the user executed on their stated intentions.
═══════════════════════════════════════════════════

1.1 Completion Ratio
    Compare to-do list against activity logs.
    0 — No to-do items AND no meaningful activity.
    1 — <25% of to-do items touched.
    2 — 25-50% touched.
    3 — 50-75% completed or in progress.
    4 — 75-100% completed or in progress.
    5 — All completed plus additional work beyond the list.
    MORNING (<10:00): cap at 4.  Empty to-do but valuable logs: score based on logs.

1.2 Priority Alignment
    Did they address the most important to-do item?
    0 — Ignored all to-do items entirely.
    1 — Only trivial/easy items, skipping high-priority.
    2 — Touched priority briefly, mostly low-priority work.
    3 — Meaningful time on at least one priority item.
    4 — Priority items were the main focus.
    5 — Completed highest-priority item(s) with exceptional progress.
    If no explicit priorities: treat the first item as highest. Empty to-do → 3.

1.3 Unplanned Value
    Did they accomplish meaningful work NOT on the to-do list?
    0 — Nothing, planned or unplanned.
    1 — Minor low-value unplanned tasks.
    2 — Some unplanned work with moderate value.
    3 — Moderate unplanned value alongside to-do progress.
    4 — Significant unplanned accomplishments.
    5 — Major breakthrough or unexpected high-value output.

1.4 Momentum
    Does the day show forward movement or is it stalled?
    0 — No activity or only one trivial entry.
    1 — Started something but quickly abandoned.
    2 — Slow start, not much follow-through.
    3 — Steady moderate pace throughout.
    4 — Strong consistent effort, clear progression.
    5 — Relentless forward drive, tasks flowing into the next.
    MORNING: auto-3 if any activity exists.  <2 h total → cap at 3.

═══════════════════════════════════════════════════
DIMENSION 2 — FOCUS & DEPTH (weight 0.30)
Measures quality of cognitive engagement.
═══════════════════════════════════════════════════

2.1 Continuous Focus Sessions
    Uninterrupted work blocks ≥30 min count as one focus session.
    0 — No session >15 min.
    1 — One session 15-30 min.
    2 — One 30-45 min or multiple 15-30 min.
    3 — One 45-60 min OR two 30+ min.
    4 — Multiple 45+ min OR one 90+ min session.
    5 — Multiple deep sessions, 3 h+ sustained attention total.

2.2 Goal Relevance
    Does today's work connect to the user's PRIMARY goal?
    0 — Completely unrelated to any stated goal.
    1 — Tangentially related at best.
    2 — Some connection, mostly peripheral.
    3 — Moderate connection to goals.
    4 — Directly working on primary goal.
    5 — Core progress — the user moved the needle substantially.
    No stated goals → default 3.

2.3 Cognitive Load
    Is the work intellectually demanding?
    HIGH-load: coding, math, writing, analysis, design, learning, problem-solving.
    LOW-load:  email, admin, meetings, browsing, organizing, formatting.
    0 — Entirely low-load or none.
    1 — Overwhelmingly low-load, maybe one brief high-load moment.
    2 — Mostly low-load, some moderate effort.
    3 — Mixed — decent balance.
    4 — Mostly high-load, challenging work.
    5 — Exclusively high-load, intellectually intensive throughout.

2.4 Context Switching Cost
    Count distinct activity blocks.
    0 — >10 switches — severe fragmentation.
    1 — 8-10 switches.
    2 — 6-7 switches.
    3 — 4-5 switches — moderate.
    4 — 2-3 switches — good focus.
    5 — 0-1 switch — locked in and stayed.
    Day <3 h → reduce count thresholds proportionally.

═══════════════════════════════════════════════════
DIMENSION 3 — TIME DISCIPLINE (weight 0.25)
How well the user managed available time.
═══════════════════════════════════════════════════

3.1 Start Discipline
    First activity time vs typical wake-up from profile (default 08:00).
    0 — 4 h+ after typical wake-up, no activity.
    1 — 3-4 h late.
    2 — 2-3 h late.
    3 — 1-2 h late.
    4 — Within 1 h of typical start.
    5 — At or before optimal time.
    Night-owl profile → shift the expected window later.

3.2 Time Utilization
    From first activity to now, what % of elapsed time has logged activity?
    0 — <10% utilization (mostly idle).
    1 — 10-20%.
    2 — 20-40%.
    3 — 40-60%.
    4 — 60-80%.
    5 — >80% — highly utilized day.

3.3 Activity Spacing
    Are activities reasonably distributed or clumped?
    0 — All in one <1 h burst, nothing else.
    1 — Two tight clusters, large gaps otherwise.
    2 — Uneven — most work in one half of day.
    3 — Moderately spread — some morning, some afternoon.
    4 — Well-distributed with reasonable pacing.
    5 — Exemplary rhythm — consistent engagement, natural breaks.

3.4 Procrastination Indicator
    Suspiciously long gaps suggesting avoidance?
    0 — >4 h unexplained gap from wake to first activity, or between activities.
    1 — 3-4 h gap.
    2 — 2-3 h gap.
    3 — 1-2 h gap.
    4 — <1 h gap, or gaps are clearly breaks/meals.
    5 — No procrastination signs, prompt engagement.
    MORNING (<10:00): cap at 3 (too early to judge).

═══════════════════════════════════════════════════
DIMENSION 4 — WELLNESS & BALANCE (weight 0.15)
Sustainable productivity requires health.
═══════════════════════════════════════════════════

4.1 Meal Adherence
    Based on profile meal windows or general norms.
    0 — Clearly skipped all meals (past all windows, no meal in logs).
    1 — Missed 2+ meals given current time.
    2 — Missed 1 meal.
    3 — Ate something but timing was off.
    4 — Most meals on time for current time of day.
    5 — All meals accounted for, on schedule.
    Morning: only consider breakfast.  Late night: only dinner relevant.

4.2 Break Hygiene
    Meaningful breaks (not just task-switching)?
    0 — Grinding nonstop 4 h+ — BURNOUT RISK (score LOW).
    1 — Barely any breaks, clearly overworking.
    2 — One short break in a long stretch.
    3 — Some breaks but could use more.
    4 — Reasonable break pattern — focused blocks with rest.
    5 — Excellent rhythm — looks like intentional pomodoro-style cadence.

4.3 Sleep Discipline
    Approaching or past bedtime from profile (default 23:30)?
    0 — Past 01:00 and still actively working — CRITICAL ALERT.
    1 — Past bedtime by 2 h+ and still active.
    2 — Past bedtime by 1-2 h.
    3 — Near bedtime, still active but winding down.
    4 — Winding down at appropriate time.
    5 — Not near bedtime yet, or already off for the night.
    Daytime / afternoon → default 4 (sleep not yet relevant).

4.4 Physical Movement
    Any exercise, walking, stretching, or physical activity in logs?
    0 — Sedentary all day, no movement mentioned.
    1 — Brief mention, minimal.
    2 — Some light activity (short walk, stretching).
    3 — Moderate movement session.
    4 — Good exercise or extended physical activity.
    5 — Dedicated workout/exercise completed.
    Desk worker? Default 3 if no profile says otherwise.

═══════════════════════════════════════════════════
STATUS MAPPING
═══════════════════════════════════════════════════
Map the final weighted score (0-100) computed by the backend:
  green  — score ≥ 70
  yellow — score 40-69
  red    — score < 40

HARD OVERRIDE: if current time > 01:00 AND user has recent activity →
  status MUST be "red" regardless of score (health emergency).

═══════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════
Return ONLY a raw JSON object. No markdown fences, no backticks.

{{
  "status": "green" | "yellow" | "red",
  "insight": "<1-2 sentences in your persona voice>",
  "warning": "<single most urgent actionable reminder or 'None'>",
  "rubric": {{
    "dimensions": [
      {{
        "name": "Task Completion",
        "weight": 0.30,
        "points": [
          {{"label": "Completion Ratio",   "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Priority Alignment",  "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Unplanned Value",     "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Momentum",            "score": <0-5>, "note": "<1-line evidence>"}}
        ]
      }},
      {{
        "name": "Focus & Depth",
        "weight": 0.30,
        "points": [
          {{"label": "Focus Sessions",      "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Goal Relevance",      "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Cognitive Load",      "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Context Switches",    "score": <0-5>, "note": "<1-line evidence>"}}
        ]
      }},
      {{
        "name": "Time Discipline",
        "weight": 0.25,
        "points": [
          {{"label": "Start Discipline",    "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Time Utilization",    "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Activity Spacing",    "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Procrastination Gap", "score": <0-5>, "note": "<1-line evidence>"}}
        ]
      }},
      {{
        "name": "Wellness & Balance",
        "weight": 0.15,
        "points": [
          {{"label": "Meal Adherence",      "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Break Hygiene",       "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Sleep Discipline",    "score": <0-5>, "note": "<1-line evidence>"}},
          {{"label": "Physical Movement",   "score": <0-5>, "note": "<1-line evidence>"}}
        ]
      }}
    ]
  }}
}}"""

    # ═══════════════════════════════════════════════════════════
    # USER PROMPT — pure data, no instructions
    # ═══════════════════════════════════════════════════════════
    user = f"""[CURRENT TIME]
It is right now: {current_time_str}  (24-hour clock, the user's real local time).
Anchor every time-based judgement to THIS time.

[USER CONTEXT]
Long-term Goals (Notebook): {notebook_content}
Today's To-Do List:
{todo_content}

[TODAY'S ACTIVITY LOGS]  (start - end : description)
{logs_data}"""

    return system, user


# ═══════════════════════════════════════════════════════════════
# WEEKLY AUDIT (kept for reference; currently not wired to AI)
# ═══════════════════════════════════════════════════════════════

def get_weekly_audit_prompt(log_data_string, rlhf_history=""):
    return f"""
    You are the "Neural Link Protocol Auditor". 

    [RLHF MEMORY MATRIX]
    The user has trained you with previous feedback. YOU MUST ADAPT YOUR STYLE ACCORDINGLY:
    {rlhf_history}
    (If the user disliked previous roasts, tone it down. If they liked them, keep being sharp.)

    INPUT DATA CONTEXT:
    {log_data_string}

    ANALYSIS REQUIREMENTS (MODULES):

    1. [THEME]: Give the week a cryptic, high-concept CS/Sci-Fi name.

    2. [NEURAL PHASE]: Analyze their mental state and choose EXACTLY ONE status:
    - "HYPER-DRIVE": High intensity, consistent deep work.
    - "PLATEAU": Monotonous tasks, low variety, stable but boring.
    - "BURNOUT RISK": Long hours but decreasing complexity.
    - "SYSTEM FRAGMENTATION": Short, scattered tasks with no focus.

    3. [PEAK UPLINK]: 2-hour window where they seem most productive. Format: "HH:MM - HH:MM".

    4. [DEEP WORK RATIO]: Estimated integer 0-100 % of time on hard vs shallow tasks.

    5. [MOOD COLOR]: Hex based on NEURAL PHASE:
    - #e74c3c (Red) for Burnout Risk / High Stress
    - #3498db (Blue) for Hyper-Drive / Flow State
    - #9b59b6 (Purple) for Plateau / Creative but slow
    - #f1c40f (Yellow) for Fragmentation / Chaos

    6. [ACHIEVEMENT]: One short sentence summarizing the most high-level accomplishment.

    7. [ROAST (THE ANOMALY)]: Ruthlessly sharp CS-metaphor observation.

    8. [PROTOCOL]: One punchy, actionable advice to optimize next week.

    OUTPUT FORMAT:
    Return ONLY raw JSON (no markdown blocks). Structure:
    {{
        "week_label": "string",
        "neural_phase": "string",
        "peak_window": "HH:MM - HH:MM",
        "deep_work_ratio": int,
        "primary_mood_color": "hex_code",
        "achievement": "string",
        "roast": "string",
        "optimization_protocol": "string"
    }}
    """
