from datetime import datetime

from services.stats import is_deep_work


def calculate_duration_minutes(start_str, end_str):
    """计算两个 HH:MM 时间字符串之间的分钟数"""
    if not start_str or not end_str:
        return 0

    start_str = str(start_str).strip()
    end_str = str(end_str).strip()

    formats = ["%H:%M", "%H:%M:%S"]

    s = None
    for fmt in formats:
        try:
            s = datetime.strptime(start_str, fmt)
            break
        except ValueError:
            continue

    e = None
    for fmt in formats:
        try:
            e = datetime.strptime(end_str, fmt)
            break
        except ValueError:
            continue

    if s is None or e is None:
        print(f"⚠️ PARSE FAILED: start={repr(start_str)}, end={repr(end_str)}")
        return 0

    diff = (e - s).total_seconds() / 60.0
    if diff < 0:
        diff += 24 * 60
    return diff


def build_day_stats(items):
    """接收一天的记录列表，返回聚合统计"""
    total_min = 0.0
    deep_min = 0.0

    for item in items:
        dur = calculate_duration_minutes(item.start_time, item.end_time)
        total_min += dur
        if is_deep_work(item.desc):
            deep_min += dur

    focus_pct = int(deep_min / total_min * 100) if total_min > 0 else 0

    return {
        'total_minutes': total_min,
        'total_hours': f"{total_min / 60:.1f}h",
        'focus_pct': focus_pct,
        'entry_count': len(items),
    }

