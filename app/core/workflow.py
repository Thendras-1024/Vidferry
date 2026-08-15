"""YouTube 工作流任务的创建、状态更新、阶段事件记录与统计。"""


import datetime

from app.core.cover_service import (
    normalize_cover_context,
    normalize_cover_signature,
    normalize_cover_title,
)


_WORKFLOW_JOB_MUTABLE_FIELDS = {
    "status", "step", "message", "source_file_path", "processed_file_path",
    "publish_command", "progress", "speed", "eta", "error_code", "error_type",
    "error_reason", "error_detail", "interrupted_at", "publish_confirmation_required",
    "publish_confirmation_status", "content_risk",
    "translation_enabled", "subtitle_mask_enabled", "source_subtitle_analysis",
}
_WORKFLOW_ACTIVE_STATUSES = ("queued", "running", "waiting_confirmation", "waiting_publish")
_WORKFLOW_TERMINAL_STATUSES = ("success", "reused", "partial", "needs_verification", "failed", "abnormal", "cancelled")


def _workflow_content_risk(value):
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else (value or {})
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _workflow_source_subtitle_analysis(value):
    try:
        parsed = json.loads(value or "{}") if isinstance(value, str) else (value or {})
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_subtitle_mode(value, allow_legacy=True):
    mode = str(value or "").strip()
    allowed = {"auto", "force_burn", "original"}
    if allow_legacy:
        allowed.add("legacy")
    return mode if mode in allowed else ("legacy" if allow_legacy else "auto")


def _content_safety_enabled(item):
    return bool(_workflow_content_risk(item.get("content_risk")).get("contentSafetyReviewEnabled"))


def _validate_workflow_job_changes(changes):
    invalid_fields = set(changes) - _WORKFLOW_JOB_MUTABLE_FIELDS
    if invalid_fields:
        raise ValueError(f"不允许更新工作流字段: {', '.join(sorted(invalid_fields))}")


