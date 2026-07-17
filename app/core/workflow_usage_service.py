"""视频工作流的模型调用账本与任务级统计。"""


def _usage_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_float(value):
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def build_workflow_llm_telemetry(job, workflow_event_id, stage):
    """生成供 LLM 调用层使用的轻量记录回调。"""
    context = {
        "workflowEventId": workflow_event_id,
        "jobId": (job or {}).get("id") or "",
        "videoId": (job or {}).get("videoId") or "",
        "stage": str(stage or ""),
    }

    def record(payload):
        record_workflow_llm_usage(context, payload)

    return record


def record_workflow_llm_usage(context, payload):
    """账本写入失败不得影响视频处理主链路。"""
    context = context or {}
    payload = payload or {}
    job_id = str(context.get("jobId") or "").strip()
    if not job_id:
        return
    try:
        init_database_tables()
        prompt_tokens = _usage_int(payload.get("promptTokens") or payload.get("prompt_tokens"))
        completion_tokens = _usage_int(payload.get("completionTokens") or payload.get("completion_tokens"))
        total_tokens = _usage_int(payload.get("totalTokens") or payload.get("total_tokens") or payload.get("tokens"))
        if not total_tokens:
            total_tokens = prompt_tokens + completion_tokens
        with _db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO youtube_workflow_llm_usage_events (
                workflow_event_id, job_id, video_id, stage, operation, provider, model,
                status, attempt, prompt_tokens, completion_tokens, total_tokens,
                latency_ms, error_message, error_category, violations, raw_output, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                context.get("workflowEventId") or None,
                job_id,
                str(context.get("videoId") or ""),
                str(context.get("stage") or ""),
                str(payload.get("operation") or ""),
                str(payload.get("provider") or "openai-compatible"),
                str(payload.get("model") or ""),
                str(payload.get("status") or "success"),
                max(1, _usage_int(payload.get("attempt") or 1)),
                prompt_tokens,
                completion_tokens,
                total_tokens,
                _usage_float(payload.get("latencyMs") or payload.get("latency_ms")),
                clean_display_text(str(payload.get("errorMessage") or ""))[:500],
                str(payload.get("errorCategory") or payload.get("error_category") or "")[:80],
                json.dumps(list(payload.get("violations") or []), ensure_ascii=False)[:4000],
                str(payload.get("rawOutput") or payload.get("raw_output") or "")[:20000]
                if str(payload.get("status") or "") in {"contract_failed", "soft_warning"} else "",
                _now_iso(),
            ))
            conn.commit()
    except Exception:
        backend_logger.exception("模型用量账本写入失败 : jobId = %s | stage = %s", job_id, context.get("stage") or "")


