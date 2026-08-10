"""管理员字幕审查快照与模型失败诊断查询。"""


def _subtitle_audit_json(value, fallback):
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
                    job_id, video_id, video_title, target_language, initial_segments, reviewed_segments,
                    review_status, fallback_segment_count, review_batches, saved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    video_id = excluded.video_id, video_title = excluded.video_title,
                    target_language = excluded.target_language, initial_segments = excluded.initial_segments,
                    reviewed_segments = excluded.reviewed_segments, review_status = excluded.review_status,
                    fallback_segment_count = excluded.fallback_segment_count, review_batches = excluded.review_batches, saved_at = excluded.saved_at
            ''', (
                job_id, str(job.get("videoId") or ""), str(job.get("title") or ""),
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


def list_subtitle_audits(keyword="", status="", safety_status="", sort="saved_desc", page=1, page_size=20):
    init_database_tables()
    page = _parse_positive_int(page, 1, 1, 999999)
    page_size = _parse_positive_int(page_size, 20, 1, 100)
    keyword = str(keyword or "").strip()
    status = str(status or "").strip()
    safety_status = str(safety_status or "").strip()
    clauses, params = ["1 = 1"], []
    if keyword:
        clauses.append("(COALESCE(a.video_title, j.title) LIKE ? OR COALESCE(a.video_id, j.video_id) LIKE ? OR j.id LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    if status:
        clauses.append("COALESCE(a.review_status, 'not_recorded') = ?")
        params.append(status)
    if safety_status:
        clauses.append("COALESCE(s.status, 'not_enabled') = ?")
        params.append(safety_status)
    where = " AND ".join(clauses)
    order_by = _subtitle_audit_sort_sql(sort)
    with _db_connect() as conn:
        conn.row_factory = True
        total = conn.execute(f"SELECT COUNT(*) FROM youtube_workflow_jobs j LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f'''
            SELECT a.*, v.transcript_language AS source_language, s.snapshot AS content_safety_snapshot, s.status AS content_safety_status,
                   j.id AS workflow_job_id, j.video_id AS workflow_video_id, j.title AS workflow_title, j.url AS workflow_url,
                   j.status AS job_status, j.started_at AS job_started_at, j.created_at AS job_created_at,
                   j.updated_at AS job_updated_at, j.comment_burn_enabled,
                   EXISTS(SELECT 1 FROM youtube_workflow_events e WHERE e.job_id = j.id AND e.stage IN ('comment_fetch', 'comment_review')) AS has_comment_audit
            FROM youtube_workflow_jobs j
            LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id
            LEFT JOIN youtube_videos v ON v.video_id = COALESCE(a.video_id, j.video_id)
            LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        '''.format(where=where, order_by=order_by), [*params, page_size, (page - 1) * page_size]).fetchall()
    return {"items": [_subtitle_audit_list_item(dict(row)) for row in rows], "total": int(total), "page": page, "pageSize": page_size, "sort": str(sort or "saved_desc")}


def delete_subtitle_audits(job_ids):
    unique_job_ids = list(dict.fromkeys(
        str(job_id or "").strip() for job_id in (job_ids or []) if str(job_id or "").strip()
    ))
    if not unique_job_ids:
        raise ValueError("请至少选择一条审查记录")
    if len(unique_job_ids) > 100:
        raise ValueError("单次最多删除 100 条审查记录")
    init_database_tables()
    placeholders = ", ".join("?" for _ in unique_job_ids)
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        rows = cursor.execute(
            f"SELECT id, video_id, status FROM youtube_workflow_jobs WHERE id IN ({placeholders})",
            unique_job_ids,
        ).fetchall()
        active_ids = [row["id"] for row in rows if row["status"] in {"queued", "running", "waiting_confirmation"}]
        if active_ids:
            raise ValueError("运行中或待确认的任务不能删除")
        video_ids = {str(row["video_id"] or "") for row in rows if row["video_id"]}
        for table in ("youtube_workflow_llm_usage_events", "youtube_workflow_events", "youtube_subtitle_audits", "youtube_workflow_locks"):
            cursor.execute(f"DELETE FROM {table} WHERE job_id IN ({placeholders})", unique_job_ids)
        cursor.execute(f"DELETE FROM youtube_workflow_jobs WHERE id IN ({placeholders})", unique_job_ids)
        for video_id in video_ids:
            if cursor.execute("SELECT 1 FROM youtube_workflow_jobs WHERE video_id = ? LIMIT 1", (video_id,)).fetchone():
                continue
            cursor.execute(
                "UPDATE youtube_videos SET comment_burn_snapshot = ?, comment_burn_signature = ?, comment_burn_status = ?, updated_at = CURRENT_TIMESTAMP WHERE video_id = ?",
                ("{}", "", "", video_id),
            )
        conn.commit()
    return {"deletedCount": max(0, int(cursor.rowcount or 0))}


def _subtitle_audit_list_item(row):
    safety = _subtitle_audit_json(row.get("content_safety_snapshot"), "{}")
    return {
        "jobId": row.get("job_id") or row.get("workflow_job_id") or "", "videoId": row.get("video_id") or row.get("workflow_video_id") or "", "url": row.get("workflow_url") or "",
        "title": row.get("video_title") or row.get("workflow_title") or row.get("video_id") or row.get("workflow_video_id") or "未命名视频",
        "targetLanguage": row.get("target_language") or "", "sourceLanguage": _normalize_source_language(row.get("source_language")), "reviewStatus": row.get("review_status") or "not_recorded",
        "fallbackSegmentCount": int(row.get("fallback_segment_count") or 0),
        "savedAt": row.get("saved_at") or row.get("job_updated_at") or row.get("job_started_at") or row.get("job_created_at") or "", "jobStatus": row.get("job_status") or "",
        "jobStartedAt": row.get("job_started_at") or row.get("job_created_at") or "",
        "commentBurnEnabled": bool(row.get("comment_burn_enabled")), "hasCommentAudit": bool(row.get("has_comment_audit")),
        "contentSafetyStatus": row.get("content_safety_status") or safety.get("status") or "not_enabled",
        "contentSafetyRiskCount": len(safety.get("risks") or []), "contentSafetyDecision": safety.get("decision") or "",
    }


def get_subtitle_audit_detail(job_id):
    init_database_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute('''
            SELECT a.*, v.transcript_language AS source_language, s.snapshot AS content_safety_snapshot, s.status AS content_safety_status,
                   j.id AS workflow_job_id, j.video_id AS workflow_video_id, j.title AS workflow_title, j.url AS workflow_url,
                   j.status AS job_status, j.started_at AS job_started_at, j.created_at AS job_created_at,
                   j.updated_at AS job_updated_at, j.comment_burn_enabled,
                   EXISTS(SELECT 1 FROM youtube_workflow_events e WHERE e.job_id = j.id AND e.stage IN ('comment_fetch', 'comment_review')) AS has_comment_audit
            FROM youtube_workflow_jobs j LEFT JOIN youtube_subtitle_audits a ON a.job_id = j.id
            LEFT JOIN youtube_videos v ON v.video_id = COALESCE(a.video_id, j.video_id)
            LEFT JOIN youtube_content_safety_audits s ON s.job_id = j.id
            WHERE j.id = ?
        ''', (str(job_id or ""),)).fetchone()
        if not row:
            return None
        diagnostics = conn.execute('''
            SELECT operation, model, attempt, prompt_tokens, completion_tokens, total_tokens,
                   latency_ms, error_category, violations, raw_output, created_at
            FROM youtube_workflow_llm_usage_events
            WHERE job_id = ? AND status IN ('contract_failed', 'soft_warning') AND raw_output <> ''
            ORDER BY created_at DESC, id DESC
        ''', (str(job_id or ""),)).fetchall()
        comment_events = conn.execute('''
            SELECT metadata FROM youtube_workflow_events
            WHERE job_id = ? AND stage IN ('comment_review', 'comment_fetch')
            ORDER BY CASE stage WHEN 'comment_review' THEN 0 ELSE 1 END, id DESC
        ''', (str(job_id or ""),)).fetchall()
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
        "rawOutput": item["raw_output"] or "", "createdAt": item["created_at"] or "",
    } for item in diagnostics]
    return result
