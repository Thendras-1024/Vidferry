"""时间格式化与时长辅助函数。"""

import datetime


def _format_publish_schedule(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _build_publish_datetimes(file_count, enable_timer=False, videos_per_day=1, daily_times=None, start_days=0):
    if not enable_timer:
        return [0 for _ in range(file_count)]
    from utils.files_times import generate_schedule_time_next_day

    normalized_daily_times = []
    for item in daily_times or []:
        if isinstance(item, str) and ":" in item:
            normalized_daily_times.append(int(item.split(":", 1)[0]))
        else:
            normalized_daily_times.append(int(item))
    return generate_schedule_time_next_day(file_count, videos_per_day, normalized_daily_times, start_days=start_days)


def _parse_publish_schedule(value):
    value = str(value or "").strip()
    if not value:
        return 0
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return value
