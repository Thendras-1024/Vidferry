"""任务中心展示数据转换。"""


def _task_publish_status(publish_progress, fallback):
    if not publish_progress:
        return fallback
    status = _task_status(publish_progress.get("status"))
    return {
        "queued": "waiting_publish", "running": "running", "waiting_existing": "waiting_publish",
        "confirmed": "success", "reused": "reused", "partial": "partial",
        "uncertain": "needs_verification", "failed": "failed", "cancelled": "cancelled",
    }.get(status, fallback)


def _task_publish_retry_data(job, materials):
    task_id = f"workflow:{job.get('id')}"
    records = [item for item in materials if str(item.get("publish_task_id") or "") == task_id]
    retry_records = [item for item in records if str(item.get("status") or "") in {"failed", "timeout"}]
    has_blocking_status = any(str(item.get("status") or "") in {"queued", "running", "uncertain", "cancelled"} for item in records)
    can_retry = bool(retry_records) and not has_blocking_status and not any(item.get("retry_source") for item in records)
    return {
        "publishTaskId": task_id if retry_records else "",
        "canRetry": can_retry,
        "retryTargets": [
            {
                "id": item.get("id"), "platform": platform_name(int(item.get("platform_type") or 0)),
                "accountName": item.get("account_name") or "", "accountFile": item.get("account_file") or "",
                "message": item.get("message") or "", "updatedAt": _task_iso(item.get("updated_at") or item.get("published_at")),
            }
            for item in retry_records
        ],
    }


def _task_item(job, events, materials, acknowledged_at=""):
    job_status = _task_status(job.get("status"))
    task_key = f"workflow:{job.get('id')}"
    download_only = _task_only_download(job, events)
    stage_events = [event for event in events if event["stage"] != "workflow"]
    latest = next((event for event in reversed(stage_events) if event["status"] == "running"), None) or (stage_events[-1] if stage_events else None)
    warning_events = [event for event in stage_events if _task_has_fallback(event, False)[0]]
    completion_at = _task_datetime(job.get("updated_at")) or _task_datetime(job.get("created_at"))
    has_publish_event = any(event["stage"] == "publish" for event in events)
    is_publish = has_publish_event or str(job.get("step") or "") in {"publish", "publish_confirmation"}
    publish_progress = job.get("publishProgress") if isinstance(job.get("publishProgress"), dict) else {}
    task_status = _task_publish_status(publish_progress, job_status) if is_publish else job_status
    if task_status in {"success", "reused"}:
        completion_at = _task_datetime(publish_progress.get("finishedAt") or publish_progress.get("updatedAt")) or completion_at
    expires_at = completion_at + datetime.timedelta(hours=_TASK_SUCCESS_RETENTION_HOURS) if task_status in {"success", "reused"} and completion_at else None
    current_stage = latest.get("label") if latest else _TASK_STAGE_LABELS.get(job.get("step"), job.get("step") or "等待开始")
    progress_value = round(float(job.get("progress") or 0), 1)
    message = str(job.get("message") or (latest.get("message") if latest else ""))
    if publish_progress and is_publish:
        completed = int(publish_progress.get("completed") or 0)
        total = int(publish_progress.get("total") or 0)
        stage_label = {
            "waiting_publish": "发布排队中", "running": "发布中", "success": "发布完成", "reused": "发布完成",
            "partial": "部分发布完成", "needs_verification": "发布待核验", "failed": "发布失败", "cancelled": "发布已取消",
        }.get(task_status, "发布")
        current_stage = f"{stage_label} {completed} / {total}" if total else stage_label
        message = str(publish_progress.get("message") or message)
        if total:
            progress_value = max(progress_value, round(97 + (min(completed, total) / total) * 3, 1))
    error_reason = str(job.get("error_reason") or job.get("error_detail") or (latest.get("message") if latest and latest["status"] in {"failed", "abnormal"} else ""))
    if not error_reason and task_status in {"partial", "needs_verification", "failed", "abnormal"}:
        error_reason = message
    scope = "download" if download_only else "publish" if is_publish else "processing"
    chinese_title = job.get("_task_chinese_title") or ""
    english_title = job.get("title") or job.get("video_id") or "未命名视频"
    return {
        "taskKey": task_key, "jobId": job.get("id"), "videoId": job.get("video_id") or "", "title": english_title,
        "englishTitle": english_title, "chineseTitle": chinese_title, "type": scope, "typeLabel": _task_type_label(scope, job, events), "scope": scope,
        "status": task_status, "statusLabel": _task_status_label(task_status), "progress": progress_value,
        "currentStage": current_stage, "currentStageKey": latest.get("stage") if latest else job.get("step") or "workflow",
        "message": message, "errorReason": error_reason,
        "warningSummary": warning_events[0].get("message") if warning_events else "", "hasWarning": bool(warning_events),
        "startedAt": _task_iso(job.get("started_at") or job.get("created_at")), "updatedAt": _task_iso(job.get("updated_at") or job.get("created_at")),
        "finishedAt": _task_iso(completion_at) if task_status in _TASK_TERMINAL_STATUSES else "", "expiresAt": _task_iso(expires_at),
        "acknowledged": bool(acknowledged_at), "acknowledgedAt": acknowledged_at,
        "ownerUserId": job.get("owner_user_id"), "ownerDisplayName": job.get("_task_owner_display_name") or "",
        "publishProgress": publish_progress, **_task_publish_retry_data(job, materials),
    }
