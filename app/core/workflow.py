def _row_to_workflow_job(row):
    item = dict(row)
    return {
        "id": item.get("id"),
        "videoId": item.get("video_id") or "",
        "url": item.get("url") or "",
        "account": item.get("account") or "",
        "channel": item.get("channel") or "",
        "subscribers": _format_subscribers_w(item.get("subscribers")),
        "publishedAt": item.get("published_at") or "",
        "bilibiliAccount": item.get("bilibili_account") or "",
        "bilibiliTid": normalize_bilibili_tid(item.get("bilibili_tid")),
        "publishToDouyin": int(item.get("publish_to_douyin") if item.get("publish_to_douyin") is not None else 1),
        "publishToBilibili": int(item.get("publish_to_bilibili") or 0),
        "processVersion": _normalize_process_version(item.get("process_version")),
        "subtitleLanguage": _normalize_subtitle_language(item.get("subtitle_language")),
        "burnProfile": _normalize_burn_profile(item.get("burn_profile")),
        "subtitleSize": _normalize_subtitle_size(item.get("subtitle_size")),
        "translatorLabel": _normalize_translator_label(item.get("translator_label")),
        "title": item.get("title") or "",
        "description": item.get("description") or "",
        "tags": json.loads(item.get("tags") or "[]"),
        "schedule": item.get("schedule") or "",
        "status": item.get("status") or "",
        "step": item.get("step") or "",
        "message": item.get("message") or "",
        "sourceFilePath": item.get("source_file_path") or "",
        "processedFilePath": item.get("processed_file_path") or "",
        "publishCommand": item.get("publish_command") or "",
        "progress": round(float(item.get("progress") or 0), 1),
        "speed": item.get("speed") or "",
        "eta": item.get("eta") or "",
        "errorCode": item.get("error_code") or "",
        "errorType": item.get("error_type") or "",
        "errorReason": item.get("error_reason") or "",
        "errorDetail": item.get("error_detail") or "",
        "interruptedAt": item.get("interrupted_at") or "",
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def _normalize_subtitle_language(value):
    language = str(value or DEFAULT_SUBTITLE_LANGUAGE).strip()
    return language if language in SUBTITLE_LANGUAGES else DEFAULT_SUBTITLE_LANGUAGE


def _subtitle_language_meta(value):
    language = _normalize_subtitle_language(value)
    return language, SUBTITLE_LANGUAGES[language]


def _infer_subtitle_language_from_filename(filename):
    stem = Path(str(filename or "")).stem.lower()
    suffix_map = {
        "zh": "zh-CN",
        "en": "en",
        "ja": "ja",
        "ko": "ko",
        "es": "es",
        "fr": "fr",
        "de": "de",
        "ru": "ru",
    }
    for suffix, language in suffix_map.items():
        if stem.endswith(f"_{suffix}"):
            return language
    return ""


def _youtube_thumbnail_url(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return ""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _normalize_burn_profile(value):
    profile = str(value or DEFAULT_BURN_PROFILE).strip()
    return profile if profile in BURN_PROFILES else DEFAULT_BURN_PROFILE


def _burn_profile_config(value):
    profile = _normalize_burn_profile(value)
    return profile, BURN_PROFILES[profile]


def _normalize_subtitle_size(value):
    size = str(value or DEFAULT_SUBTITLE_SIZE).strip()
    return size if size in SUBTITLE_SIZE_PRESETS else DEFAULT_SUBTITLE_SIZE


def _subtitle_size_config(value):
    size = _normalize_subtitle_size(value)
    return size, SUBTITLE_SIZE_PRESETS[size]


def _normalize_translator_label(value):
    label = str(value or "").strip()
    return label[:32] if label else DEFAULT_TRANSLATOR_LABEL


def _normalize_process_version(value):
    process_version = str(value or PROCESS_VERSION_TRANSLATION).strip()
    return process_version if process_version in PROCESS_VERSIONS else PROCESS_VERSION_TRANSLATION


def create_youtube_workflow_job(payload):
    init_youtube_workflow_table()
    job_id = str(uuid.uuid4())
    subtitle_language = _normalize_subtitle_language(payload.get("subtitleLanguage"))
    burn_profile = _normalize_burn_profile(payload.get("burnProfile"))
    subtitle_size = _normalize_subtitle_size(payload.get("subtitleSize"))
    translator_label = _normalize_translator_label(payload.get("translatorLabel"))
    process_version = _normalize_process_version(payload.get("processVersion"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_jobs (
            id, video_id, url, account, channel, subscribers, published_at,
            bilibili_account, bilibili_tid, publish_to_douyin, publish_to_bilibili,
            process_version, subtitle_language, burn_profile, subtitle_size, translator_label,
            title, description, tags, schedule, status, step, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id,
            payload.get("videoId") or "",
            payload["url"],
            payload.get("account") or "",
            payload.get("channel") or "",
            _format_subscribers_w(payload.get("subscribers")),
            payload.get("publishedAt") or "",
            payload.get("bilibiliAccount") or "",
            normalize_bilibili_tid(payload.get("bilibiliTid")),
            int(1 if payload.get("publishToDouyin", True) else 0),
            int(1 if payload.get("publishToBilibili") else 0),
            process_version,
            subtitle_language,
            burn_profile,
            subtitle_size,
            translator_label,
            payload.get("title") or "",
            payload.get("description") or "",
            json.dumps(tags, ensure_ascii=False),
            payload.get("schedule") or "",
            "queued",
            "queued",
            "任务已创建，等待后台执行",
        ))
        conn.commit()
    return get_youtube_workflow_job(job_id)


def get_youtube_workflow_job(job_id):
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        return _row_to_workflow_job(row)


def _workflow_status_clause(status):
    if status == "running":
        return "status IN ('queued', 'running')", []
    if status == "recent":
        return "", []
    if status in {"success", "failed", "abnormal"}:
        return "status = ?", [status]
    return "", []


def list_youtube_workflow_jobs(limit=50, params=None):
    init_youtube_workflow_table()
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize") or params.get("limit"), limit, 1, 100)
    offset = (page - 1) * page_size
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        where = []
        values = []
        status_clause, status_values = _workflow_status_clause(str(params.get("status") or "all"))
        if status_clause:
            where.append(status_clause)
            values.extend(status_values)
        if str(params.get("status") or "") == "recent":
            where.append("""(
                status IN ('queued', 'running')
                OR datetime(COALESCE(updated_at, created_at)) >= datetime('now', '-10 minutes')
            )""")
        video_ids = _split_request_values(params.get("videoIds") or params.get("ids"))
        if video_ids:
            where.append(f"video_id IN ({_sql_placeholders(video_ids)})")
            values.extend(video_ids)
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_workflow_jobs{where_sql}", values)
        total = int((cursor.fetchone() or {})["total"] or 0)
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        {where_sql}
        ORDER BY CASE WHEN status IN ('queued', 'running') THEN 0 ELSE 1 END,
                 updated_at DESC,
                 created_at DESC
        LIMIT ? OFFSET ?
        '''.format(where_sql=where_sql), values + [page_size, offset])
        return {
            "items": [_row_to_workflow_job(row) for row in cursor.fetchall()],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }


def _active_job_for_video(cursor, video_id):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ? AND status IN ('queued', 'running')
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _latest_workflow_job_for_material(cursor, video_id, process_version=""):
    if not video_id:
        return None

    normalized_version = _normalize_process_version(process_version) if process_version else ""
    if normalized_version:
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE video_id = ?
          AND process_version = ?
          AND status IN ('queued', 'running')
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        ''', (video_id, normalized_version))
        row = cursor.fetchone()
        if row:
            return _row_to_workflow_job(row)

    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
      AND status IN ('queued', 'running')
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    if row:
        return _row_to_workflow_job(row)

    if normalized_version:
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE video_id = ?
          AND process_version = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        ''', (video_id, normalized_version))
        row = cursor.fetchone()
        if row:
            return _row_to_workflow_job(row)

    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _attach_material_workflow_state(cursor, material):
    video_id = material.get("source_video_id") or material.get("metadata", {}).get("videoId") or ""
    if not video_id:
        return material

    process_version = material.get("processVersion") or material.get("metadata", {}).get("processVersion") or ""
    job = _latest_workflow_job_for_material(cursor, video_id, process_version)
    if not job:
        return material

    material["workflowStatus"] = job.get("status") or ""
    material["workflowStep"] = job.get("step") or ""
    material["workflowMessage"] = job.get("message") or ""
    material["workflowProgress"] = job.get("progress") or 0
    material["workflowProcessVersion"] = job.get("processVersion") or ""
    material["workflowSubtitleLanguage"] = job.get("subtitleLanguage") or ""
    material["workflowUpdatedAt"] = job.get("updatedAt") or ""
    material["workflowJobId"] = job.get("id") or ""
    material["workflowSameProcessVersion"] = bool(
        process_version and job.get("processVersion") == process_version
    )
    return material


def _latest_workflow_jobs_for_videos(cursor, video_ids):
    clean_ids = _clean_unique_list(video_ids)
    if not clean_ids:
        return {}, {}

    cursor.execute(f'''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id IN ({_sql_placeholders(clean_ids)})
    ORDER BY CASE WHEN status IN ('queued', 'running') THEN 0 ELSE 1 END,
             updated_at DESC,
             created_at DESC
    ''', clean_ids)
    jobs = [_row_to_workflow_job(row) for row in cursor.fetchall()]
    jobs_by_video = {}
    jobs_by_video_version = {}
    for job in jobs:
        video_id = job.get("videoId") or ""
        if not video_id:
            continue
        process_version = job.get("processVersion") or ""
        jobs_by_video.setdefault(video_id, job)
        if process_version:
            jobs_by_video_version.setdefault((video_id, process_version), job)
    return jobs_by_video, jobs_by_video_version


def _material_workflow_job(material, jobs_by_video, jobs_by_video_version):
    video_id = material.get("source_video_id") or material.get("metadata", {}).get("videoId") or ""
    process_version = material.get("processVersion") or material.get("metadata", {}).get("processVersion") or ""
    normalized_version = _normalize_process_version(process_version) if process_version else ""
    if normalized_version:
        job = jobs_by_video_version.get((video_id, normalized_version))
        if job:
            return job
    return jobs_by_video.get(video_id)


def _attach_workflow_job_to_material(material, workflow_job):
    if not workflow_job:
        return material
    material["workflowStatus"] = workflow_job.get("status") or ""
    material["workflowStep"] = workflow_job.get("step") or ""
    material["workflowMessage"] = workflow_job.get("message") or ""
    material["workflowProgress"] = workflow_job.get("progress") or 0
    material["workflowProcessVersion"] = workflow_job.get("processVersion") or ""
    material["workflowSubtitleLanguage"] = workflow_job.get("subtitleLanguage") or ""
    material["workflowUpdatedAt"] = workflow_job.get("updatedAt") or ""
    material["workflowJobId"] = workflow_job.get("id") or ""
    material["workflowSameProcessVersion"] = bool(
        material.get("processVersion") and workflow_job.get("processVersion") == material.get("processVersion")
    )
    return material


def _active_analysis_job_for_video(cursor, video_id):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
      AND status IN ('queued', 'running')
      AND step = 'analysis'
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _assert_no_active_youtube_job(cursor, video_id):
    active_job = _active_job_for_video(cursor, video_id)
    if not active_job:
        return
    raise WorkflowConflictError(
        "该视频存在运行中任务，请等待任务结束后再操作。",
        WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
        "ACTIVE_JOB_LOCK",
        {"job": active_job},
    )


def update_youtube_workflow_job(job_id, **changes):
    if not changes:
        return get_youtube_workflow_job(job_id)
    fields = []
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_workflow_jobs
        SET {", ".join(fields)}
        WHERE id = ?
        ''', values)
        conn.commit()
    return get_youtube_workflow_job(job_id)


def mark_interrupted_workflow_jobs(error_code, error_type, reason, detail="", only_existing_active=True):
    init_youtube_workflow_table()
    now = _now_iso()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE status IN ('queued', 'running')
        ''')
        rows = cursor.fetchall()
        if not rows:
            return []
        cursor.execute('''
        UPDATE youtube_workflow_jobs
        SET status = 'abnormal',
            step = 'abnormal',
            message = ?,
            error_code = ?,
            error_type = ?,
            error_reason = ?,
            error_detail = ?,
            interrupted_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('queued', 'running')
        ''', (reason, error_code, error_type, reason, detail, now))
        conn.commit()
        return [get_youtube_workflow_job(row["id"]) for row in rows]


def recover_interrupted_workflow_jobs():
    return mark_interrupted_workflow_jobs(
        WORKFLOW_ERROR_BOOT_INTERRUPTED,
        "BACKEND_RESTART_RECOVERY",
        "后端服务曾异常退出，任务未正常结束",
        "服务启动时发现数据库中仍有 queued/running 任务，已标记为异常。",
    )


def mark_shutdown_interrupted_jobs():
    return mark_interrupted_workflow_jobs(
        WORKFLOW_ERROR_SHUTDOWN,
        "BACKEND_SHUTDOWN",
        "后端服务正在关闭，任务被中断",
        "后端进程收到退出信号，已尽量将运行中任务标记为异常。",
    )


WORKFLOW_STAGE_LABELS = {
    "download": "下载原视频",
    "subtitle": "转写处理与烧录",
    "analysis": "剪辑方案分析",
    "publish": "发布",
    "workflow": "完整工作流",
    "cloud_summary": "云端总结",
}


def _file_size_mb(path):
    if not path:
        return 0
    try:
        candidate = Path(path)
        if candidate.is_file():
            return round(candidate.stat().st_size / (1024 * 1024), 2)
    except Exception:
        return 0
    return 0


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def start_workflow_event(job, stage, message="", input_file_path="", metadata=None):
    init_database_tables()
    now = _now_iso()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_events (
            job_id, video_id, stage, stage_label, status, message,
            input_file_path, input_size_mb, started_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.get("id") or "",
            job.get("videoId") or "",
            stage,
            WORKFLOW_STAGE_LABELS.get(stage, stage),
            "running",
            message,
            str(input_file_path or ""),
            _file_size_mb(input_file_path),
            now,
            json.dumps(metadata or {}, ensure_ascii=False),
        ))
        conn.commit()
        return cursor.lastrowid


def finish_workflow_event(event_id, status="success", message="", output_file_path="", cloud_usage=None, metadata=None):
    if not event_id:
        return None
    init_database_tables()
    now = _now_iso()
    cloud_usage = cloud_usage or {}
    prompt_tokens = int(cloud_usage.get("promptTokens") or cloud_usage.get("prompt_tokens") or 0)
    completion_tokens = int(cloud_usage.get("completionTokens") or cloud_usage.get("completion_tokens") or 0)
    total_tokens = int(
        cloud_usage.get("totalTokens")
        or cloud_usage.get("total_tokens")
        or cloud_usage.get("tokens")
        or (prompt_tokens + completion_tokens)
        or 0
    )
    metadata = metadata or {}
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_workflow_events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        started_at = _parse_dt(event["started_at"]) if event else None
        duration = 0
        if started_at:
            ended_at = _parse_dt(now) or datetime.datetime.now()
            duration = max(0, (ended_at.replace(tzinfo=None) - started_at.replace(tzinfo=None)).total_seconds())
        cursor.execute('''
        UPDATE youtube_workflow_events
        SET status = ?,
            message = ?,
            output_file_path = ?,
            output_size_mb = ?,
            ended_at = ?,
            duration_seconds = ?,
            cloud_model = ?,
            prompt_tokens = ?,
            completion_tokens = ?,
            total_tokens = ?,
            cloud_latency_ms = ?,
            metadata = ?
        WHERE id = ?
        ''', (
            status,
            message,
            str(output_file_path or ""),
            _file_size_mb(output_file_path),
            now,
            round(duration, 2),
            cloud_usage.get("model") or "",
            prompt_tokens,
            completion_tokens,
            total_tokens,
            float(cloud_usage.get("latencyMs") or 0),
            json.dumps(metadata, ensure_ascii=False),
            event_id,
        ))
        conn.commit()
        cursor.execute("SELECT * FROM youtube_workflow_events WHERE id = ?", (event_id,))
        return _row_to_workflow_event(cursor.fetchone())


def _row_to_workflow_event(row):
    item = dict(row)
    try:
        metadata = json.loads(item.get("metadata") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": item.get("id"),
        "jobId": item.get("job_id") or "",
        "videoId": item.get("video_id") or "",
        "stage": item.get("stage") or "",
        "stageLabel": item.get("stage_label") or item.get("stage") or "",
        "status": item.get("status") or "",
        "message": item.get("message") or "",
        "inputFilePath": item.get("input_file_path") or "",
        "outputFilePath": item.get("output_file_path") or "",
        "inputSizeMb": float(item.get("input_size_mb") or 0),
        "outputSizeMb": float(item.get("output_size_mb") or 0),
        "startedAt": item.get("started_at") or "",
        "endedAt": item.get("ended_at") or "",
        "durationSeconds": round(float(item.get("duration_seconds") or 0), 2),
        "cloudModel": item.get("cloud_model") or "",
        "promptTokens": int(item.get("prompt_tokens") or 0),
        "completionTokens": int(item.get("completion_tokens") or 0),
        "totalTokens": int(item.get("total_tokens") or 0),
        "cloudLatencyMs": float(item.get("cloud_latency_ms") or 0),
        "metadata": metadata,
        "createdAt": item.get("created_at") or "",
    }


def list_workflow_events(limit=200, page=1, page_size=None):
    init_youtube_workflow_table()
    page_size = _parse_positive_int(page_size or limit, limit, 1, 1000)
    page = _parse_positive_int(page, 1, 1, 100000)
    offset = (page - 1) * page_size
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM youtube_workflow_events")
        total = int((cursor.fetchone() or {})["total"] or 0)
        cursor.execute('''
        SELECT e.*, j.title, j.process_version, j.subtitle_language, j.burn_profile
        FROM youtube_workflow_events e
        LEFT JOIN youtube_workflow_jobs j ON j.id = e.job_id
        ORDER BY e.started_at DESC, e.id DESC
        LIMIT ? OFFSET ?
        ''', (page_size, offset))
        rows = cursor.fetchall()
        events = []
        for row in rows:
            event = _row_to_workflow_event(row)
            event["title"] = row["title"] or ""
            event["processVersion"] = row["process_version"] or "translation_v1"
            event["subtitleLanguage"] = _normalize_subtitle_language(row["subtitle_language"])
            event["burnProfile"] = _normalize_burn_profile(row["burn_profile"])
            events.append(event)
        return {"items": events, "total": total, "page": page, "pageSize": page_size}


def get_workflow_statistics(limit=200, page=1, page_size=None):
    event_page = list_workflow_events(limit, page=page, page_size=page_size)
    events = event_page["items"]
    jobs_page = list_youtube_workflow_jobs(limit)
    jobs = jobs_page["items"]
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT
            COUNT(*) AS event_count,
            SUM(duration_seconds) AS total_duration,
            SUM(prompt_tokens) AS prompt_tokens,
            SUM(completion_tokens) AS completion_tokens,
            SUM(total_tokens) AS total_tokens,
            SUM(CASE WHEN cloud_latency_ms > 0 OR total_tokens > 0 THEN 1 ELSE 0 END) AS cloud_call_count,
            AVG(CASE WHEN cloud_latency_ms > 0 OR total_tokens > 0 THEN cloud_latency_ms ELSE NULL END) AS avg_cloud_latency
        FROM youtube_workflow_events
        ''')
        summary_row = cursor.fetchone()
        event_count = int(summary_row["event_count"] or 0) if summary_row else 0
        total_duration = float(summary_row["total_duration"] or 0) if summary_row else 0
        prompt_tokens = int(summary_row["prompt_tokens"] or 0) if summary_row else 0
        completion_tokens = int(summary_row["completion_tokens"] or 0) if summary_row else 0
        total_tokens = int(summary_row["total_tokens"] or 0) if summary_row else 0
        cloud_call_count = int(summary_row["cloud_call_count"] or 0) if summary_row else 0
        avg_cloud_latency = float(summary_row["avg_cloud_latency"] or 0) if summary_row else 0

        cursor.execute('''
        SELECT
            stage,
            COALESCE(stage_label, stage) AS stage_label,
            COUNT(*) AS count,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(duration_seconds) AS duration_seconds,
            AVG(duration_seconds) AS avg_duration_seconds,
            SUM(input_size_mb) AS input_size_mb,
            SUM(output_size_mb) AS output_size_mb,
            SUM(prompt_tokens) AS prompt_tokens,
            SUM(completion_tokens) AS completion_tokens,
            SUM(total_tokens) AS total_tokens,
            AVG(CASE WHEN cloud_latency_ms > 0 OR total_tokens > 0 THEN cloud_latency_ms ELSE NULL END) AS avg_cloud_latency
        FROM youtube_workflow_events
        GROUP BY stage, COALESCE(stage_label, stage)
        ORDER BY MAX(started_at) DESC, MAX(id) DESC
        ''')
        stages = []
        for row in cursor.fetchall():
            stages.append({
                "stage": row["stage"] or "",
                "stageLabel": row["stage_label"] or row["stage"] or "",
                "count": int(row["count"] or 0),
                "success": int(row["success"] or 0),
                "failed": int(row["failed"] or 0),
                "durationSeconds": round(float(row["duration_seconds"] or 0), 2),
                "avgDurationSeconds": round(float(row["avg_duration_seconds"] or 0), 2),
                "inputSizeMb": round(float(row["input_size_mb"] or 0), 2),
                "outputSizeMb": round(float(row["output_size_mb"] or 0), 2),
                "promptTokens": int(row["prompt_tokens"] or 0),
                "completionTokens": int(row["completion_tokens"] or 0),
                "totalTokens": int(row["total_tokens"] or 0),
                "avgCloudLatencyMs": round(float(row["avg_cloud_latency"] or 0), 2),
            })

    return {
        "summary": {
            "eventCount": event_count,
            "jobCount": jobs_page["total"],
            "totalDurationSeconds": round(total_duration, 2),
            "avgDurationSeconds": round(total_duration / event_count, 2) if event_count else 0,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": total_tokens,
            "cloudCallCount": cloud_call_count,
            "avgCloudLatencyMs": round(avg_cloud_latency, 2),
        },
        "stages": stages,
        "events": events,
        "eventsTotal": event_page["total"],
        "eventsPage": event_page["page"],
        "eventsPageSize": event_page["pageSize"],
        "jobs": jobs,
    }


