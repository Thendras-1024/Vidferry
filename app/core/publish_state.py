"""发布目标状态、批次聚合和展示文案。"""

PUBLISH_TARGET_STATUSES = {
    "queued", "running", "confirmed", "failed", "uncertain", "cancelled",
    "reused", "waiting_existing",
}
PUBLISH_ACTIVE_TARGET_STATUSES = {"queued", "running", "waiting_existing"}
PUBLISH_TERMINAL_TARGET_STATUSES = PUBLISH_TARGET_STATUSES - PUBLISH_ACTIVE_TARGET_STATUSES
PUBLISH_CONFIRMED_TARGET_STATUSES = {"confirmed", "reused"}


def aggregate_publish_status(targets):
    statuses = [str(item.get("status") or "failed") for item in targets or []]
    if not statuses:
        return "failed"
    if "running" in statuses:
        return "running"
    if "queued" in statuses:
        return "queued"
    if "waiting_existing" in statuses:
        return "waiting_existing"
    if "uncertain" in statuses:
        return "uncertain"
    confirmed = sum(status in PUBLISH_CONFIRMED_TARGET_STATUSES for status in statuses)
    failed = sum(status in {"failed", "cancelled"} for status in statuses)
    if confirmed and failed:
        return "partial"
    if confirmed == len(statuses):
        return "reused" if all(status == "reused" for status in statuses) else "confirmed"
    return "failed"


def publish_progress(targets):
    counts = {status: 0 for status in PUBLISH_TARGET_STATUSES}
    for target in targets or []:
        status = str(target.get("status") or "queued")
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    completed = sum(counts[status] for status in PUBLISH_TERMINAL_TARGET_STATUSES)
    return {
        "total": total,
        **counts,
        "completed": completed,
        "percentage": round(completed * 100 / total) if total else 0,
    }


def publish_status_label(status):
    return {
        "queued": "待发布",
        "running": "发布中",
        "confirmed": "已确认发布",
        "failed": "发布失败",
        "uncertain": "待核验",
        "cancelled": "已取消",
        "reused": "复用已发布结果",
        "waiting_existing": "等待已有发布任务",
        "partial": "部分完成",
    }.get(str(status or ""), str(status or "未知"))


def workflow_status_from_dispatch(status):
    return {
        "confirmed": ("success", "done"),
        "reused": ("reused", "done"),
        "partial": ("partial", "publish"),
        "uncertain": ("needs_verification", "publish"),
        "waiting_existing": ("waiting_publish", "publish"),
        "failed": ("failed", "publish"),
        "cancelled": ("cancelled", "publish"),
    }.get(str(status or ""), ("waiting_publish", "publish"))