def _row_to_workflow_job(row):
    item = dict(row)
    content_risk = _workflow_content_risk(item.get("content_risk"))
    source_subtitle_analysis = _workflow_source_subtitle_analysis(item.get("source_subtitle_analysis"))
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
        "xiaohongshuAccount": item.get("xiaohongshu_account") or "",
        "kuaishouAccount": item.get("kuaishou_account") or "",
        "tencentAccount": item.get("tencent_account") or "",
        "publishAccountGroupId": item.get("publish_account_group_id"),
        "publishToDouyin": int(item.get("publish_to_douyin") or 0),
        "publishToBilibili": int(item.get("publish_to_bilibili") or 0),
        "publishToXiaohongshu": int(item.get("publish_to_xiaohongshu") or 0),
        "publishToKuaishou": int(item.get("publish_to_kuaishou") or 0),
        "publishToTencent": int(item.get("publish_to_tencent") or 0),
        "processVersion": _normalize_process_version(item.get("process_version")),
        "subtitleLanguage": _normalize_subtitle_language(item.get("subtitle_language")),
        "burnProfile": _normalize_burn_profile(item.get("burn_profile")),
        "subtitleSize": _normalize_subtitle_size(item.get("subtitle_size")),
        "translatorLabel": _normalize_translator_label(item.get("translator_label")),
        "watermarkEnabled": bool(item.get("watermark_enabled") or 0),
        "watermarkText": _normalize_watermark_text(item.get("watermark_text")),
        "highlightCount": _normalize_highlight_count(item.get("highlight_count")),
        "translationEnabled": bool(item.get("translation_enabled") if item.get("translation_enabled") is not None else 1),
        "highlightIntroEnabled": bool(item.get("highlight_intro_enabled") if item.get("highlight_intro_enabled") is not None else 1),
        "coverIntroEnabled": bool(item.get("cover_intro_enabled") if item.get("cover_intro_enabled") is not None else 1),
        "commentBurnEnabled": bool(item.get("comment_burn_enabled") or 0),
        "subtitleMaskEnabled": bool(item.get("subtitle_mask_enabled") or 0),
        "subtitleMode": _normalize_subtitle_mode(item.get("subtitle_mode")),
        "sourceSubtitleAnalysis": source_subtitle_analysis,
        "commentBurnCount": _normalize_comment_burn_count(item.get("comment_burn_count")),
        "commentTranslationMode": _normalize_comment_translation_mode(item.get("comment_translation_mode")),
        "coverTitle": normalize_cover_title(item.get("cover_title")),
        "coverSignature": normalize_cover_signature(item.get("cover_brand_name")),
        "operation": item.get("operation") or "process",
        "title": item.get("title") or "",
        "description": item.get("description") or "",
        "tags": json.loads(item.get("tags") or "[]"),
        "schedule": item.get("schedule") or "",
        "status": item.get("status") or "",
        "step": item.get("step") or "",
        "message": clean_display_text(item.get("message")),
        "sourceFilePath": item.get("source_file_path") or "",
        "processedFilePath": item.get("processed_file_path") or "",
        "publishCommand": item.get("publish_command") or "",
        "publishConfirmationRequired": bool(item.get("publish_confirmation_required") or 0),
        "publishConfirmationStatus": item.get("publish_confirmation_status") or "",
        "contentRisk": content_risk,
        "ownerUserId": item.get("owner_user_id"),
        "contentSafetyReviewEnabled": _content_safety_enabled(item),
        "progress": round(float(item.get("progress") or 0), 1),
        "speed": item.get("speed") or "",
        "eta": item.get("eta") or "",
        "errorCode": item.get("error_code") or "",
        "errorType": item.get("error_type") or "",
        "errorReason": clean_display_text(item.get("error_reason")),
        "errorDetail": clean_display_text(item.get("error_detail")),
        "interruptedAt": item.get("interrupted_at") or "",
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def _processing_settings_snapshot(job):
    """返回成片可追溯的处理参数，不包含发布账号和平台选择。"""
    if not job:
        return {}
    return {
        "processVersion": job.get("processVersion") or PROCESS_VERSION_TRANSLATION,
        "subtitleLanguage": job.get("subtitleLanguage") or DEFAULT_SUBTITLE_LANGUAGE,
        "burnProfile": job.get("burnProfile") or DEFAULT_BURN_PROFILE,
        "subtitleSize": job.get("subtitleSize") or DEFAULT_SUBTITLE_SIZE,
        "translatorLabel": job.get("translatorLabel") or "",
        "translationEnabled": bool(job.get("translationEnabled", True)),
        "watermarkEnabled": bool(job.get("watermarkEnabled")),
        "watermarkText": job.get("watermarkText") or "",
        "highlightIntroEnabled": bool(job.get("highlightIntroEnabled", True)),
        "highlightCount": int(job.get("highlightCount") or 0),
        "coverIntroEnabled": bool(job.get("coverIntroEnabled", True)),
        "coverTitle": job.get("coverTitle") or "",
        "coverSignature": job.get("coverSignature") or "",
        "commentBurnEnabled": bool(job.get("commentBurnEnabled")),
        "subtitleMaskEnabled": bool(job.get("subtitleMaskEnabled")),
        "subtitleMode": _normalize_subtitle_mode(job.get("subtitleMode")),
        "sourceSubtitleAnalysis": _workflow_source_subtitle_analysis(job.get("sourceSubtitleAnalysis")),
        "commentBurnCount": int(job.get("commentBurnCount") or 0),
        "commentTranslationMode": job.get("commentTranslationMode") or "",
        "contentSafetyReviewEnabled": bool(job.get("contentSafetyReviewEnabled")),
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


def _validate_burn_profile_source_resolution(video_id, burn_profile):
    if burn_profile != "2k":
        return
    source_file = _resolve_downloaded_source_file({"videoId": video_id})
    video_info = _get_video_info(source_file)
    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    if max(width, height) >= 2560 and min(width, height) >= 1440:
        return
    raise ValueError(
        "2K 高画质（需 2K 原片）仅支持原视频不低于 2560x1440（竖屏不低于 1440x2560）。"
        f"当前下载视频为 {width}x{height}，请改用 1080p 预设后重试。"
    )


def _normalize_subtitle_size(value):
    size = str(value or DEFAULT_SUBTITLE_SIZE).strip()
    return size if size in SUBTITLE_SIZE_PRESETS else DEFAULT_SUBTITLE_SIZE


def _subtitle_size_config(value):
    size = _normalize_subtitle_size(value)
    return size, SUBTITLE_SIZE_PRESETS[size]


def _normalize_translator_label(value):
    label = str(value or "").strip()
    return label[:20] if label else DEFAULT_TRANSLATOR_LABEL


def _normalize_watermark_text(value):
    text = str(value or "").strip()[:16]
    return text if len(text) >= 2 else ""


def _normalize_highlight_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 3
    return count if count in {1, 2, 3} else 3


def _normalize_comment_translation_mode(value):
    mode = str(value or "google_llm").strip()
    return mode if mode in {"google_llm", "google"} else "google_llm"


def _normalize_comment_burn_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 30
    return count if count in {20, 25, 30, 35, 40, 45, 50} else 30


def _workflow_watermark_settings(payload):
    saved_settings = get_workflow_settings()
    watermark_enabled = bool(
        payload["watermarkEnabled"]
        if "watermarkEnabled" in payload else saved_settings.get("watermarkEnabled")
    )
    watermark_text = _normalize_watermark_text(
        payload["watermarkText"]
        if "watermarkText" in payload else saved_settings.get("watermarkText")
    )
    return watermark_enabled, watermark_text


def _workflow_cover_settings(payload):
    saved_settings = get_workflow_settings()
    signature = payload.get("coverSignature") if "coverSignature" in payload else saved_settings.get("coverSignature")
    return (
        normalize_cover_title(payload.get("coverTitle")),
        normalize_cover_signature(signature),
    )


def _workflow_highlight_count(payload):
    saved_settings = get_workflow_settings()
    value = payload.get("highlightCount") if "highlightCount" in payload else saved_settings.get("highlightCount")
    return _normalize_highlight_count(value)


def _workflow_comment_burn_count(payload):
    saved_settings = get_workflow_settings()
    value = payload.get("commentBurnCount") if "commentBurnCount" in payload else saved_settings.get("commentBurnCount")
    return _normalize_comment_burn_count(value)


def _workflow_processing_options(payload):
    saved_settings = get_workflow_settings()
    defaults = {"translationEnabled": True, "highlightIntroEnabled": True, "coverIntroEnabled": True, "commentBurnEnabled": False, "subtitleMaskEnabled": False}
    return tuple(bool(payload[key] if key in payload else saved_settings.get(key, defaults[key])) for key in (
        "translationEnabled", "highlightIntroEnabled", "coverIntroEnabled", "commentBurnEnabled", "subtitleMaskEnabled",
    ))


def _workflow_subtitle_mode(payload):
    saved_settings = get_workflow_settings()
    value = payload.get("subtitleMode") if "subtitleMode" in payload else saved_settings.get("subtitleMode")
    return _normalize_subtitle_mode(value, allow_legacy=False)


def _normalize_process_version(value):
    process_version = str(value or PROCESS_VERSION_TRANSLATION).strip()
    return process_version if process_version in PROCESS_VERSIONS else PROCESS_VERSION_TRANSLATION


def create_youtube_workflow_job(payload, *, allow_active_job=False, lock_scope="media"):
    init_youtube_workflow_table()
    payload = dict(payload or {})
    account_group = resolve_publish_account_group(payload.get("publishAccountGroupId"))
    if account_group:
        group_accounts = {int(item["platformType"]): item["name"] for item in account_group["accounts"]}
        platform_fields = {1: "xiaohongshuAccount", 2: "tencentAccount", 3: "account", 4: "kuaishouAccount", 5: "bilibiliAccount"}
        platform_flags = {1: "publishToXiaohongshu", 2: "publishToTencent", 3: "publishToDouyin", 4: "publishToKuaishou", 5: "publishToBilibili"}
        for platform_type, account_name in group_accounts.items():
            payload[platform_fields[platform_type]] = account_name
            payload[platform_flags[platform_type]] = True
        for platform_type, field in platform_fields.items():
            if platform_type not in group_accounts:
                payload[field] = ""
                payload[platform_flags[platform_type]] = False
    job_id = str(uuid.uuid4())
    subtitle_language = _normalize_subtitle_language(payload.get("subtitleLanguage"))
    burn_profile = _normalize_burn_profile(payload.get("burnProfile"))
    subtitle_size = _normalize_subtitle_size(payload.get("subtitleSize"))
    translator_label = _normalize_translator_label(payload.get("translatorLabel"))
    watermark_enabled, watermark_text = _workflow_watermark_settings(payload)
    highlight_count = _workflow_highlight_count(payload)
    comment_burn_count = _workflow_comment_burn_count(payload)
    comment_translation_mode = _normalize_comment_translation_mode(payload.get("commentTranslationMode"))
    translation_enabled, highlight_intro_enabled, cover_intro_enabled, comment_burn_enabled, subtitle_mask_enabled = _workflow_processing_options(payload)
    subtitle_mode = _workflow_subtitle_mode(payload)
    if subtitle_mode == "auto":
        translation_enabled, subtitle_mask_enabled = True, False
    elif subtitle_mode == "force_burn":
        translation_enabled = True
    else:
        translation_enabled, subtitle_mask_enabled = False, False
    cover_title, cover_signature = _workflow_cover_settings(payload)
    process_version = _normalize_process_version(payload.get("processVersion"))
    if comment_burn_enabled and process_version != PROCESS_VERSION_EDITING:
        raise ValueError("评论烧制仅支持处理版本二")
    if comment_burn_enabled and str(SUBTITLE_COMMAND_TEMPLATE or "").strip():
        raise ValueError("启用自定义字幕命令时不支持评论烧制")
    if subtitle_mask_enabled and str(SUBTITLE_COMMAND_TEMPLATE or "").strip():
        raise ValueError("启用自定义字幕命令时不支持字幕马赛克遮挡")
    if subtitle_mode == "auto" and str(SUBTITLE_COMMAND_TEMPLATE or "").strip():
        raise ValueError("启用自定义字幕命令时不支持字幕自动适配")
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]
    video_id = payload.get("videoId") or ""
    _validate_burn_profile_source_resolution(video_id, burn_profile)
    if lock_scope not in {"media", "analysis"}:
        raise ValueError("任务锁范围不合法")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        if video_id and not allow_active_job:
            active_job = _active_job_for_video(cursor, video_id)
            if active_job:
                raise WorkflowConflictError(
                    "该视频存在运行中任务，请等待任务结束后再操作。",
                    WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
                    "ACTIVE_JOB_LOCK",
                    {"job": active_job},
                )
        if video_id:
            try:
                cursor.execute(
                    "INSERT INTO youtube_workflow_locks (video_id, scope, job_id) VALUES (?, ?, ?)",
                    (video_id, lock_scope, job_id),
                )
            except DATABASE_INTEGRITY_ERRORS as exc:
                cursor.execute(
                    "SELECT job_id FROM youtube_workflow_locks WHERE video_id = ? AND scope = ?",
                    (video_id, lock_scope),
                )
                lock = cursor.fetchone()
                raise WorkflowConflictError(
                    "该视频存在同类型运行中任务，请等待任务结束后再操作。",
                    WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
                    "ACTIVE_JOB_LOCK",
                    {"jobId": lock["job_id"] if lock else ""},
                ) from exc
        cursor.execute('''
        INSERT INTO youtube_workflow_jobs (
            id, video_id, url, account, channel, subscribers, published_at,
            bilibili_account, bilibili_tid, xiaohongshu_account, kuaishou_account, tencent_account,
            publish_to_douyin, publish_to_bilibili, publish_to_xiaohongshu, publish_to_kuaishou, publish_to_tencent,
            process_version, subtitle_language, burn_profile, subtitle_size, translator_label, watermark_enabled, watermark_text, highlight_count, translation_enabled, highlight_intro_enabled, cover_intro_enabled, comment_burn_enabled, subtitle_mask_enabled, subtitle_mode, source_subtitle_analysis, comment_burn_count, comment_translation_mode, publish_account_group_id, owner_user_id,
            cover_title, cover_context, cover_brand_name, cover_brand_platform, operation,
            title, description, tags, schedule, status, step, message
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ''', (
            job_id,
            video_id,
            payload["url"],
            payload.get("account") or "",
            payload.get("channel") or "",
            _format_subscribers_w(payload.get("subscribers")),
            payload.get("publishedAt") or "",
            payload.get("bilibiliAccount") or "",
            normalize_bilibili_tid(payload.get("bilibiliTid")),
            payload.get("xiaohongshuAccount") or "",
            payload.get("kuaishouAccount") or "",
            payload.get("tencentAccount") or "",
            int(1 if payload.get("publishToDouyin") else 0),
            int(1 if payload.get("publishToBilibili") else 0),
            int(1 if payload.get("publishToXiaohongshu") else 0),
            int(1 if payload.get("publishToKuaishou") else 0),
            int(1 if payload.get("publishToTencent") else 0),
            process_version,
            subtitle_language,
            burn_profile,
            subtitle_size,
            translator_label,
            int(watermark_enabled),
            watermark_text,
            highlight_count,
            int(translation_enabled),
            int(highlight_intro_enabled),
            int(cover_intro_enabled),
            int(comment_burn_enabled),
            int(subtitle_mask_enabled),
            subtitle_mode,
            "{}",
            comment_burn_count,
            comment_translation_mode,
            account_group.get("id") if account_group else None,
            payload.get("ownerUserId"),
            cover_title,
            "",
            cover_signature,
            "",
            payload.get("operation") or "process",
            payload.get("title") or "",
            payload.get("description") or "",
            json.dumps(tags, ensure_ascii=False),
            payload.get("schedule") or "",
            "queued",
            "queued",
            "任务已创建，等待后台执行",
        ))
        cursor.execute(
            "UPDATE youtube_workflow_jobs SET content_risk = ? WHERE id = ?",
            (json.dumps({"contentSafetyReviewEnabled": bool(payload.get("contentSafetyReviewEnabled"))}, ensure_ascii=False), job_id),
        )
        conn.commit()
    return get_youtube_workflow_job(job_id)


