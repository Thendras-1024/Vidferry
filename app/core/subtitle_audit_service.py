"""管理员字幕审查快照与模型失败诊断查询。"""


def _subtitle_audit_json(value, fallback):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or fallback)
    except (TypeError, ValueError):
        return json.loads(fallback)


def _normalize_source_language(value):
    language = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN",
        "en": "en", "en-us": "en", "en-gb": "en",
        "ja": "ja", "ja-jp": "ja",
        "ko": "ko", "ko-kr": "ko",
        "es": "es", "es-es": "es",
        "fr": "fr", "fr-fr": "fr",
        "de": "de", "de-de": "de",
        "ru": "ru", "ru-ru": "ru",
    }
    return aliases.get(language, language if re.fullmatch(r"[a-z]{2,3}", language) else "")


def save_subtitle_audit_snapshot(job, initial_segments, reviewed_segments, review_metadata=None):
    job = job or {}
    job_id = str(job.get("id") or "").strip()
    if not job_id:
        return
    review_metadata = review_metadata or {}
    try:
        init_database_tables()
        with _db_connect() as conn:
            conn.execute('''
                INSERT INTO youtube_subtitle_audits (
                    owner_user_id, job_id, video_id, video_title, target_language, initial_segments, reviewed_segments,
                    review_status, fallback_segment_count, review_batches, saved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(job_id) DO UPDATE SET
                    video_id = excluded.video_id, video_title = excluded.video_title,
                    target_language = excluded.target_language, initial_segments = excluded.initial_segments,
                    reviewed_segments = excluded.reviewed_segments, review_status = excluded.review_status,
                    fallback_segment_count = excluded.fallback_segment_count, review_batches = excluded.review_batches, saved_at = excluded.saved_at
            ''', (
                job.get("ownerUserId"), job_id, str(job.get("videoId") or ""), str(job.get("title") or ""),
                str(job.get("subtitleLanguage") or "zh-CN"),
                json.dumps(initial_segments or [], ensure_ascii=False),
                json.dumps(reviewed_segments or [], ensure_ascii=False),
                str(review_metadata.get("status") or "unknown"),
                max(0, int(review_metadata.get("fallbackCount") or 0)),
                json.dumps(review_metadata.get("batches") or [], ensure_ascii=False), _now_iso(),
            ))
            conn.commit()
    except Exception:
        backend_logger.exception("字幕审查快照保存失败 : jobId = %s", job_id)


def _subtitle_audit_sort_sql(value):
    return {
        "saved_desc": "COALESCE(a.saved_at, j.updated_at, j.started_at, j.created_at) DESC, j.id DESC",
        "saved_asc": "COALESCE(a.saved_at, j.updated_at, j.started_at, j.created_at) ASC, j.id ASC",
        "job_started_desc": "COALESCE(j.started_at, j.created_at) DESC, j.id DESC",
        "job_started_asc": "COALESCE(j.started_at, j.created_at) ASC, j.id ASC",
        "fallback_desc": "COALESCE(a.fallback_segment_count, 0) DESC, COALESCE(a.saved_at, j.updated_at) DESC, j.id DESC",
        "review_status_asc": "COALESCE(a.review_status, 'not_recorded') ASC, COALESCE(a.saved_at, j.updated_at) DESC, j.id DESC",
    }.get(str(value or "").strip(), "COALESCE(a.saved_at, j.updated_at, j.started_at, j.created_at) DESC, j.id DESC")


