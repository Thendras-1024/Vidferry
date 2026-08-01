"""管理员字幕审查快照与模型失败诊断查询。"""


def _subtitle_audit_json(value, fallback):
    try:
        return json.loads(value or fallback)
    except (TypeError, ValueError):
        return json.loads(fallback)


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
        "saved_desc": "a.saved_at DESC, a.job_id DESC",
        "saved_asc": "a.saved_at ASC, a.job_id ASC",
        "job_started_desc": "COALESCE(j.started_at, a.saved_at) DESC, a.job_id DESC",
        "job_started_asc": "COALESCE(j.started_at, a.saved_at) ASC, a.job_id ASC",
        "fallback_desc": "a.fallback_segment_count DESC, a.saved_at DESC, a.job_id DESC",
        "review_status_asc": "a.review_status ASC, a.saved_at DESC, a.job_id DESC",
    }.get(str(value or "").strip(), "a.saved_at DESC, a.job_id DESC")


def list_subtitle_audits(keyword="", status="", sort="saved_desc", page=1, page_size=20):
    init_database_tables()
    page = _parse_positive_int(page, 1, 1, 999999)
    page_size = _parse_positive_int(page_size, 20, 1, 100)
    keyword = str(keyword or "").strip()
    status = str(status or "").strip()
    clauses, params = ["1 = 1"], []
    if keyword:
        clauses.append("(a.video_title LIKE ? OR a.video_id LIKE ? OR a.job_id LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)
    if status:
        clauses.append("a.review_status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    order_by = _subtitle_audit_sort_sql(sort)
    with _db_connect() as conn:
        conn.row_factory = True
        total = conn.execute(f"SELECT COUNT(*) FROM youtube_subtitle_audits a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f'''
            SELECT a.*, j.status AS job_status, j.started_at AS job_started_at
            FROM youtube_subtitle_audits a
            LEFT JOIN youtube_workflow_jobs j ON j.id = a.job_id
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
        cursor = conn.execute(
            f"DELETE FROM youtube_subtitle_audits WHERE job_id IN ({placeholders})",
            unique_job_ids,
        )
        conn.commit()
    return {"deletedCount": max(0, int(cursor.rowcount or 0))}


def _subtitle_audit_list_item(row):
    return {
        "jobId": row.get("job_id") or "", "videoId": row.get("video_id") or "",
        "title": row.get("video_title") or row.get("video_id") or "未命名视频",
        "targetLanguage": row.get("target_language") or "", "reviewStatus": row.get("review_status") or "unknown",
        "fallbackSegmentCount": int(row.get("fallback_segment_count") or 0),
        "savedAt": row.get("saved_at") or "", "jobStatus": row.get("job_status") or "",
        "jobStartedAt": row.get("job_started_at") or "",
    }


def get_subtitle_audit_detail(job_id):
    init_database_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute('''
            SELECT a.*, j.status AS job_status, j.started_at AS job_started_at
            FROM youtube_subtitle_audits a LEFT JOIN youtube_workflow_jobs j ON j.id = a.job_id
            WHERE a.job_id = ?
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
    result = _subtitle_audit_list_item(dict(row))
    result["initialSegments"] = _subtitle_audit_json(row["initial_segments"], "[]")
    result["reviewedSegments"] = _subtitle_audit_json(row["reviewed_segments"], "[]")
    result["reviewBatches"] = _subtitle_audit_json(row["review_batches"], "[]")
    result["diagnostics"] = [{
        "operation": item["operation"] or "", "model": item["model"] or "", "attempt": int(item["attempt"] or 1),
        "promptTokens": int(item["prompt_tokens"] or 0), "completionTokens": int(item["completion_tokens"] or 0),
        "totalTokens": int(item["total_tokens"] or 0), "latencyMs": float(item["latency_ms"] or 0),
        "category": item["error_category"] or "", "violations": _subtitle_audit_json(item["violations"], "[]"),
        "rawOutput": item["raw_output"] or "", "createdAt": item["created_at"] or "",
    } for item in diagnostics]
    return result
