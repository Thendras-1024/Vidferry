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
        "ownerUserId": (job or {}).get("ownerUserId"),
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
                owner_user_id, workflow_event_id, job_id, video_id, stage, operation, provider, model,
                status, attempt, prompt_tokens, completion_tokens, total_tokens,
                latency_ms, error_message, error_category, violations, raw_output, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                context.get("ownerUserId"),
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
                "",
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
    placeholders = ",".join("%s" for _ in job_ids)
    with _db_connect() as conn:
        conn.row_factory = True
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


def _stats_task_page(start, end, page, page_size, owner_user_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        where = "owner_user_id = %s AND COALESCE(started_at, created_at) >= %s AND COALESCE(started_at, created_at) < %s"
        params = (owner_user_id, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
        cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_workflow_jobs WHERE {where}", params)
        total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(f'''SELECT * FROM youtube_workflow_jobs WHERE {where}
            ORDER BY COALESCE(started_at, created_at) DESC, id DESC LIMIT %s OFFSET %s''', (*params, page_size, (page - 1) * page_size))
        rows = [dict(item) for item in cursor.fetchall()]
    return _stats_fetch_task_bundle(rows), total


def _stats_aggregates(start, end, granularity, owner_user_id):
    where = "j.owner_user_id = %s AND COALESCE(j.started_at, j.created_at) >= %s AND COALESCE(j.started_at, j.created_at) < %s"
    params = (owner_user_id, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))
    bucket = "MM-DD HH24:00" if granularity == "hour" else "MM-DD"
    usage_cte = '''WITH all_usage AS (
            SELECT job_id, created_at, model, prompt_tokens, completion_tokens, total_tokens, latency_ms
            FROM youtube_workflow_llm_usage_events
            UNION ALL
            SELECT e.job_id, e.started_at, e.cloud_model, e.prompt_tokens, e.completion_tokens,
                e.total_tokens, e.cloud_latency_ms
            FROM youtube_workflow_events e
            WHERE (e.total_tokens > 0 OR e.cloud_latency_ms > 0)
              AND NOT EXISTS (
                  SELECT 1 FROM youtube_workflow_llm_usage_events u
                  WHERE u.workflow_event_id = e.id
              )
        )'''
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(f'''WITH scoped_jobs AS (
                SELECT id FROM youtube_workflow_jobs j WHERE {where}
            ), task_durations AS (
                SELECT j.id, COALESCE(
                    MAX(CASE WHEN e.stage = 'workflow' THEN e.duration_seconds END),
                    EXTRACT(EPOCH FROM (
                        MAX(e.ended_at) - MIN(e.started_at)
                    )),
                    0
                ) AS duration_seconds
                FROM scoped_jobs j
                LEFT JOIN youtube_workflow_events e ON e.job_id = j.id
                GROUP BY j.id
            )
            SELECT COUNT(*) AS job_count, COALESCE(SUM(GREATEST(0.0, duration_seconds)), 0) AS duration_seconds
            FROM task_durations''', params)
        jobs = cursor.fetchone()
        cursor.execute(f'''SELECT COUNT(*) AS event_count
            FROM youtube_workflow_events e JOIN youtube_workflow_jobs j ON j.id = e.job_id
            WHERE {where} AND e.stage != 'workflow' ''', params)
        event_count = int(cursor.fetchone()["event_count"] or 0)
        cursor.execute(f'''{usage_cte}
            SELECT COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens, COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
            COUNT(*) AS request_count, COALESCE(SUM(u.latency_ms), 0) AS latency_total
            FROM all_usage u JOIN youtube_workflow_jobs j ON j.id = u.job_id WHERE {where}''', params)
        usage = cursor.fetchone()
        cursor.execute(f'''WITH usage_by_event AS (
                SELECT workflow_event_id, SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens, SUM(total_tokens) AS total_tokens,
                    COUNT(*) AS request_count, SUM(latency_ms) AS latency_total
                FROM youtube_workflow_llm_usage_events
                WHERE workflow_event_id IS NOT NULL
                GROUP BY workflow_event_id
            )
            SELECT e.stage, COALESCE(e.stage_label, e.stage) AS stage_label, COUNT(*) AS count,
            COUNT(*) FILTER (WHERE e.status = 'success') AS success,
            COUNT(*) FILTER (WHERE e.status = 'failed') AS failed,
            COALESCE(SUM(e.duration_seconds), 0) AS duration_seconds,
            COALESCE(SUM(COALESCE(u.prompt_tokens, CASE WHEN e.total_tokens > 0 OR e.cloud_latency_ms > 0 THEN e.prompt_tokens ELSE 0 END)), 0) AS prompt_tokens,
            COALESCE(SUM(COALESCE(u.completion_tokens, CASE WHEN e.total_tokens > 0 OR e.cloud_latency_ms > 0 THEN e.completion_tokens ELSE 0 END)), 0) AS completion_tokens,
            COALESCE(SUM(COALESCE(u.total_tokens, CASE WHEN e.total_tokens > 0 OR e.cloud_latency_ms > 0 THEN e.total_tokens ELSE 0 END)), 0) AS total_tokens,
            COALESCE(SUM(COALESCE(u.request_count, CASE WHEN e.total_tokens > 0 OR e.cloud_latency_ms > 0 THEN 1 ELSE 0 END)), 0) AS request_count,
            COALESCE(SUM(COALESCE(u.latency_total, CASE WHEN e.total_tokens > 0 OR e.cloud_latency_ms > 0 THEN e.cloud_latency_ms ELSE 0 END)), 0) AS latency_total
            FROM youtube_workflow_events e JOIN youtube_workflow_jobs j ON j.id = e.job_id
            LEFT JOIN usage_by_event u ON u.workflow_event_id = e.id
            WHERE {where} AND e.stage != 'workflow' GROUP BY e.stage, COALESCE(e.stage_label, e.stage)
            ORDER BY duration_seconds DESC''', params)
        stages = [{"stage": row["stage"] or "", "stageLabel": clean_display_text(row["stage_label"] or row["stage"] or ""),
                   "count": int(row["count"] or 0), "success": int(row["success"] or 0), "failed": int(row["failed"] or 0),
                   "durationSeconds": round(_usage_float(row["duration_seconds"]), 2),
                   "avgDurationSeconds": round(_usage_float(row["duration_seconds"]) / int(row["count"] or 1), 2),
                   "promptTokens": _usage_int(row["prompt_tokens"]), "completionTokens": _usage_int(row["completion_tokens"]),
                   "totalTokens": _usage_int(row["total_tokens"]), "requestCount": _usage_int(row["request_count"]),
                   "avgCloudLatencyMs": round(_usage_float(row["latency_total"]) / _usage_int(row["request_count"]), 2) if _usage_int(row["request_count"]) else 0} for row in cursor.fetchall()]
        cursor.execute(f'''{usage_cte}
            SELECT to_char(u.created_at, %s) AS bucket, COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens, COALESCE(SUM(u.total_tokens), 0) AS total_tokens, COUNT(*) AS request_count
            FROM all_usage u JOIN youtube_workflow_jobs j ON j.id = u.job_id
            WHERE {where} GROUP BY bucket ORDER BY bucket''', (bucket, *params))
        trend = [{"bucket": row["bucket"], "promptTokens": int(row["prompt_tokens"] or 0), "completionTokens": int(row["completion_tokens"] or 0), "totalTokens": int(row["total_tokens"] or 0), "requestCount": int(row["request_count"] or 0)} for row in cursor.fetchall()]
        cursor.execute(f'''{usage_cte}
            SELECT COALESCE(NULLIF(u.model, ''), '未记录模型') AS model, COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens, COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
            COUNT(*) AS request_count, COALESCE(SUM(u.latency_ms), 0) AS latency_total
            FROM all_usage u JOIN youtube_workflow_jobs j ON j.id = u.job_id
            WHERE {where} GROUP BY model ORDER BY total_tokens DESC''', params)
        models = [{"model": row["model"], "promptTokens": int(row["prompt_tokens"] or 0), "completionTokens": int(row["completion_tokens"] or 0),
                   "totalTokens": int(row["total_tokens"] or 0), "requestCount": int(row["request_count"] or 0),
                   "avgLatencyMs": round(_usage_float(row["latency_total"]) / int(row["request_count"] or 1), 2)} for row in cursor.fetchall()]
    request_count = int(usage["request_count"] or 0)
    return {
        "summary": {"eventCount": event_count, "jobCount": int(jobs["job_count"] or 0), "totalDurationSeconds": round(_usage_float(jobs["duration_seconds"]), 2),
                    "promptTokens": int(usage["prompt_tokens"] or 0), "completionTokens": int(usage["completion_tokens"] or 0), "totalTokens": int(usage["total_tokens"] or 0),
                    "cloudCallCount": request_count, "avgDurationSeconds": round(_usage_float(jobs["duration_seconds"]) / int(jobs["job_count"] or 1), 2) if jobs["job_count"] else 0,
                    "avgCloudLatencyMs": round(_usage_float(usage["latency_total"]) / request_count, 2) if request_count else 0},
        "stages": stages, "trend": trend, "models": models,
    }


def get_workflow_task_statistics(job_id, owner_user_id):
    init_youtube_workflow_table()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute(
            "SELECT * FROM youtube_workflow_jobs WHERE id = %s AND owner_user_id = %s",
            (job_id, owner_user_id),
        ).fetchone()
    if not row:
        return None
    tasks = _stats_fetch_task_bundle([dict(row)])
    task = tasks[0] if tasks else None
    if not task:
        return None
    with _db_connect() as conn:
        conn.row_factory = True
        rows = conn.execute("SELECT * FROM youtube_workflow_llm_usage_events WHERE job_id = %s AND owner_user_id = %s ORDER BY created_at DESC, id DESC", (job_id, owner_user_id)).fetchall()
    task["requests"] = [{
        "id": item["id"], "workflowEventId": item["workflow_event_id"], "stage": item["stage"] or "",
        "stageLabel": WORKFLOW_STAGE_LABELS.get(item["stage"], item["stage"] or ""), "operation": item["operation"] or "",
        "model": _stats_model_name(item["model"]), "status": item["status"] or "", "attempt": _usage_int(item["attempt"]),
        "promptTokens": _usage_int(item["prompt_tokens"]), "completionTokens": _usage_int(item["completion_tokens"]),
        "totalTokens": _usage_int(item["total_tokens"]), "latencyMs": _usage_float(item["latency_ms"]),
        "errorMessage": clean_display_text(item["error_message"] or ""), "createdAt": item["created_at"] or "",
    } for item in rows]
    return task


def get_workflow_statistics(limit=200, page=1, page_size=None, date_from=None, date_to=None, granularity="auto", owner_user_id=None):
    init_youtube_workflow_table()
    page_size = _parse_positive_int(page_size or limit, limit, 1, 100)
    page = _parse_positive_int(page, 1, 1, 100000)
    start, end, resolved_granularity = _stats_range(date_from, date_to, granularity)
    tasks, task_total = _stats_task_page(start, end, page, page_size, owner_user_id)
    aggregates = _stats_aggregates(start, end, resolved_granularity, owner_user_id)
    legacy_events = list_workflow_events(limit, page=page, page_size=page_size, owner_user_id=owner_user_id)
    return {
        **aggregates,
        "tasks": tasks, "tasksTotal": task_total, "tasksPage": page, "tasksPageSize": page_size,
        "range": {"dateFrom": start.isoformat(timespec="seconds"), "dateTo": end.isoformat(timespec="seconds"), "granularity": resolved_granularity},
        "events": legacy_events["items"], "eventsTotal": legacy_events["total"], "eventsPage": legacy_events["page"], "eventsPageSize": legacy_events["pageSize"],
        "jobs": tasks,
    }