def list_subtitle_audits(owner_user_id, keyword="", status="", safety_status="", sort="saved_desc", page=1, page_size=20):
    owner_user_id = int(owner_user_id)
    if owner_user_id <= 0:
        raise ValueError("字幕审查归属账号必须是正整数")
    init_database_tables()
    page = _parse_positive_int(page, 1, 1, 999999)
    page_size = _parse_positive_int(page_size, 20, 1, 100)
    keyword = str(keyword or "").strip()
    status = str(status or "").strip()
    safety_status = str(safety_status or "").strip()
    clauses, params = ["j.owner_user_id = %s"], [owner_user_id]
    if keyword:
        clauses.append("(COALESCE(a.video_title, j.title) ILIKE %s OR COALESCE(a.video_id, j.video_id) ILIKE %s OR j.id ILIKE %s)")
        params.extend([f"%{keyword}%"] * 3)
    if status:
        clauses.append("COALESCE(a.review_status, 'not_recorded') = %s")
        params.append(status)
    if safety_status:
        clauses.append("COALESCE(s.status, 'not_enabled') = %s")
        params.append(safety_status)
    where = " AND ".join(clauses)
    order_by = _subtitle_audit_sort_sql(sort)
    with _db_connect() as conn:
        conn.row_factory = True
        total = conn.execute(f"SELECT COUNT(*) FROM youtube_workflow_jobs j LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id AND a.owner_user_id = j.owner_user_id LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id AND s.owner_user_id = j.owner_user_id WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f'''
            SELECT a.*, v.transcript_language AS source_language, s.snapshot AS content_safety_snapshot, s.status AS content_safety_status,
                   j.id AS workflow_job_id, j.video_id AS workflow_video_id, j.title AS workflow_title, j.channel AS workflow_channel, j.url AS workflow_url,
                   j.status AS job_status, j.started_at AS job_started_at, j.created_at AS job_created_at,
                   j.updated_at AS job_updated_at, j.comment_burn_enabled,
                   (SELECT e.metadata
                    FROM youtube_workflow_events e
                    WHERE e.owner_user_id = j.owner_user_id AND e.stage = 'source_title_translation' AND e.status = 'success'
                      AND (e.job_id = j.id OR (e.video_id = COALESCE(a.video_id, j.video_id) AND e.owner_user_id = j.owner_user_id))
                    ORDER BY CASE WHEN e.job_id = j.id THEN 0 ELSE 1 END, e.ended_at DESC NULLS LAST, e.id DESC
                    LIMIT 1) AS source_title_translation_metadata,
                   EXISTS(SELECT 1 FROM youtube_workflow_events e WHERE e.owner_user_id = j.owner_user_id AND e.job_id = j.id AND e.stage IN ('comment_fetch', 'comment_review')) AS has_comment_audit
            FROM youtube_workflow_jobs j
            LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id AND a.owner_user_id = j.owner_user_id
            LEFT JOIN youtube_videos v ON v.video_id = COALESCE(a.video_id, j.video_id) AND v.owner_user_id = j.owner_user_id
            LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id AND s.owner_user_id = j.owner_user_id
            WHERE {where}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        '''.format(where=where, order_by=order_by), [*params, page_size, (page - 1) * page_size]).fetchall()
    return {"items": [_subtitle_audit_list_item(dict(row)) for row in rows], "total": int(total), "page": page, "pageSize": page_size, "sort": str(sort or "saved_desc")}


def _subtitle_cleanup_path(raw_path, roots):
    candidate = Path(str(raw_path or ""))
    if not str(candidate):
        return None
    try:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
            return resolved
    except (OSError, ValueError):
        return None
    return None


def _subtitle_cleanup_files(video_rows, file_rows, owner_user_id, job_ids):
    roots = (YOUTUBE_DOWNLOAD_DIR, YOUTUBE_PROCESSED_DIR, YOUTUBE_TRANSCRIPT_DIR)
    candidates = []
    for video in video_rows:
        video_id = str(video.get("video_id") or "").strip()
        for key in ("downloaded_file_path", "processed_file_path", "editing_body_path", "editing_ass_path", "transcript_file_path"):
            if video.get(key):
                candidates.append((str(video[key]), video_id))
        if video_id:
            transcript_key = re.sub(r"[^A-Za-z0-9_-]+", "_", video_id)
            candidates.append((str(Path(YOUTUBE_TRANSCRIPT_DIR) / f"{transcript_key}.json"), video_id))
        download_path = _subtitle_cleanup_path(video.get("downloaded_file_path"), roots)
        if download_path:
            candidates.extend((str(download_path.with_suffix(extension)), video_id) for extension in (".webp", ".jpg", ".jpeg", ".png"))
    for record in file_rows:
        path = _material_file_path(dict(record))
        if path:
            candidates.append((str(path), str(record.get("source_video_id") or "")))

    deleted_file_count = 0
    errors = []
    for raw_path, video_id in candidates:
        path = _subtitle_cleanup_path(raw_path, roots)
        if not path or not path.is_file():
            continue
        if _retention_path_shared(path, video_id, owner_user_id):
            continue
        try:
            path.unlink()
            deleted_file_count += 1
        except OSError as exc:
            errors.append(f"{path.name}:{type(exc).__name__}")

    for job_id in job_ids:
        intro_dir = _subtitle_cleanup_path(Path(YOUTUBE_PROCESSED_DIR) / f"{job_id}_editing_intro", (YOUTUBE_PROCESSED_DIR,))
        if not intro_dir or not intro_dir.exists():
            continue
        try:
            shutil.rmtree(intro_dir)
        except OSError as exc:
            errors.append(f"{intro_dir.name}:{type(exc).__name__}")
    if errors:
        raise RuntimeError("清理视频中间文件失败 : " + ", ".join(errors[:10]))
    return deleted_file_count


def delete_subtitle_audits(owner_user_id, job_ids):
    owner_user_id = int(owner_user_id)
    if owner_user_id <= 0:
        raise ValueError("字幕审查归属账号必须是正整数")
    unique_job_ids = list(dict.fromkeys(
        str(job_id or "").strip() for job_id in (job_ids or []) if str(job_id or "").strip()
    ))
    if not unique_job_ids:
        raise ValueError("请至少选择一条审查记录")
    if len(unique_job_ids) > 100:
        raise ValueError("单次最多删除 100 条审查记录")
    init_database_tables()
    requested_placeholders = ", ".join("%s" for _ in unique_job_ids)
    with _db_connect() as conn:
        cursor = conn.cursor()
        selected_rows = cursor.execute(
            f"SELECT id, video_id, status FROM youtube_workflow_jobs WHERE owner_user_id = %s AND id IN ({requested_placeholders}) FOR UPDATE",
            [owner_user_id, *unique_job_ids],
        ).fetchall()
        if not selected_rows:
            return {"deletedCount": 0, "deletedJobCount": 0, "deletedMaterialCount": 0, "deletedFileCount": 0, "retainedPublishedPlatformCount": 0}

        video_ids = sorted({str(row["video_id"] or "").strip() for row in selected_rows if row["video_id"]})
        if not video_ids:
            return {"deletedCount": 0, "deletedJobCount": 0, "deletedMaterialCount": 0, "deletedFileCount": 0, "retainedPublishedPlatformCount": 0}
        video_placeholders = ", ".join("%s" for _ in video_ids)

        all_jobs = cursor.execute(
            f"SELECT id, video_id, status FROM youtube_workflow_jobs WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) FOR UPDATE",
            [owner_user_id, *video_ids],
        ).fetchall()
        active_statuses = {"queued", "running", "waiting_confirmation", "waiting_publish"}
        active_ids = [row["id"] for row in all_jobs if str(row["status"] or "").lower() in active_statuses]
        if active_ids:
            raise ValueError("运行中或待确认的任务不能清理")

        scheduled = cursor.execute(
            f"SELECT 1 FROM scheduled_publish_tasks WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) AND status IN ('scheduled', 'queued', 'running') LIMIT 1",
            [owner_user_id, *video_ids],
        ).fetchone()
        if scheduled:
            raise ValueError("存在进行中的定时发布任务，不能清理")

        uncertain = cursor.execute(
            f"SELECT 1 FROM published_youtube_materials WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) AND deleted_at IS NULL AND invalidated_at IS NULL AND status IN ('unknown', 'pending', 'running', 'uncertain', 'queued') LIMIT 1",
            [owner_user_id, *video_ids],
        ).fetchone()
        if uncertain:
            raise ValueError("存在状态未确认的平台发布记录，不能清理")

        video_rows = [dict(row) for row in cursor.execute(
            f"SELECT * FROM youtube_videos WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) FOR UPDATE",
            [owner_user_id, *video_ids],
        ).fetchall()]
        file_rows = [dict(row) for row in cursor.execute(
            f"SELECT * FROM file_records WHERE owner_user_id = %s AND source_video_id IN ({video_placeholders}) AND source_type IN ('youtube_download', 'youtube_processed')",
            [owner_user_id, *video_ids],
        ).fetchall()]
        all_job_ids = [str(row["id"]) for row in all_jobs]
        deleted_file_count = _subtitle_cleanup_files(video_rows, file_rows, owner_user_id, all_job_ids)

        if all_job_ids:
            job_placeholders = ", ".join("%s" for _ in all_job_ids)
            for table in ("youtube_workflow_llm_usage_events", "youtube_workflow_events", "youtube_subtitle_audits", "youtube_content_safety_audits", "youtube_workflow_locks"):
                cursor.execute(f"DELETE FROM {table} WHERE owner_user_id = %s AND job_id IN ({job_placeholders})", [owner_user_id, *all_job_ids])
            cursor.execute(f"DELETE FROM youtube_workflow_jobs WHERE owner_user_id = %s AND id IN ({job_placeholders})", [owner_user_id, *all_job_ids])

        cursor.execute(
            f"DELETE FROM file_records WHERE owner_user_id = %s AND source_video_id IN ({video_placeholders}) AND source_type IN ('youtube_download', 'youtube_processed')",
            [owner_user_id, *video_ids],
        )
        deleted_material_count = cursor.execute(
            f"DELETE FROM published_youtube_materials WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) AND NOT (deleted_at IS NULL AND invalidated_at IS NULL AND status IN ('confirmed', 'reused'))",
            [owner_user_id, *video_ids],
        ).rowcount
        retained_count = cursor.execute(
            f"SELECT COUNT(*) FROM published_youtube_materials WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) AND deleted_at IS NULL AND invalidated_at IS NULL AND status IN ('confirmed', 'reused')",
            [owner_user_id, *video_ids],
        ).fetchone()[0]
        cursor.execute(
            f"UPDATE published_youtube_materials SET material_id = NULL, filename = '', file_path = '', filesize = 0, thumbnail = '', account_file = '', metadata = '{{}}', updated_at = CURRENT_TIMESTAMP WHERE owner_user_id = %s AND video_id IN ({video_placeholders}) AND deleted_at IS NULL AND invalidated_at IS NULL AND status IN ('confirmed', 'reused')",
            [owner_user_id, *video_ids],
        )

        for video_id in video_ids:
            cursor.execute(
                """
                UPDATE youtube_videos
                SET download_status = 0, translate_status = 0, transcript_status = 0,
                    downloaded_file_path = '', processed_file_path = '', transcript_file_path = '',
                    transcript_language = '', analysis_status = 0, analysis_result = '', publish_draft = '',
                    analysis_updated_at = NULL, editing_body_path = '', editing_ass_path = '',
                    editing_body_signature = '', editing_intro_signature = '', editing_highlight_snapshot = '[]',
                    editing_intro_status = '', comment_burn_snapshot = '{}', comment_burn_signature = '',
                    comment_burn_status = '', local_files_state = 'purged', local_files_purged_at = CURRENT_TIMESTAMP,
                    purge_attempted_at = CURRENT_TIMESTAMP, purge_error = '',
                    publish_status = CASE WHEN EXISTS (
                        SELECT 1 FROM published_youtube_materials
                        WHERE owner_user_id = %s AND video_id = %s AND deleted_at IS NULL
                          AND invalidated_at IS NULL AND status IN ('confirmed', 'reused')
                    ) THEN 1 ELSE 0 END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE owner_user_id = %s AND video_id = %s
                """,
                (owner_user_id, video_id, owner_user_id, video_id),
            )
        conn.commit()
    return {
        "deletedCount": len(all_job_ids),
        "deletedJobCount": len(all_job_ids),
        "deletedMaterialCount": max(0, int(deleted_material_count or 0)),
        "deletedFileCount": deleted_file_count,
        "retainedPublishedPlatformCount": int(retained_count or 0),
    }


def _subtitle_audit_list_item(row):
    safety = _subtitle_audit_json(row.get("content_safety_snapshot"), "{}")
    translation_metadata = _subtitle_audit_json(row.get("source_title_translation_metadata"), "{}")
    original_title = row.get("workflow_title") or row.get("video_title") or row.get("video_id") or row.get("workflow_video_id") or "未命名视频"
    return {
        "jobId": row.get("job_id") or row.get("workflow_job_id") or "", "videoId": row.get("video_id") or row.get("workflow_video_id") or "", "url": row.get("workflow_url") or "",
        "title": original_title, "originalTitle": original_title,
        "chineseTitle": (
            str(translation_metadata.get("sourceTitleZh") or "").strip()
            if _is_valid_source_title_translation(translation_metadata.get("sourceTitleZh"))
            else ""
        ),
        "author": row.get("workflow_channel") or "",
        "targetLanguage": row.get("target_language") or "", "sourceLanguage": _normalize_source_language(row.get("source_language")), "reviewStatus": row.get("review_status") or "not_recorded",
        "fallbackSegmentCount": int(row.get("fallback_segment_count") or 0),
        "savedAt": _to_beijing_iso(row.get("saved_at") or row.get("job_updated_at") or row.get("job_started_at") or row.get("job_created_at")), "jobStatus": row.get("job_status") or "",
        "jobStartedAt": _to_beijing_iso(row.get("job_started_at") or row.get("job_created_at")),
        "commentBurnEnabled": bool(row.get("comment_burn_enabled")), "hasCommentAudit": bool(row.get("has_comment_audit")),
        "contentSafetyStatus": row.get("content_safety_status") or safety.get("status") or "not_enabled",
        "contentSafetyRiskCount": len(safety.get("risks") or []), "contentSafetyDecision": safety.get("decision") or "",
    }


def get_subtitle_audit_detail(owner_user_id, job_id):
    owner_user_id = int(owner_user_id)
    if owner_user_id <= 0:
        raise ValueError("字幕审查归属账号必须是正整数")
    init_database_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute('''
            SELECT a.*, v.transcript_language AS source_language, s.snapshot AS content_safety_snapshot, s.status AS content_safety_status,
                   j.id AS workflow_job_id, j.video_id AS workflow_video_id, j.title AS workflow_title, j.channel AS workflow_channel, j.url AS workflow_url,
                   j.status AS job_status, j.started_at AS job_started_at, j.created_at AS job_created_at,
                   j.updated_at AS job_updated_at, j.comment_burn_enabled,
                   (SELECT e.metadata
                    FROM youtube_workflow_events e
                    WHERE e.owner_user_id = j.owner_user_id AND e.stage = 'source_title_translation' AND e.status = 'success'
                      AND (e.job_id = j.id OR (e.video_id = COALESCE(a.video_id, j.video_id) AND e.owner_user_id = j.owner_user_id))
                    ORDER BY CASE WHEN e.job_id = j.id THEN 0 ELSE 1 END, e.ended_at DESC NULLS LAST, e.id DESC
                    LIMIT 1) AS source_title_translation_metadata,
                   EXISTS(SELECT 1 FROM youtube_workflow_events e WHERE e.owner_user_id = j.owner_user_id AND e.job_id = j.id AND e.stage IN ('comment_fetch', 'comment_review')) AS has_comment_audit
            FROM youtube_workflow_jobs j LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id AND a.owner_user_id = j.owner_user_id
            LEFT JOIN youtube_videos v ON v.video_id = COALESCE(a.video_id, j.video_id) AND v.owner_user_id = j.owner_user_id
            LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id AND s.owner_user_id = j.owner_user_id
            WHERE j.owner_user_id = %s AND j.id = %s
        ''', (owner_user_id, str(job_id or ""))).fetchone()
        if not row:
            return None
        diagnostics = conn.execute('''
            SELECT operation, model, attempt, prompt_tokens, completion_tokens, total_tokens,
                   latency_ms, error_category, violations, raw_output, created_at
            FROM youtube_workflow_llm_usage_events
            WHERE owner_user_id = %s AND job_id = %s AND status IN ('contract_failed', 'soft_warning') AND raw_output <> ''
            ORDER BY created_at DESC, id DESC
        ''', (owner_user_id, str(job_id or ""))).fetchall()
        comment_events = conn.execute('''
            SELECT metadata FROM youtube_workflow_events
            WHERE owner_user_id = %s AND job_id = %s AND stage IN ('comment_review', 'comment_fetch')
            ORDER BY CASE stage WHEN 'comment_review' THEN 0 ELSE 1 END, id DESC
        ''', (owner_user_id, str(job_id or ""))).fetchall()
    result = _subtitle_audit_list_item(dict(row))
    result["initialSegments"] = _subtitle_audit_json(row["initial_segments"], "[]")
    result["reviewedSegments"] = _subtitle_audit_json(row["reviewed_segments"], "[]")
    result["reviewBatches"] = _subtitle_audit_json(row["review_batches"], "[]")
    result["contentSafety"] = _subtitle_audit_json(row.get("content_safety_snapshot"), "{}")
    comment_metadata = {}
    for comment_event in comment_events:
        candidate = _subtitle_audit_json(comment_event["metadata"], "{}")
        if not comment_metadata and isinstance(candidate, dict):
            comment_metadata = candidate
        if isinstance(candidate, dict) and isinstance(candidate.get("reviewItems"), list):
            comment_metadata = candidate
            break
    result["commentReviewItems"] = comment_metadata.get("reviewItems") if isinstance(comment_metadata, dict) else []
    result["commentReviewMeta"] = comment_metadata if isinstance(comment_metadata, dict) else {}
    result["diagnostics"] = [{
        "operation": item["operation"] or "", "model": item["model"] or "", "attempt": int(item["attempt"] or 1),
        "promptTokens": int(item["prompt_tokens"] or 0), "completionTokens": int(item["completion_tokens"] or 0),
        "totalTokens": int(item["total_tokens"] or 0), "latencyMs": float(item["latency_ms"] or 0),
        "category": item["error_category"] or "", "violations": _subtitle_audit_json(item["violations"], "[]"),
        "rawOutput": item["raw_output"] or "", "createdAt": _to_beijing_iso(item["created_at"]),
    } for item in diagnostics]
    return result