def claim_youtube_workflow_job(job_id, **changes):
    """仅允许 queued 任务被一个后台执行器领取。"""
    init_youtube_workflow_table()
    _validate_workflow_job_changes(changes)
    fields = [
        "status = 'running'",
        "started_at = COALESCE(started_at, CURRENT_TIMESTAMP)",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(clean_display_text(value) if key == "message" else value)
    values.append(job_id)
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE youtube_workflow_jobs SET {', '.join(fields)} WHERE id = ? AND status = 'queued'", values)
        if cursor.rowcount != 1:
            return None
        conn.commit()
    return get_youtube_workflow_job(job_id)


def get_youtube_workflow_job(job_id, owner_user_id=None):
    init_youtube_workflow_table()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        if owner_user_id is None:
            cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,))
        else:
            cursor.execute(
                "SELECT * FROM youtube_workflow_jobs WHERE id = ? AND owner_user_id = ?",
                (job_id, int(owner_user_id)),
            )
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        job = _row_to_workflow_job(row)
        publish_progress = _workflow_publish_progress(cursor, job.get("id"))
        if publish_progress:
            job["publishProgress"] = publish_progress
        return job


def _workflow_publish_progress(cursor, job_id):
    if not job_id:
        return None
    cursor.execute(
        "SELECT id, status, message FROM publish_dispatch_jobs WHERE source = 'workflow' AND source_ref_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (str(job_id),),
    )
    dispatch = cursor.fetchone()
    if not dispatch:
        return None
    cursor.execute(
        "SELECT platform_type, status, message, duration_ms, started_at, finished_at "
        "FROM publish_dispatch_targets WHERE job_id = ? ORDER BY platform_type, id",
        (dispatch["id"],),
    )
    targets = [dict(item) for item in cursor.fetchall()]
    progress = _publish_dispatch_progress(targets)
    progress.update({
        "publishTaskId": dispatch["id"],
        "status": dispatch["status"] or "queued",
        "message": clean_display_text(dispatch["message"]),
        "targets": targets,
    })
    return progress