def update_youtube_video_artifacts(video_id, **changes):
    if not video_id or not changes:
        return None
    fields = []
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(video_id)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = ?
        ''', values)
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return _row_to_youtube_video(row) if row else None


def update_youtube_video_analysis_status(video_id, status, result=None):
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    init_youtube_video_table()
    fields = ["analysis_status = ?", "analysis_updated_at = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]
    values = [int(status)]
    if result is not None:
        fields.append("analysis_result = ?")
        values.append(json.dumps(result, ensure_ascii=False))
    values.append(video_id)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = ?
        ''', values)
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def save_youtube_video_analysis(video_id, result):
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    init_youtube_video_table()
    default_draft = _build_default_publish_draft(result)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT publish_draft FROM youtube_videos WHERE video_id = ?
        ''', (video_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("视频线索不存在")

        current_draft = _parse_publish_draft(row["publish_draft"] if "publish_draft" in row.keys() else "", result)
        if current_draft:
            cursor.execute('''
            UPDATE youtube_videos
            SET analysis_status = 1,
                analysis_result = ?,
                analysis_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (json.dumps(result, ensure_ascii=False), video_id))
        else:
            cursor.execute('''
            UPDATE youtube_videos
            SET analysis_status = 1,
                analysis_result = ?,
                publish_draft = ?,
                analysis_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (
                json.dumps(result, ensure_ascii=False),
                json.dumps(default_draft, ensure_ascii=False),
                video_id,
            ))
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def update_youtube_video_publish_draft(video_id, payload):
    current = get_youtube_video_analysis(video_id)
    current_draft = dict(current.get("draft") or {})
    title = payload.get("title", payload.get("selectedTitle", current_draft.get("title", "")))
    description = payload.get("description", payload.get("publish_copy", current_draft.get("description", "")))
    tags = payload.get("tags", current_draft.get("tags", []))
    draft = {
        "title": str(title or "").strip(),
        "description": str(description or "").strip(),
        "tags": _clean_topic_list(tags),
        "source": "user_saved",
        "updatedAt": _now_iso(),
    }
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE youtube_videos
        SET publish_draft = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (json.dumps(draft, ensure_ascii=False), video_id))
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
    return get_youtube_video_analysis(video_id)


def update_youtube_video_analysis_result(video_id, payload):
    return update_youtube_video_publish_draft(video_id, payload)


def ensure_youtube_publish_draft(video_id):
    analysis = get_youtube_video_analysis(video_id)
    if analysis.get("draft"):
        return analysis
    result = analysis.get("result") or {}
    if not result:
        return analysis
    draft = _build_default_publish_draft(result)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE youtube_videos
        SET publish_draft = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (json.dumps(draft, ensure_ascii=False), video_id))
        conn.commit()
    return get_youtube_video_analysis(video_id)


def get_youtube_video_analysis(video_id):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("视频线索不存在")
        raw_result = row["analysis_result"] if "analysis_result" in row.keys() else ""
        result = _parse_json_object(raw_result)
        raw_draft = row["publish_draft"] if "publish_draft" in row.keys() else ""
        draft = _parse_publish_draft(raw_draft, result)
        return {
            "videoId": video_id,
            "status": int(row["analysis_status"] or 0),
            "updatedAt": row["analysis_updated_at"] or "",
            "result": result,
            "draft": draft,
            "error": result.get("error") or {},
        }


