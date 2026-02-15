import datetime

def get_audit_prompt(notebook, quick_note, logs_data, tone="strict"):
    """
    构造全能审计 Prompt。
    :param notebook: 长期笔记
    :param quick_note: 短期/今日笔记
    :param logs_data: 今日的时间日志列表
    :param tone: "strict" (严厉), "roast" (毒舌), "gentle" (温柔)
    """
    
    # --- 1. 数据预处理 (Data Fusion) ---
    # 如果用户没写，给一个默认值，防止 Prompt 看起来很空
    notebook_content = notebook if notebook and notebook.strip() else "No long-term goals set."
    quick_note_content = quick_note if quick_note and quick_note.strip() else "No specific daily tasks."
    
    # 获取当前时间，帮助 AI 判断是否熬夜
    current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- 2. 语气设定 (Tone Configuration) ---
    if tone == "roast":
        persona = "You are a sarcastic, roasting AI. Mock the user for bad habits funny but painfully true."
    elif tone == "gentle":
        persona = "You are a supportive life coach. Be encouraging and focus on mental health."
    else:  # Default to 'strict'
        persona = "You are a ruthless Productivity Auditor. Logic only. No excuses. High standards."

    # --- 3. 核心 Prompt (The Master Prompt) ---
    return f"""
    [ROLE DEFINITION]
    {persona}
    Current Time: {current_time_str}

    [DATA STREAM - USER CONTEXT]
    Long-term Goals (Notebook): {notebook_content}
    Today's Tasks (Quick Note): {quick_note_content}

    [DATA STREAM - ACTIVITY LOGS]
    {logs_data}

    [EVALUATION PROTOCOL]
    Analyze the user's day based on 3 dimensions:
    1. **Alignment:** Did they do what they planned in Notebook/Quick Note?
       - *FALLBACK RULE:* If User Context is empty or nonsense, judge based on "General High-Performance Standards" (Deep work vs. Cheap dopamine).
    2. **Efficiency:** Look for fragmentation, multitasking, or long idle gaps.
    3. **Health & Biology:** - Check for late-night grinding (sleep deprivation).
       - Check for skipped meals (long gaps without 'Lunch'/'Dinner').
       - Check for sedentary behavior (4+ hours without break).

    [DECISION LOGIC FOR 'STATUS']
    - GREEN: High alignment, healthy routine, strong focus.
    - YELLOW: Moderate alignment OR minor health issues (e.g., skipped lunch).
    - RED: Zero alignment, severe procrastination, OR severe health risk (e.g., staying up past 2 AM, 12h gaming).

    [OUTPUT FORMAT]
    Return ONLY a raw JSON object (no markdown, no ```json tags).
    Keys required:
    - "score": (0-100 integer. Deduct points heavily for health violations).
    - "status": ("green", "yellow", or "red").
    - "insight": (Max 15 words. Sharp, specific comment on their biggest win or fail).
    - "warning": (String. Specific health/habit warning like "Go to sleep", "Eat dinner", or "None").
    """