def _stats_parse_datetime(value, end_of_day=False):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            parsed = datetime.datetime.fromisoformat(text)
            return parsed + datetime.timedelta(days=1) if end_of_day else parsed
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _stats_range(date_from=None, date_to=None, granularity="auto"):
    now = datetime.datetime.now()
    start = _stats_parse_datetime(date_from) or (now - datetime.timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = _stats_parse_datetime(date_to, end_of_day=True) or (now + datetime.timedelta(seconds=1))
    if end <= start:
        end = start + datetime.timedelta(days=1)
    requested = str(granularity or "auto").lower()
    resolved = requested if requested in {"hour", "day"} else ("hour" if end - start <= datetime.timedelta(hours=48) else "day")
    return start, end, resolved


def _stats_model_name(value):
    return str(value or "").strip() or "未记录模型"


def _stats_usage_values(records, event=None):
    if records:
        model_usage = {}
        for item in records:
            model = _stats_model_name(item.get("model"))
            values = model_usage.setdefault(model, {"model": model, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "requestCount": 0, "latencyTotalMs": 0.0})
            values["promptTokens"] += _usage_int(item.get("prompt_tokens"))
            values["completionTokens"] += _usage_int(item.get("completion_tokens"))
            values["totalTokens"] += _usage_int(item.get("total_tokens"))
            values["requestCount"] += 1
            values["latencyTotalMs"] += _usage_float(item.get("latency_ms"))
        return {
            "promptTokens": sum(_usage_int(item.get("prompt_tokens")) for item in records),
            "completionTokens": sum(_usage_int(item.get("completion_tokens")) for item in records),
            "totalTokens": sum(_usage_int(item.get("total_tokens")) for item in records),
            "requestCount": len(records),
            "latencyTotalMs": sum(_usage_float(item.get("latency_ms")) for item in records),
            "models": sorted(model_usage),
            "modelUsage": list(model_usage.values()),
        }
    if event and (_usage_int(event.get("total_tokens")) or _usage_float(event.get("cloud_latency_ms"))):
        return {
            "promptTokens": _usage_int(event.get("prompt_tokens")),
            "completionTokens": _usage_int(event.get("completion_tokens")),
            "totalTokens": _usage_int(event.get("total_tokens")),
            "requestCount": 1,
            "latencyTotalMs": _usage_float(event.get("cloud_latency_ms")),
            "models": [_stats_model_name(event.get("cloud_model"))],
            "modelUsage": [{
                "model": _stats_model_name(event.get("cloud_model")), "promptTokens": _usage_int(event.get("prompt_tokens")),
                "completionTokens": _usage_int(event.get("completion_tokens")), "totalTokens": _usage_int(event.get("total_tokens")),
                "requestCount": 1, "latencyTotalMs": _usage_float(event.get("cloud_latency_ms")),
            }],
        }
    return {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "requestCount": 0, "latencyTotalMs": 0.0, "models": [], "modelUsage": []}


def _stats_add_usage(target, values):
    for key in ("promptTokens", "completionTokens", "totalTokens", "requestCount", "latencyTotalMs"):
        target[key] = target.get(key, 0) + values.get(key, 0)
    target.setdefault("models", set()).update(values.get("models") or [])


def _stats_event_item(event, records):
    usage = _stats_usage_values(records, event)
    usage_entries = [{
        "model": _stats_model_name(item.get("model")), "promptTokens": _usage_int(item.get("prompt_tokens")),
        "completionTokens": _usage_int(item.get("completion_tokens")), "totalTokens": _usage_int(item.get("total_tokens")),
        "requestCount": 1, "latencyMs": _usage_float(item.get("latency_ms")), "createdAt": item.get("created_at") or event.get("started_at") or "",
    } for item in records]
    if not usage_entries and usage["requestCount"]:
        usage_entries.append({
            "model": _stats_model_name(event.get("cloud_model")), "promptTokens": usage["promptTokens"],
            "completionTokens": usage["completionTokens"], "totalTokens": usage["totalTokens"],
            "requestCount": 1, "latencyMs": usage["latencyTotalMs"], "createdAt": event.get("started_at") or "",
        })
    return {
        "id": event.get("id"),
        "stage": event.get("stage") or "",
        "stageLabel": clean_display_text(event.get("stage_label") or WORKFLOW_STAGE_LABELS.get(event.get("stage"), event.get("stage") or "")),
        "status": event.get("status") or "",
        "message": clean_display_text(event.get("message") or ""),
        "startedAt": event.get("started_at") or "",
        "endedAt": event.get("ended_at") or "",
        "durationSeconds": round(_usage_float(event.get("duration_seconds")), 2),
        "promptTokens": usage["promptTokens"],
        "completionTokens": usage["completionTokens"],
        "totalTokens": usage["totalTokens"],
        "requestCount": usage["requestCount"],
        "avgLatencyMs": round(usage["latencyTotalMs"] / usage["requestCount"], 2) if usage["requestCount"] else 0,
        "models": usage["models"],
        "modelUsage": usage["modelUsage"],
        "_usageEntries": usage_entries,
    }


def _stats_task_duration(events):
    workflow_durations = [_usage_float(item.get("duration_seconds")) for item in events if item.get("stage") == "workflow"]
    if workflow_durations:
        return round(max(workflow_durations), 2)
    timestamps = []
    for item in events:
        for value in (item.get("started_at"), item.get("ended_at")):
            parsed = _stats_parse_datetime(value)
            if parsed:
                timestamps.append(parsed)
    return round(max(0.0, (max(timestamps) - min(timestamps)).total_seconds()), 2) if len(timestamps) > 1 else 0


def _stats_build_task(job, events, usage_records):
    by_event = {}
    for record in usage_records:
        by_event.setdefault(record.get("workflow_event_id"), []).append(record)
    visible_events = [item for item in events if item.get("stage") != "workflow"]
    stages = [_stats_event_item(item, by_event.get(item.get("id"), [])) for item in visible_events]
    totals = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "requestCount": 0, "latencyTotalMs": 0.0, "models": set()}
    for stage in stages:
        _stats_add_usage(totals, stage)
    return {
        "jobId": job.get("id") or "",
        "videoId": job.get("video_id") or "",
        "title": job.get("title") or job.get("video_id") or job.get("id") or "未命名视频",
        "status": job.get("status") or "",
        "startedAt": job.get("started_at") or job.get("created_at") or "",
        "updatedAt": job.get("updated_at") or "",
        "durationSeconds": _stats_task_duration(events),
        "stageCount": len(stages),
        "promptTokens": totals["promptTokens"],
        "completionTokens": totals["completionTokens"],
        "totalTokens": totals["totalTokens"],
        "requestCount": totals["requestCount"],
        "avgLatencyMs": round(totals["latencyTotalMs"] / totals["requestCount"], 2) if totals["requestCount"] else 0,
        "models": sorted(totals["models"]),
        "stages": stages,
    }