def _workflow_status_clause(status):
    if status == "running":
        return "status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')", []
    if status == "recent":
        return "", []
    if status in set(_WORKFLOW_TERMINAL_STATUSES):
        return "status = ?", [status]
    return "", []


def list_youtube_workflow_jobs(limit=50, params=None, owner_user_id=None):
    init_youtube_workflow_table()
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize") or params.get("limit"), limit, 1, 100)
    offset = (page - 1) * page_size
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        where = []
        values = []
        if owner_user_id is not None:
            where.append("owner_user_id = ?")
            values.append(int(owner_user_id))
        status_clause, status_values = _workflow_status_clause(str(params.get("status") or "all"))
        if status_clause:
            where.append(status_clause)
            values.extend(status_values)
        if str(params.get("status") or "") == "recent":
            where.append("""(
                status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
                OR COALESCE(updated_at, created_at) >= ?
            )""")
            values.append((datetime.datetime.now() - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"))
        if str(params.get("hasSchedule") or "").lower() in {"1", "true", "yes"}:
            where.append("COALESCE(schedule, '') <> '' AND schedule > ?")
            values.append(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
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
        ORDER BY CASE WHEN status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish') THEN 0 ELSE 1 END,
                 updated_at DESC,
                 created_at DESC
        LIMIT ? OFFSET ?
        '''.format(where_sql=where_sql), values + [page_size, offset])
        items = []
        for row in cursor.fetchall():
            job = _row_to_workflow_job(row)
            publish_progress = _workflow_publish_progress(cursor, job.get("id"))
            if publish_progress:
                job["publishProgress"] = publish_progress
            items.append(job)
        return {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }


def _active_job_for_video(cursor, video_id):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ? AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
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
        AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        ''', (video_id, normalized_version))
        row = cursor.fetchone()
        if row:
            return _row_to_workflow_job(row)

    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
      AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
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

    return None


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
    ORDER BY CASE WHEN status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish') THEN 0 ELSE 1 END,
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
        fallback_job = jobs_by_video.get(video_id)
        if fallback_job and fallback_job.get("status") in {"queued", "running", "waiting_confirmation", "waiting_publish"}:
            return fallback_job
        return None
    return jobs_by_video.get(video_id)


def _attach_workflow_job_to_material(material, workflow_job):
    if not workflow_job:
        return material
    if (
        material.get("source_type") == "youtube_processed"
        and workflow_job.get("status") == "failed"
        and int(material.get("analysisStatus") or 0) == 1
    ):
        failed_step = str(workflow_job.get("step") or "").lower()
        failed_message = str(workflow_job.get("message") or "")
        if failed_step in {"analysis", "failed"} and any(keyword in failed_message for keyword in ["文案", "分析", "LLM", "模型"]):
            return material
    material["workflowStatus"] = workflow_job.get("status") or ""
    material["workflowStep"] = workflow_job.get("step") or ""
    material["workflowMessage"] = workflow_job.get("message") or ""
    material["workflowProgress"] = workflow_job.get("progress") or 0
    material["workflowProcessVersion"] = workflow_job.get("processVersion") or ""
    material["workflowSubtitleLanguage"] = workflow_job.get("subtitleLanguage") or ""
    material["workflowUpdatedAt"] = workflow_job.get("updatedAt") or ""
    material["workflowJobId"] = workflow_job.get("id") or ""
    material["processingSettings"] = _processing_settings_snapshot(workflow_job)
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
      AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
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
    _validate_workflow_job_changes(changes)
    for text_key in ("message", "error_reason", "error_detail"):
        if text_key in changes:
            changes[text_key] = clean_display_text(changes[text_key])
    fields = []
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(json.dumps(value, ensure_ascii=False) if key in {"content_risk", "source_subtitle_analysis"} else value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_workflow_jobs
        SET {", ".join(fields)}
        WHERE id = ?
        ''', values)
        if changes.get("status") in set(_WORKFLOW_TERMINAL_STATUSES):
            cursor.execute("DELETE FROM youtube_workflow_locks WHERE job_id = ?", (job_id,))
        conn.commit()
    return get_youtube_workflow_job(job_id)


def resolve_youtube_workflow_publish_confirmation(job_id, confirmed, owner_user_id=None):
    """原子地处理发布确认，避免并发确认重复提交同一工作流。"""
    init_youtube_workflow_table()
    if not isinstance(confirmed, bool):
        raise ValueError("confirmed 必须是布尔值")

    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        if owner_user_id is None:
            cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,))
        else:
            cursor.execute(
                "SELECT * FROM youtube_workflow_jobs WHERE id = ? AND owner_user_id = ?",
                (job_id, int(owner_user_id)),
            )
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        job = _row_to_workflow_job(row)
        if (
            job.get("status") != "waiting_confirmation"
            or not job.get("publishConfirmationRequired")
            or job.get("publishConfirmationStatus") not in {"", "pending"}
        ):
            raise WorkflowConflictError(
                "该任务当前无需发布确认，或确认已处理。",
                "VF-WORKFLOW-PUBLISH-CONFIRMATION-INVALID",
                "PUBLISH_CONFIRMATION_INVALID",
                {"job": job},
            )

        if confirmed:
            cursor.execute('''
            UPDATE youtube_workflow_jobs
            SET status = 'queued',
                step = 'publish',
                message = '已确认待审核项，正在恢复发布',
                publish_confirmation_status = 'confirmed',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'waiting_confirmation'
              AND publish_confirmation_required = 1
              AND COALESCE(publish_confirmation_status, '') IN ('', 'pending')
            ''', (job_id,))
        else:
            cursor.execute('''
            UPDATE youtube_workflow_jobs
            SET status = 'success',
                step = 'done',
                message = '视频已处理完成，已取消发布',
                publish_confirmation_status = 'cancelled',
                progress = 100,
                speed = '',
                eta = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status = 'waiting_confirmation'
              AND publish_confirmation_required = 1
              AND COALESCE(publish_confirmation_status, '') IN ('', 'pending')
            ''', (job_id,))
        if cursor.rowcount != 1:
            raise WorkflowConflictError(
                "该任务的发布确认已被其他请求处理。",
                "VF-WORKFLOW-PUBLISH-CONFIRMATION-INVALID",
                "PUBLISH_CONFIRMATION_INVALID",
                {"jobId": job_id},
            )
        if not confirmed:
            cursor.execute("DELETE FROM youtube_workflow_locks WHERE job_id = ?", (job_id,))
        conn.commit()

    return get_youtube_workflow_job(job_id)


def mark_interrupted_workflow_jobs(error_code, error_type, reason, detail="", only_existing_active=True):
    init_youtube_workflow_table()
    now = _now_iso()
    with _db_connect() as conn:
        conn.row_factory = True
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
        job_ids = [row["id"] for row in rows]
        cursor.execute(
            f"DELETE FROM youtube_workflow_locks WHERE job_id IN ({_sql_placeholders(job_ids)})",
            job_ids,
        )
        conn.commit()
    for job_id in job_ids:
        finish_open_workflow_events(job_id, "failed", reason)
    return [get_youtube_workflow_job(job_id) for job_id in job_ids]


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
    "transcript": "语音转写",
    "subtitle": "字幕翻译与修订",
    "subtitle_burn": "字幕烧制",
    "body_burn": "正片字幕烧制",
    "comment_fetch": "热门评论获取",
    "comment_review": "评论筛选与翻译",
    "comment_render": "评论烧制",
    "cover_render": "封面片头生成",
    "highlight_render": "高光短片生成",
    "editing_concat": "片头与正片拼接",
    "analysis": "内容分析与文案生成",
    "content_safety_detect": "广告风险检测",
    "content_safety_confirm": "等待视频处理确认",
    "content_trim": "风险片段裁剪",
    "editing": "封面片头与高光拼接",
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
    message = clean_display_text(message)
    stage_label = clean_display_text(WORKFLOW_STAGE_LABELS.get(stage, stage))
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_events (
            job_id, video_id, stage, stage_label, status, message,
            input_file_path, input_size_mb, started_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
        ''', (
            job.get("id") or "",
            job.get("videoId") or "",
            stage,
            stage_label,
            "running",
            message,
            str(input_file_path or ""),
            _file_size_mb(input_file_path),
            now,
            json.dumps(metadata or {}, ensure_ascii=False),
        ))
        event_id = cursor.fetchone()[0]
        conn.commit()
        return event_id


def finish_workflow_event(event_id, status="success", message="", output_file_path="", cloud_usage=None, metadata=None):
    if not event_id:
        return None
    init_database_tables()
    now = _now_iso()
    message = clean_display_text(message)
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
    with _db_connect() as conn:
        conn.row_factory = True
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


def finish_open_workflow_events(job_id, status="failed", message=""):
    """收口异常退出的阶段，避免已结束任务留下运行中统计记录。"""
    if not job_id:
        return []
    init_database_tables()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM youtube_workflow_events WHERE job_id = ? AND status = 'running'",
            (job_id,),
        )
        event_ids = [row[0] for row in cursor.fetchall()]
    return [
        finish_workflow_event(event_id, status, message)
        for event_id in event_ids
    ]


def reconcile_finished_workflow_events():
    """收口历史上已结束任务遗留的 running 阶段事件。"""
    init_youtube_workflow_table()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT DISTINCT e.job_id
        FROM youtube_workflow_events e
        LEFT JOIN youtube_workflow_jobs j ON j.id = e.job_id
        WHERE e.status = 'running'
          AND (j.id IS NULL OR j.status NOT IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish'))
        ''')
        job_ids = [row[0] for row in cursor.fetchall()]
    for job_id in job_ids:
        finish_open_workflow_events(job_id, "failed", "任务已结束，已自动收口历史阶段记录")
    return job_ids


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
        "stageLabel": clean_display_text(item.get("stage_label") or item.get("stage") or ""),
        "status": item.get("status") or "",
        "message": clean_display_text(item.get("message")),
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
    with _db_connect() as conn:
        conn.row_factory = True
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


def update_youtube_video_artifacts(video_id, **changes):
    if not video_id or not changes:
        return None
    column_map = {
        "downloadStatus": "download_status",
        "publishStatus": "publish_status",
        "translateStatus": "translate_status",
        "downloadedFilePath": "downloaded_file_path",
        "processedFilePath": "processed_file_path",
        "transcriptStatus": "transcript_status",
        "transcriptFilePath": "transcript_file_path",
        "transcriptLanguage": "transcript_language",
        "analysisStatus": "analysis_status",
        "analysisResult": "analysis_result",
        "publishDraft": "publish_draft",
        "editingBodyPath": "editing_body_path",
        "editingAssPath": "editing_ass_path",
        "editingBodySignature": "editing_body_signature",
        "editingIntroSignature": "editing_intro_signature",
        "editingHighlightSnapshot": "editing_highlight_snapshot",
        "editingIntroStatus": "editing_intro_status",
    }
    fields = []
    values = []
    for key, value in changes.items():
        column = column_map.get(key, key)
        fields.append(f"{column} = ?")
        values.append(value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(video_id)
    with _db_connect() as conn:
        conn.row_factory = True
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
    with _db_connect() as conn:
        conn.row_factory = True
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
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute('''
        SELECT publish_draft FROM youtube_videos WHERE video_id = ?
        ''', (video_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("视频线索不存在")

        current_draft = _parse_publish_draft(row["publish_draft"] if "publish_draft" in row.keys() else "", result)
        if current_draft.get("source") == "user_saved":
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
    custom_tags = payload.get("customTags", current_draft.get("customTags", []))
    cover_title = payload.get("coverTitle", current_draft.get("coverTitle", ""))
    cover_context = payload.get("coverContext", current_draft.get("coverContext", ""))
    selected_tags = _clean_topic_list(tags)
    draft = {
        "title": str(title or "").strip(),
        "coverTitle": normalize_cover_title(cover_title),
        "coverContext": normalize_cover_context(cover_context),
        "description": str(description or "").strip(),
        "tags": selected_tags,
        "customTags": [tag for tag in _clean_topic_list(custom_tags) if tag not in selected_tags],
        "source": "user_saved",
        "updatedAt": _now_iso(),
    }
    with _db_connect() as conn:
        conn.row_factory = True
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
    with _db_connect() as conn:
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
    with _db_connect() as conn:
        conn.row_factory = True
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


