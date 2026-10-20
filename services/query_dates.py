"""Calendar filters use local file modification time; end dates are inclusive."""
from datetime import date, datetime, time, timedelta


def time_window(preset, start=None, end=None, *, today=None):
    today = today or date.today()
    if preset == "all":
        return None, None
    if preset == "today":
        start = end = today
    elif preset in {"week", "month30"}:
        start, end = today - timedelta(days=6 if preset == "week" else 29), today
    elif preset == "month":
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif preset != "custom" or start is None or end is None:
        raise ValueError("日期筛选无效")
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    return (int(datetime.combine(start, time.min).timestamp() * 1_000_000_000),
            int(datetime.combine(end + timedelta(days=1), time.min).timestamp() * 1_000_000_000))