def _stats_fetch_task_bundle(job_rows):
    job_ids = [str(item.get("id") or "") for item in job_rows if item.get("id")]
    if not job_ids:
        return []
    placeholders = ",".join("?" for _ in job_ids)
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM youtube_workflow_events WHERE job_id IN ({placeholders}) ORDER BY started_at, id", job_ids)
        events_by_job = {}
        for row in cursor.fetchall():
            events_by_job.setdefault(row["job_id"], []).append(dict(row))
        cursor.execute(f"SELECT * FROM youtube_workflow_llm_usage_events WHERE job_id IN ({placeholders}) ORDER BY created_at, id", job_ids)
        usage_by_job = {}
        for row in cursor.fetchall():
            usage_by_job.setdefault(row["job_id"], []).append(dict(row))
    return [_stats_build_task(job, events_by_job.get(job.get("id"), []), usage_by_job.get(job.get("id"), [])) for job in job_rows]


def _stats_stage_summary(tasks):
    grouped = {}
    for task in tasks:
        for stage in task["stages"]:
            key = (stage["stage"], stage["stageLabel"])
            item = grouped.setdefault(key, {
                "stage": stage["stage"], "stageLabel": stage["stageLabel"], "count": 0, "success": 0, "failed": 0,
                "durationSeconds": 0.0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0,
                "requestCount": 0, "latencyTotalMs": 0.0,
            })
            item["count"] += 1
            item["success"] += int(stage["status"] == "success")
            item["failed"] += int(stage["status"] == "failed")
            item["durationSeconds"] += stage["durationSeconds"]
            for field in ("promptTokens", "completionTokens", "totalTokens", "requestCount"):
                item[field] += stage[field]
            item["latencyTotalMs"] += stage["avgLatencyMs"] * stage["requestCount"]
    values = []
    for item in grouped.values():
        item["durationSeconds"] = round(item["durationSeconds"], 2)
        item["avgDurationSeconds"] = round(item["durationSeconds"] / item["count"], 2) if item["count"] else 0
        item["avgCloudLatencyMs"] = round(item["latencyTotalMs"] / item["requestCount"], 2) if item["requestCount"] else 0
        item.pop("latencyTotalMs", None)
        values.append(item)
    return sorted(values, key=lambda item: item["durationSeconds"], reverse=True)


def _stats_model_and_trend(tasks, start, granularity):
    models = {}
    trend = {}
    for task in tasks:
        for stage in task["stages"]:
            for entry in stage.get("_usageEntries") or []:
                entry_time = _stats_parse_datetime(entry["createdAt"]) or _stats_parse_datetime(stage["startedAt"]) or start
                bucket = entry_time.strftime("%m-%d %H:00") if granularity == "hour" else entry_time.strftime("%m-%d")
                trend_item = trend.setdefault(bucket, {"bucket": bucket, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "requestCount": 0})
                for field in ("promptTokens", "completionTokens", "totalTokens", "requestCount"):
                    trend_item[field] += entry[field]
                model = entry["model"]
                model_item = models.setdefault(model, {"model": model, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "requestCount": 0, "latencyTotalMs": 0.0})
                for field in ("promptTokens", "completionTokens", "totalTokens", "requestCount"):
                    model_item[field] += entry[field]
                model_item["latencyTotalMs"] += entry["latencyMs"]
    model_rows = []
    for item in models.values():
        item["avgLatencyMs"] = round(item.pop("latencyTotalMs") / item["requestCount"], 2) if item["requestCount"] else 0
        model_rows.append(item)
    return sorted(trend.values(), key=lambda item: item["bucket"]), sorted(model_rows, key=lambda item: item["totalTokens"], reverse=True)


def _stats_strip_internal(tasks):
    for task in tasks:
        for stage in task.get("stages") or []:
            stage.pop("_usageEntries", None)


def _stats_task_rows(start, end, page, page_size=None):
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        where = "COALESCE(NULLIF(started_at, ''), created_at) >= ? AND COALESCE(NULLIF(started_at, ''), created_at) < ?"
        params = (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
        cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_workflow_jobs WHERE {where}", params)
        total = int(cursor.fetchone()["total"] or 0)
        page_size = total if page_size is None else page_size
        cursor.execute(f'''SELECT * FROM youtube_workflow_jobs WHERE {where}
            ORDER BY COALESCE(NULLIF(started_at, ''), created_at) DESC, id DESC LIMIT ? OFFSET ?''', (*params, page_size, (page - 1) * page_size))
        rows = [dict(item) for item in cursor.fetchall()]
    return _stats_fetch_task_bundle(rows), total


def get_workflow_task_statistics(job_id):
    init_youtube_workflow_table()
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    tasks = _stats_fetch_task_bundle([dict(row)])
    task = tasks[0] if tasks else None
    if not task:
        return None
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM youtube_workflow_llm_usage_events WHERE job_id = ? ORDER BY created_at DESC, id DESC", (job_id,)).fetchall()
    task["requests"] = [{
        "id": item["id"], "workflowEventId": item["workflow_event_id"], "stage": item["stage"] or "",
        "stageLabel": WORKFLOW_STAGE_LABELS.get(item["stage"], item["stage"] or ""), "operation": item["operation"] or "",
        "model": _stats_model_name(item["model"]), "status": item["status"] or "", "attempt": _usage_int(item["attempt"]),
        "promptTokens": _usage_int(item["prompt_tokens"]), "completionTokens": _usage_int(item["completion_tokens"]),
        "totalTokens": _usage_int(item["total_tokens"]), "latencyMs": _usage_float(item["latency_ms"]),
        "errorMessage": clean_display_text(item["error_message"] or ""), "createdAt": item["created_at"] or "",
    } for item in rows]
    _stats_strip_internal([task])
    return task


def get_workflow_statistics(limit=200, page=1, page_size=None, date_from=None, date_to=None, granularity="auto"):
    init_youtube_workflow_table()
    page_size = _parse_positive_int(page_size or limit, limit, 1, 100)
    page = _parse_positive_int(page, 1, 1, 100000)
    start, end, resolved_granularity = _stats_range(date_from, date_to, granularity)
    all_tasks, task_total = _stats_task_rows(start, end, 1)
    offset = (page - 1) * page_size
    tasks = all_tasks[offset:offset + page_size]
    stages = _stats_stage_summary(all_tasks)
    trend, models = _stats_model_and_trend(all_tasks, start, resolved_granularity)
    summary = {"eventCount": sum(item["stageCount"] for item in all_tasks), "jobCount": task_total, "totalDurationSeconds": round(sum(item["durationSeconds"] for item in all_tasks), 2), "promptTokens": sum(item["promptTokens"] for item in all_tasks), "completionTokens": sum(item["completionTokens"] for item in all_tasks), "totalTokens": sum(item["totalTokens"] for item in all_tasks), "cloudCallCount": sum(item["requestCount"] for item in all_tasks)}
    summary["avgDurationSeconds"] = round(summary["totalDurationSeconds"] / len(all_tasks), 2) if all_tasks else 0
    latency_total = sum(item["avgLatencyMs"] * item["requestCount"] for item in all_tasks)
    summary["avgCloudLatencyMs"] = round(latency_total / summary["cloudCallCount"], 2) if summary["cloudCallCount"] else 0
    _stats_strip_internal(all_tasks)
    legacy_events = list_workflow_events(limit, page=page, page_size=page_size)
    return {
        "summary": summary, "stages": stages, "trend": trend, "models": models,
        "tasks": tasks, "tasksTotal": task_total, "tasksPage": page, "tasksPageSize": page_size,
        "range": {"dateFrom": start.isoformat(timespec="seconds"), "dateTo": end.isoformat(timespec="seconds"), "granularity": resolved_granularity},
        "events": legacy_events["items"], "eventsTotal": legacy_events["total"], "eventsPage": legacy_events["page"], "eventsPageSize": legacy_events["pageSize"],
        "jobs": tasks,
    }
