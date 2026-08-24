"""YouTube 视频线索的存储、状态流转与列表查询(含阶段排序与状态对账)。"""


def _local_youtube_thumbnail_path(video_id, downloaded_file_path=""):
    candidates = [Path(downloaded_file_path)] if downloaded_file_path else []
    if video_id:
        candidates.append(Path(YOUTUBE_DOWNLOAD_DIR) / f"{video_id}.mp4")
    for candidate in candidates:
        for extension in (".webp", ".jpg", ".jpeg", ".png"):
            thumbnail_path = candidate.with_suffix(extension)
            if thumbnail_path.is_file():
                return str(thumbnail_path)
    return ""


def _row_to_youtube_video(row):
    item = dict(row)
    analysis_result = _parse_json_object(item.get("analysis_result"))
    publish_draft = _parse_publish_draft(item.get("publish_draft"), analysis_result)
    try:
        editing_highlight_snapshot = json.loads(item.get("editing_highlight_snapshot") or "[]")
    except (TypeError, ValueError):
        editing_highlight_snapshot = []
    if not isinstance(editing_highlight_snapshot, list):
        editing_highlight_snapshot = []
    comment_burn_snapshot = _parse_json_object(item.get("comment_burn_snapshot"))
    video_id = item.get("video_id") or ""
    downloaded_file_path = item.get("downloaded_file_path") or ""
    return {
        "dbId": item.get("id"),
        "id": video_id,
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "subscribers": _format_subscribers_w(item.get("subscribers")),
        "publishedAt": item.get("published_at") or "",
        "url": item.get("url") or "",
        # hqdefault 对所有公开视频都可用；搜索结果中的 maxresdefault 并不保证存在。
        "thumbnail": _youtube_thumbnail_url(video_id) or item.get("thumbnail") or "",
        "duration": item.get("duration") or "",
        "query": item.get("query") or "",
        "groupId": item.get("group_id"),
        "groupName": item.get("group_name") or "",
        "groupIsDefault": bool(item.get("group_is_default") or 0),
        "downloadStatus": int(item.get("download_status") or 0),
        "publishStatus": int(item.get("publish_status") or 0),
        "translateStatus": int(item.get("translate_status") or 0),
        "downloadedFilePath": downloaded_file_path,
        "localThumbnailPath": _local_youtube_thumbnail_path(video_id, downloaded_file_path),
        "processedFilePath": item.get("processed_file_path") or "",
        "transcriptStatus": int(item.get("transcript_status") or 0),
        "transcriptFilePath": item.get("transcript_file_path") or "",
        "transcriptLanguage": item.get("transcript_language") or "",
        "analysisStatus": int(item.get("analysis_status") or 0),
        "hasAnalysis": int(item.get("analysis_status") or 0) == 1,
        "analysisResult": analysis_result,
        "publishDraft": publish_draft,
        "analysisUpdatedAt": item.get("analysis_updated_at") or "",
        "editingBodyPath": item.get("editing_body_path") or "",
        "editingAssPath": item.get("editing_ass_path") or "",
        "editingBodySignature": item.get("editing_body_signature") or "",
        "editingIntroSignature": item.get("editing_intro_signature") or "",
        "editingHighlightSnapshot": editing_highlight_snapshot,
        "editingIntroStatus": item.get("editing_intro_status") or "",
        "commentBurnSnapshot": comment_burn_snapshot,
        "commentBurnSignature": item.get("comment_burn_signature") or "",
        "commentBurnStatus": item.get("comment_burn_status") or "",
        "localFilesState": item.get("local_files_state") or "available",
        "retentionAnchorAt": item.get("retention_anchor_at") or "",
        "localFilesPurgedAt": item.get("local_files_purged_at") or "",
        "purgeError": item.get("purge_error") or "",
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def get_youtube_comment_burn_snapshot(video_id, owner_user_id=None):
    if not video_id:
        return {}
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute(
            "SELECT comment_burn_snapshot, comment_burn_signature, comment_burn_status FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s",
            (video_id, owner_user_id),
        ).fetchone()
    if not row:
        return {}
    snapshot = _parse_json_object(row["comment_burn_snapshot"])
    return {
        **snapshot,
        "signature": row["comment_burn_signature"] or "",
        "status": row["comment_burn_status"] or snapshot.get("status") or "",
    }


def save_youtube_comment_burn_snapshot(video_id, snapshot, signature="", status="", owner_user_id=None):
    if not video_id:
        return
    init_youtube_video_table()
    value = snapshot if isinstance(snapshot, dict) else {}
    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE youtube_videos
            SET comment_burn_snapshot = %s, comment_burn_signature = %s, comment_burn_status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE video_id = %s AND owner_user_id = %s
            """,
            (json.dumps(value, ensure_ascii=False), str(signature or ""), str(status or value.get("status") or ""), video_id, owner_user_id),
        )
        conn.commit()


def save_new_youtube_videos(videos, query, owner_user_id, group_id=None):
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        target_group = _resolve_youtube_group(cursor, owner_user_id, group_id)
        normalized_videos = []
        seen_ids = set()
        for video in videos:
            video_id = video.get("id")
            url = video.get("url")
            if not video_id or not url:
                continue
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            normalized_videos.append(video)

        if not normalized_videos:
            return {"items": [], "created": 0, "duplicate": 0, "requested": len(videos)}

        ids = [video.get("id") for video in normalized_videos]
        placeholders = ",".join("%s" for _ in ids)
        cursor.execute(f"SELECT video_id FROM youtube_videos WHERE owner_user_id = %s AND video_id IN ({placeholders})", [owner_user_id, *ids])
        existing_ids = {row["video_id"] for row in cursor.fetchall()}
        published_ids, published_urls = _published_youtube_identity_sets(cursor, owner_user_id)
        published_duplicate_count = sum(
            1
            for video in normalized_videos
            if video.get("id") in published_ids
            or _canonical_youtube_url(video.get("url") or "", video.get("id") or "") in published_urls
        )
        new_videos = [
            video
            for video in normalized_videos
            if video.get("id") not in existing_ids
            and video.get("id") not in published_ids
            and _canonical_youtube_url(video.get("url") or "", video.get("id") or "") not in published_urls
        ]

        for video in new_videos:
            video_id = video.get("id")
            url = video.get("url")
            cursor.execute('''
            INSERT INTO youtube_videos (
                video_id, title, channel, subscribers, published_at, url, thumbnail, duration, query, group_id, owner_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                video_id,
                video.get("title") or "",
                video.get("channel") or "",
                _format_subscribers_w(video.get("subscribers")),
                video.get("publishedAt") or "",
                url,
                video.get("thumbnail") or "",
                video.get("duration") or "",
                query,
                target_group["id"],
                owner_user_id,
            ))
        conn.commit()

        if not new_videos:
            return {
                "items": [],
                "created": 0,
                "duplicate": len(normalized_videos),
                "publishedDuplicate": published_duplicate_count,
                "requested": len(videos),
            }

        new_ids = [video.get("id") for video in new_videos]
        placeholders = ",".join("%s" for _ in new_ids)
        cursor.execute(f'''
        SELECT youtube_videos.*, %s AS group_name, %s AS group_is_default
        FROM youtube_videos
        WHERE owner_user_id = %s AND video_id IN ({placeholders})
        ORDER BY CASE video_id {' '.join(f'WHEN %s THEN {index}' for index, _ in enumerate(new_ids))} END
        ''', [target_group["name"], target_group["is_default"], owner_user_id, *new_ids, *new_ids])
        result = {
            "items": [_row_to_youtube_video(row) for row in cursor.fetchall()],
            "created": len(new_videos),
            "duplicate": len(normalized_videos) - len(new_videos),
            "publishedDuplicate": published_duplicate_count,
            "requested": len(videos),
        }
        _queue_source_title_translations(owner_user_id, result["items"], _TITLE_TRANSLATION_PAGE_LIMIT)
        return result


def _save_one_youtube_video_with_cursor(cursor, video, query, owner_user_id, job_created_at="", group_id=None):
    video_id = str(video.get("id") or "").strip()
    url = str(video.get("url") or "").strip()
    if not video_id or not url:
        return {"decision": "skipped", "item": None}
    target_group = _resolve_youtube_group(cursor, owner_user_id, group_id)

    if job_created_at:
        cursor.execute(
            "SELECT deleted_at FROM youtube_video_deletions WHERE video_id = %s AND owner_user_id = %s",
            (video_id, owner_user_id),
        )
        deletion = cursor.fetchone()
        deleted_at = deletion["deleted_at"] if deletion else ""
        if deleted_at and str(deleted_at) >= str(job_created_at):
            return {"decision": "skipped", "item": None}

    cursor.execute('''
    SELECT youtube_videos.*, groups.name AS group_name, groups.is_default AS group_is_default
    FROM youtube_videos
    LEFT JOIN youtube_video_groups groups ON groups.id = youtube_videos.group_id
    WHERE youtube_videos.video_id = %s AND youtube_videos.owner_user_id = %s
    ''', (video_id, owner_user_id))
    existing = cursor.fetchone()
    published_ids, published_urls = _published_youtube_identity_sets(cursor, owner_user_id)
    canonical_url = _canonical_youtube_url(url, video_id)
    if existing or video_id in published_ids or canonical_url in published_urls:
        return {
            "decision": "duplicate",
            "item": _row_to_youtube_video(existing) if existing else None,
        }

    cursor.execute('''
    INSERT INTO youtube_videos (
        video_id, title, channel, subscribers, published_at, url, thumbnail, duration, query, group_id, owner_user_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        video_id,
        video.get("title") or "",
        video.get("channel") or "",
        _format_subscribers_w(video.get("subscribers")),
        video.get("publishedAt") or "",
        url,
        video.get("thumbnail") or "",
        video.get("duration") or "",
        query,
        target_group["id"],
        owner_user_id,
    ))
    cursor.execute('''
    SELECT youtube_videos.*, groups.name AS group_name, groups.is_default AS group_is_default
    FROM youtube_videos
    LEFT JOIN youtube_video_groups groups ON groups.id = youtube_videos.group_id
    WHERE youtube_videos.video_id = %s AND youtube_videos.owner_user_id = %s
    ''', (video_id, owner_user_id))
    return {"decision": "created", "item": _row_to_youtube_video(cursor.fetchone())}


def save_one_youtube_video(video, query, owner_user_id, job_created_at="", group_id=None):
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        _resolve_youtube_group(cursor, owner_user_id, group_id)
        result = _save_one_youtube_video_with_cursor(cursor, video, query, owner_user_id, job_created_at, group_id)
    if result.get("decision") == "created" and result.get("item"):
        _queue_source_title_translations(owner_user_id, [result["item"]], 1)
    return result


def upsert_youtube_videos(videos, query, owner_user_id):
    result = save_new_youtube_videos(videos, query, owner_user_id)
    return result["items"]


def _youtube_video_status_clause(status):
    active_job_sql = """video_id IN (
            SELECT video_id FROM youtube_workflow_jobs
            WHERE owner_user_id = youtube_videos.owner_user_id
              AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish') AND video_id IS NOT NULL AND video_id != ''
        )"""
    failed_job_sql = _relevant_job_status_exists_sql("failed")
    abnormal_job_sql = _relevant_job_status_exists_sql("abnormal")
    failed_or_abnormal_sql = f"({failed_job_sql} OR {abnormal_job_sql})"
    if status == "initial":
        return f"""(download_status IS NULL OR download_status != 1)
            AND (translate_status IS NULL OR translate_status NOT IN (1, 2))
            AND (publish_status IS NULL OR publish_status != 1)
            AND NOT ({active_job_sql})
            AND NOT {failed_or_abnormal_sql}""", []
    if status == "processed":
        return "translate_status = 1 AND (publish_status IS NULL OR publish_status != 1)", []
    if status == "failed":
        return failed_job_sql, []
    if status == "abnormal":
        return abnormal_job_sql, []
    if status == "notDownloaded":
        return "(download_status IS NULL OR download_status != 1)", []
    if status == "downloaded":
        return "download_status = 1 AND (translate_status IS NULL OR translate_status NOT IN (1, 2)) AND (publish_status IS NULL OR publish_status != 1)", []
    if status == "notTranslated":
        return "(translate_status IS NULL OR translate_status NOT IN (1, 2))", []
    if status == "translated":
        return "translate_status = 1", []
    if status == "translationSkipped":
        return "translate_status = 2", []
    if status == "notPublished":
        return "(publish_status IS NULL OR publish_status != 1)", []
    if status == "published":
        return "publish_status = 1", []
    if status == "running":
        return active_job_sql, []
    return "", []


def _published_newest_order_sql():
    return """
    NULLIF(published_at, '') DESC NULLS LAST,
    created_at DESC,
    id DESC
    """


def _active_job_exists_sql():
    return """EXISTS (
        SELECT 1 FROM youtube_workflow_jobs job
        WHERE job.video_id = youtube_videos.video_id
          AND job.owner_user_id = youtube_videos.owner_user_id
          AND job.status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
    )"""


def _job_status_exists_sql(status):
    return f"""EXISTS (
        SELECT 1 FROM youtube_workflow_jobs job
        WHERE job.video_id = youtube_videos.video_id
          AND job.owner_user_id = youtube_videos.owner_user_id
          AND job.status = '{status}'
    )"""


def _relevant_job_status_exists_sql(status):
    return f"""EXISTS (
        SELECT 1 FROM youtube_workflow_jobs job
        WHERE job.video_id = youtube_videos.video_id
          AND job.owner_user_id = youtube_videos.owner_user_id
          AND job.status = '{status}'
          AND (
            (COALESCE(youtube_videos.download_status, 0) != 1 AND COALESCE(job.step, '') IN ('queued', 'download', 'failed'))
            OR (COALESCE(youtube_videos.download_status, 0) = 1
                AND COALESCE(youtube_videos.translate_status, 0) NOT IN (1, 2)
                AND COALESCE(job.step, '') IN ('queued', 'subtitle', 'analysis', 'editing', 'failed'))
            OR (COALESCE(youtube_videos.translate_status, 0) IN (1, 2)
                AND COALESCE(youtube_videos.publish_status, 0) != 1
                AND COALESCE(job.step, '') IN ('publish', 'failed'))
          )
    )"""


def _default_stage_order_sql():
    return f"""
    CASE
        WHEN {_relevant_job_status_exists_sql('failed')} OR {_relevant_job_status_exists_sql('abnormal')} THEN 0
        WHEN {_active_job_exists_sql()} THEN 1
        WHEN (publish_status IS NULL OR publish_status != 1) AND translate_status IN (1, 2) THEN 2
        WHEN download_status = 1 AND (translate_status IS NULL OR translate_status NOT IN (1, 2)) THEN 3
        WHEN (download_status IS NULL OR download_status != 1) THEN 4
        WHEN publish_status = 1 THEN 5
        ELSE 6
    END ASC,
    {_published_newest_order_sql()}
    """


def _duration_seconds_sql():
    return """
    CASE
        WHEN duration ~ '^\\d+$' THEN duration::BIGINT
        WHEN duration ~ '^\\d+:\\d+$' THEN split_part(duration, ':', 1)::BIGINT * 60 + split_part(duration, ':', 2)::BIGINT
        WHEN duration ~ '^\\d+:\\d+:\\d+$' THEN split_part(duration, ':', 1)::BIGINT * 3600 + split_part(duration, ':', 2)::BIGINT * 60 + split_part(duration, ':', 3)::BIGINT
        WHEN duration ~ '^\\s*(\\d+\\s*h)?\\s*(\\d+\\s*m)?\\s*(\\d+\\s*s)?\\s*$' THEN
            COALESCE((regexp_match(duration, '(\\d+)\\s*h'))[1]::BIGINT, 0) * 3600 +
            COALESCE((regexp_match(duration, '(\\d+)\\s*m'))[1]::BIGINT, 0) * 60 +
            COALESCE((regexp_match(duration, '(\\d+)\\s*s'))[1]::BIGINT, 0)
    END
    """


def _youtube_video_sort_sql(sort):
    if sort == "publishedNewest":
        return _published_newest_order_sql()
    if sort == "importedNewest":
        return "created_at DESC, id DESC"
    if sort == "importedOldest":
        return "created_at ASC, id ASC"
    if sort == "durationShortest":
        duration_sql = _duration_seconds_sql()
        return f"""
        CASE WHEN ({duration_sql}) IS NULL THEN 1 ELSE 0 END ASC,
        ({duration_sql}) ASC,
        NULLIF(published_at, '') DESC NULLS LAST,
        created_at DESC,
        id DESC
        """
    if sort == "stageProgress":
        return f"""
        CASE
            WHEN publish_status = 1 THEN 0
            WHEN translate_status IN (1, 2) THEN 1
            WHEN download_status = 1 THEN 2
            ELSE 3
        END ASC,
        {_published_newest_order_sql()}
        """
    if sort == "pendingFirst":
        return """
        CASE WHEN download_status = 1 AND translate_status = 1 THEN 1 ELSE 0 END ASC,
        CASE WHEN download_status = 1 THEN 1 ELSE 0 END ASC,
        CASE WHEN translate_status = 1 THEN 1 ELSE 0 END ASC,
        CASE WHEN publish_status = 1 THEN 1 ELSE 0 END ASC,
        created_at DESC, id DESC
        """
    if sort == "downloadedFirst":
        return "CASE WHEN download_status = 1 THEN 0 ELSE 1 END ASC, CASE WHEN translate_status = 1 THEN 0 ELSE 1 END ASC, created_at DESC, id DESC"
    if sort == "translatedFirst":
        return "CASE WHEN translate_status = 1 THEN 0 ELSE 1 END ASC, CASE WHEN download_status = 1 THEN 0 ELSE 1 END ASC, created_at DESC, id DESC"
    if sort == "publishedFirst":
        return "CASE WHEN publish_status = 1 THEN 0 ELSE 1 END ASC, CASE WHEN translate_status = 1 THEN 0 ELSE 1 END ASC, created_at DESC, id DESC"
    return _default_stage_order_sql()


def _youtube_video_where(params, owner_user_id):
    where = ["owner_user_id = %s"]
    values = [owner_user_id]
    storage_clause, storage_values = _youtube_storage_scope_clause(params.get("storageScope"))
    where.append(storage_clause)
    values.extend(storage_values)
    ids = _split_request_values(params.get("ids"))
    if ids:
        where.append(f"video_id IN ({_sql_placeholders(ids)})")
        values.extend(ids)
    keyword = str(params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        where.append("""(
            title ILIKE %s OR channel ILIKE %s OR url ILIKE %s OR query ILIKE %s
            OR publish_draft ILIKE %s
        )""")
        values.extend([like, like, like, like, like])
    status_clause, status_values = _youtube_video_status_clause(str(params.get("status") or "all"))
    if status_clause:
        where.append(status_clause)
        values.extend(status_values)
    group_id = params.get("groupId") or params.get("group_id")
    if group_id not in (None, ""):
        try:
            values.append(int(group_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("groupId 必须是整数") from exc
        where.append("group_id = %s")
    return (" WHERE " + " AND ".join(where)) if where else "", values, ids


def _attach_processed_versions_for_videos(cursor, videos, owner_user_id):
    video_ids = [video.get("id") for video in videos if video.get("id")]
    for video in videos:
        video["processedVersions"] = []
    if not video_ids:
        return videos

    cursor.execute(f'''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
      AND owner_user_id = %s
      AND status != 'purged'
      AND source_video_id IN ({_sql_placeholders(video_ids)})
    ORDER BY upload_time DESC, id DESC
    ''', [owner_user_id, *video_ids])
    versions_by_video = {video_id: {} for video_id in video_ids}
    videos_by_id = {video.get("id"): video for video in videos if video.get("id")}
    for row in cursor.fetchall():
        raw_record = dict(row)
        video_id = _material_source_video_id(raw_record)
        if video_id not in versions_by_video:
            continue
        source_video = videos_by_id.get(video_id) or {}
        record = _row_to_material_fast(
            row,
            source_video=source_video,
            analysis={
                "result": source_video.get("analysisResult") or {},
                "draft": source_video.get("publishDraft") or {},
            },
        )
        process_version = record.get("processVersion") or _material_process_version(record) or "translation_v1"
        if process_version in versions_by_video[video_id]:
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        applied_cover_title = "\n".join(
            line.strip() for line in str(metadata.get("coverTitleApplied") or "").replace("\r\n", "\n").splitlines()
        ).strip()
        draft = source_video.get("publishDraft") if isinstance(source_video.get("publishDraft"), dict) else {}
        current_cover_title = "\n".join(
            line.strip() for line in str(draft.get("coverTitle") or "").replace("\r\n", "\n").splitlines()
        ).strip()
        versions_by_video[video_id][process_version] = {
            "materialId": record.get("id"),
            "filename": record.get("filename") or "",
            "filePath": str(_material_file_path(record) or ""),
            "processVersion": process_version,
            "processType": record.get("processType") or "",
            "subtitleLanguage": record.get("subtitleLanguage") or _material_subtitle_language(record),
            "subtitleLanguageLabel": record.get("subtitleLanguageLabel") or "",
            "duration": record.get("duration") or "",
            "filesize": record.get("filesize") or 0,
            "createdAt": record.get("upload_time") or "",
            "coverTitleApplied": applied_cover_title,
            "coverReburnRequired": bool(
                process_version == "editing_v1"
                and applied_cover_title
                and applied_cover_title != current_cover_title
            ),
        }

    for video in videos:
        video["processedVersions"] = list(versions_by_video.get(video.get("id"), {}).values())
    return videos


def _youtube_video_summary(cursor, owner_user_id, keyword="", group_id=None, storage_scope="active"):
    where_parts = ["owner_user_id = %s"]
    values = [owner_user_id]
    storage_clause, storage_values = _youtube_storage_scope_clause(storage_scope)
    where_parts.append(storage_clause)
    values.extend(storage_values)
    if keyword:
        like = f"%{keyword}%"
        where_parts.append("(title ILIKE %s OR channel ILIKE %s OR url ILIKE %s OR query ILIKE %s)")
        values.extend([like, like, like, like])
    if group_id not in (None, ""):
        where_parts.append("group_id = %s")
        values.append(int(group_id))
    where = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    cursor.execute(f'''
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN download_status = 1 THEN 0 ELSE 1 END) AS pending_download,
        SUM(CASE WHEN download_status = 1 AND translate_status NOT IN (1, 2) THEN 1 ELSE 0 END) AS pending_translate,
        SUM(CASE WHEN translate_status = 1 AND publish_status != 1 THEN 1 ELSE 0 END) AS ready_publish,
        SUM(CASE WHEN publish_status = 1 THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN download_status = 1 THEN 1 ELSE 0 END) AS downloaded,
        SUM(CASE WHEN translate_status = 1 THEN 1 ELSE 0 END) AS translated
    FROM youtube_videos
    {where}
    ''', values)
    row = cursor.fetchone() or {}
    running_group_clause = ""
    running_values = []
    if group_id not in (None, ""):
        running_group_clause = "AND video_id IN (SELECT video_id FROM youtube_videos WHERE owner_user_id = %s AND group_id = %s)"
        running_values.extend([owner_user_id, int(group_id)])
    cursor.execute(f'''
    SELECT COUNT(DISTINCT video_id) AS running
    FROM youtube_workflow_jobs
    WHERE owner_user_id = %s AND status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish') AND video_id IS NOT NULL AND video_id != ''
    {running_group_clause}
    ''', [owner_user_id, *running_values])
    running_row = cursor.fetchone() or {}
    return {
        "total": int(row["total"] or 0),
        "pendingDownload": int(row["pending_download"] or 0),
        "pendingTranslate": int(row["pending_translate"] or 0),
        "readyPublish": int(row["ready_publish"] or 0),
        "running": int(running_row["running"] or 0),
        "completed": int(row["completed"] or 0),
        "downloaded": int(row["downloaded"] or 0),
        "translated": int(row["translated"] or 0),
    }


def _reconcile_youtube_statuses_with_material_records(cursor, owner_user_id):
    cursor.execute('''
    UPDATE youtube_videos
    SET download_status = 0,
        downloaded_file_path = '',
        updated_at = CURRENT_TIMESTAMP
    WHERE download_status = 1
      AND youtube_videos.owner_user_id = %s
      AND NOT EXISTS (
        SELECT 1
        FROM file_records
        WHERE file_records.source_type = 'youtube_download'
          AND file_records.source_video_id = youtube_videos.video_id
          AND file_records.owner_user_id = youtube_videos.owner_user_id
          AND file_records.status != 'purged'
      )
    ''', (owner_user_id,))
    cursor.execute('''
    UPDATE youtube_videos
    SET translate_status = 0,
        publish_status = 0,
        processed_file_path = '',
        updated_at = CURRENT_TIMESTAMP
    WHERE translate_status IN (1, 2)
      AND youtube_videos.owner_user_id = %s
      AND NOT EXISTS (
        SELECT 1
        FROM file_records
        WHERE file_records.source_type = 'youtube_processed'
          AND file_records.source_video_id = youtube_videos.video_id
          AND file_records.owner_user_id = youtube_videos.owner_user_id
          AND file_records.status != 'purged'
      )
    ''', (owner_user_id,))


def _reconcile_youtube_generated_publish_drafts(cursor, owner_user_id):
    """修复历史自动稿与最新分析结果不一致的记录，不触碰人工编辑稿。"""
    cursor.execute('''
    SELECT video_id, analysis_result, publish_draft
    FROM youtube_videos
    WHERE analysis_status = 1
      AND owner_user_id = %s
      AND analysis_result IS NOT NULL AND analysis_result != ''
      AND publish_draft IS NOT NULL AND publish_draft != ''
    ''', (owner_user_id,))
    for row in cursor.fetchall():
        result = _parse_json_object(row["analysis_result"])
        draft = _parse_publish_draft(row["publish_draft"], result)
        if not result or draft.get("source") != "llm_default":
            continue
        expected = _build_default_publish_draft(result)
        if draft.get("title") in (result.get("title_options") or []):
            expected["title"] = draft["title"]
        if (
            draft.get("title") == expected.get("title")
            and draft.get("description") == expected.get("description")
            and draft.get("tags") == expected.get("tags")
        ):
            continue
        cursor.execute('''
        UPDATE youtube_videos
        SET publish_draft = %s, updated_at = CURRENT_TIMESTAMP
        WHERE video_id = %s AND owner_user_id = %s
        ''', (json.dumps(expected, ensure_ascii=False), row["video_id"], owner_user_id))


def list_youtube_videos(params=None, owner_user_id=None):
    if owner_user_id is None:
        raise PermissionError("登录用户不能为空")
    init_youtube_video_table()
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize"), 20, 1, 100)
    offset = (page - 1) * page_size
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        _reconcile_youtube_statuses_with_material_records(cursor, owner_user_id)
        _reconcile_youtube_generated_publish_drafts(cursor, owner_user_id)
        _reconcile_superseded_publish_records(cursor, owner_user_id)
        conn.commit()
        where_sql, values, ids = _youtube_video_where(params, owner_user_id)
        sort_sql = _youtube_video_sort_sql(str(params.get("sort") or "default"))
        cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_videos{where_sql}", values)
        total = int((cursor.fetchone() or {})["total"] or 0)

        if ids:
            order_sql = f"CASE video_id {' '.join(f'WHEN %s THEN {index}' for index, _ in enumerate(ids))} END"
            query_values = values + ids + [page_size, offset]
        else:
            order_sql = sort_sql
            query_values = values + [page_size, offset]
        cursor.execute('''
        SELECT youtube_videos.*,
               (SELECT name FROM youtube_video_groups WHERE id = youtube_videos.group_id) AS group_name,
               COALESCE((SELECT is_default FROM youtube_video_groups WHERE id = youtube_videos.group_id), 0) AS group_is_default
        FROM youtube_videos
        {where_sql}
        ORDER BY {order_sql}
        LIMIT %s OFFSET %s
        '''.format(where_sql=where_sql, order_sql=order_sql), query_values)
        videos = [_row_to_youtube_video(row) for row in cursor.fetchall()]
        video_ids = [video["id"] for video in videos if video.get("id")]
        publish_records = {}
        if video_ids:
            placeholders = ",".join("%s" for _ in video_ids)
            cursor.execute(f'''
            SELECT id, video_id, platform, platform_type, status, message, publish_task_id, updated_at,
                   published_at, account_id, account_name
            FROM (
                SELECT id, video_id, platform, platform_type, status, message, publish_task_id, updated_at,
                       published_at, account_id, account_name,
                       ROW_NUMBER() OVER (
                           PARTITION BY video_id, platform_type
                           ORDER BY id DESC
                       ) AS record_rank
                FROM published_youtube_materials
                WHERE owner_user_id = %s AND video_id IN ({placeholders})
                  AND deleted_at IS NULL AND invalidated_at IS NULL
            ) current_records
            WHERE record_rank = 1
            ORDER BY platform_type
            ''', [owner_user_id, *video_ids])
            for record in cursor.fetchall():
                video_id = record["video_id"] or ""
                publish_records.setdefault(video_id, []).append({
                    "recordId": int(record["id"] or 0),
                    "type": int(record["platform_type"] or 0),
                    "name": record["platform"] or platform_name(record["platform_type"]),
                    "status": record["status"] or "failed",
                    "message": clean_display_text(record["message"]),
                    "publishTaskId": record["publish_task_id"] or "",
                    "updatedAt": record["updated_at"] or "",
                    "publishedAt": record["published_at"] or "",
                    "accountId": record["account_id"],
                    "accountName": record["account_name"] or "",
                })
        for video in videos:
            records = publish_records.get(video.get("id"), [])
            video["publishedPlatforms"] = [
                record for record in records if record["status"] in {"confirmed", "reused"}
            ]
            video["publishDelivery"] = {
                "status": aggregate_publish_status(records) if records else "",
                "statusLabel": publish_status_label(aggregate_publish_status(records)) if records else "未发布",
                "progress": publish_progress(records),
                "targets": records,
            }
            valid_targets = [record for record in records if record["status"] in {"confirmed", "reused"}]
            if records and len(valid_targets) == len(records):
                anchors = [record.get("publishedAt") for record in valid_targets if record.get("publishedAt")]
                video["retentionAnchorAt"] = max(anchors) if anchors else ""
        _attach_processed_versions_for_videos(cursor, videos, owner_user_id)
        _attach_source_title_translations(cursor, videos, owner_user_id)
        _queue_source_title_translation_batch(
            owner_user_id,
            _source_title_translation_candidates(cursor, videos, owner_user_id, _TITLE_TRANSLATION_PAGE_LIMIT),
        )
        return {
            "items": videos,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": _youtube_video_summary(
                cursor,
                owner_user_id,
                str(params.get("keyword") or "").strip(),
                params.get("groupId") or params.get("group_id"),
                params.get("storageScope"),
            ),
        }


def normalize_existing_youtube_subscribers():
    init_youtube_workflow_table()
    with _db_connect() as conn:
        cursor = conn.cursor()
        for table in ("youtube_videos", "youtube_workflow_jobs"):
            cursor.execute(f"SELECT id, subscribers FROM {table} WHERE subscribers IS NOT NULL AND subscribers != ''")
            rows = cursor.fetchall()
            for row_id, subscribers in rows:
                normalized = _format_subscribers_w(subscribers)
                if normalized and normalized != subscribers:
                    cursor.execute(
                        f"UPDATE {table} SET subscribers = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (normalized, row_id),
                    )
        conn.commit()


def update_youtube_video_status(video_id, owner_user_id, download_status=None, publish_status=None, translate_status=None):
    init_youtube_video_table()
    fields = []
    values = []
    if download_status is not None:
        fields.append("download_status = %s")
        values.append(int(download_status))
    if publish_status is not None:
        fields.append("publish_status = %s")
        values.append(int(publish_status))
    if translate_status is not None:
        fields.append("translate_status = %s")
        values.append(int(translate_status))
    if not fields:
        raise ValueError("没有可更新的状态字段")
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([video_id, owner_user_id])
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = %s AND owner_user_id = %s
        ''', values)
        if cursor.rowcount == 0:
            raise LookupError("视频记录不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))
        return _row_to_youtube_video(cursor.fetchone())


def _cleanup_editing_v1_artifacts(video_record, *, cursor=None):
    """删除 editing_v1 的 body/ASS 内部产物与片头渲染临时目录，文件清理失败只记日志不抛。
    字段清理由调用方按事务情况处理（事务内裸 UPDATE，事务外 update_youtube_video_artifacts）。"""
    video_record = dict(video_record or {})
    processed_path = Path(video_record.get("processed_file_path") or "")
    # body/ASS 内部产物：跳过等于当前成片的（降级路径下 body 可能就是成片本身）。
    for key in ("editing_body_path", "editing_ass_path"):
        candidate = Path(video_record.get(key) or "")
        if candidate.is_file() and candidate != processed_path:
            safe_unlink(candidate)
    # 片头渲染临时目录：按 video_id 查历史 job_id，清理 {job_id}_editing_intro。
    video_id = video_record.get("video_id") or video_record.get("id") or ""
    if video_id and cursor is not None:
        try:
            cursor.execute(
                "SELECT id FROM youtube_workflow_jobs WHERE video_id = %s AND owner_user_id = %s",
                (video_id, video_record.get("owner_user_id")),
            )
            job_ids = [str(row[0]) for row in cursor.fetchall()]
        except Exception as exc:
            backend_logger.warning("查询历史任务失败，跳过 work_dir 清理 video_id=%s %s", video_id, exc)
            job_ids = []
        for job_id in job_ids:
            safe_rmtree(YOUTUBE_PROCESSED_DIR / f"{job_id}_editing_intro")


def delete_youtube_video_record(video_id, owner_user_id):
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        video_record = dict(video)
        _assert_no_active_youtube_job(cursor, video_id, owner_user_id)
        published_ids, _ = _published_youtube_identity_sets(cursor, owner_user_id)
        has_publish_status = int(video_record.get("publish_status") or 0) == 1
        if has_publish_status and video_id not in published_ids:
            legacy_material = (
                _find_latest_youtube_material(cursor, video_id, "youtube_processed", owner_user_id)
                or _find_latest_youtube_material(cursor, video_id, "youtube_download", owner_user_id)
                or {}
            )
            _archive_published_material(
                cursor,
                _row_to_material(legacy_material) if legacy_material else {},
                _row_to_youtube_video(video),
                "历史发布",
                _now_iso(),
                publish_title=video_record.get("title") or "",
                account_count=0,
            )
            published_ids.add(video_id)
        is_published_archived = video_id in published_ids or has_publish_status

        processed_material = _find_latest_youtube_material(cursor, video_id, "youtube_processed", owner_user_id)
        processed_path = Path(video_record["processed_file_path"]) if video_record["processed_file_path"] else None
        if not is_published_archived and (processed_material or (processed_path and processed_path.exists())):
            raise WorkflowConflictError(
                "该视频已存在处理后视频，请先删除对应处理后视频，再删除视频线索。",
                WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS,
                "PROCESSED_VIDEO_EXISTS",
            )

        download_material = _find_latest_youtube_material(cursor, video_id, "youtube_download", owner_user_id)
        downloaded_file_path = video_record.get("downloaded_file_path") or ""
        download_status = int(video_record.get("download_status") or 0)
        if not is_published_archived and (download_material or downloaded_file_path or download_status == 1):
            raise WorkflowConflictError(
                "该视频已存在下载视频，请先删除对应下载视频，再删除视频线索。",
                WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS,
                "DOWNLOADED_VIDEO_EXISTS",
                {
                    "videoId": video_id,
                    "downloadStatus": download_status,
                    "materialId": (download_material or {}).get("id"),
                },
            )

        _cleanup_editing_v1_artifacts(video_record, cursor=cursor)
        if not is_published_archived:
            cursor.execute('''
            DELETE FROM youtube_workflow_events
            WHERE (video_id = %s AND owner_user_id = %s)
               OR job_id IN (SELECT id FROM youtube_workflow_jobs WHERE video_id = %s AND owner_user_id = %s)
            ''', (video_id, owner_user_id, video_id, owner_user_id))
            cursor.execute("DELETE FROM youtube_workflow_jobs WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))

        deleted_at = datetime.datetime.now().isoformat(timespec="microseconds")
        cursor.execute('''
        INSERT INTO youtube_video_deletions (video_id, deleted_at, owner_user_id)
        VALUES (%s, %s, %s)
        ON CONFLICT(owner_user_id, video_id) DO UPDATE SET deleted_at = excluded.deleted_at
        ''', (video_id, deleted_at, owner_user_id))
        cursor.execute("DELETE FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))
        deleted = cursor.rowcount
        conn.commit()
    if not deleted:
        raise LookupError("视频线索不存在")
    return {"videoId": video_id}


def delete_youtube_video_records(video_ids, owner_user_id):
    results = []
    for video_id in video_ids:
        try:
            results.append({
                "videoId": video_id,
                "success": True,
                "data": delete_youtube_video_record(video_id, owner_user_id),
            })
        except WorkflowConflictError as exc:
            results.append({
                "videoId": video_id,
                "success": False,
                "message": str(exc),
                "errorCode": exc.error_code,
                "errorType": exc.error_type,
            })
        except Exception as exc:
            results.append({
                "videoId": video_id,
                "success": False,
                "message": str(exc),
            })
    return {
        "total": len(video_ids),
        "success": sum(1 for item in results if item.get("success")),
        "failed": sum(1 for item in results if not item.get("success")),
        "items": results,
    }


def _delete_youtube_transcript_cache(video):
    video = dict(video or {})
    video_id = str(video.get("video_id") or video.get("videoId") or "").strip()
    paths = set()
    stored_path = str(video.get("transcript_file_path") or video.get("transcriptFilePath") or "").strip()
    if stored_path:
        paths.add(Path(stored_path))
    if video_id:
        key = re.sub(r"[^A-Za-z0-9_-]+", "_", video_id)
        paths.add(Path(YOUTUBE_TRANSCRIPT_DIR) / f"{key}.json")

    deleted = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise RuntimeError(f"删除转写缓存失败: {path}") from exc
        deleted.append(str(path))
    return deleted


def _delete_reset_youtube_workflow_history(cursor, video_id, owner_user_id, process_version=""):
    conditions = ["video_id = %s", "owner_user_id = %s", "status NOT IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')"]
    values = [video_id, owner_user_id]
    if process_version:
        conditions.append("process_version = %s")
        values.append(process_version)
    where_sql = " AND ".join(conditions)
    cursor.execute(f'''
    DELETE FROM youtube_workflow_events
    WHERE job_id IN (SELECT id FROM youtube_workflow_jobs WHERE {where_sql})
    ''', values)
    cursor.execute(f"DELETE FROM youtube_workflow_jobs WHERE {where_sql}", values)
    return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def reset_youtube_video_processing(video_id, owner_user_id, delete_processed=True, process_version="", refresh_transcript=False):
    init_youtube_workflow_table()
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    process_version = _normalize_process_version(process_version) if process_version else ""

    deleted_materials = []
    deleted_transcript_files = []
    deleted_workflow_job_count = 0
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        _assert_no_active_youtube_job(cursor, video_id, owner_user_id)

        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = %s AND source_type = 'youtube_processed'
          AND owner_user_id = %s
        ORDER BY upload_time DESC, id DESC
        ''', (video_id, owner_user_id))
        material_rows = cursor.fetchall()

        if delete_processed:
            _cleanup_editing_v1_artifacts(video, cursor=cursor)
            for row in material_rows:
                record = _row_to_material(row)
                if process_version and record.get("processVersion") != process_version:
                    continue
                file_path = _material_file_path(record)
                if file_path and file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as exc:
                        print(f"删除处理后素材文件失败 : error_type = {type(exc).__name__}")
                deleted_materials.append({
                    "id": record.get("id"),
                    "filename": record.get("filename"),
                    "processVersion": record.get("processVersion") or "",
                })
            if process_version:
                for record in deleted_materials:
                    cursor.execute("DELETE FROM file_records WHERE id = %s", (record.get("id"),))
            else:
                cursor.execute(
                    "DELETE FROM file_records WHERE source_video_id = %s AND source_type = 'youtube_processed' AND owner_user_id = %s",
                    (video_id, owner_user_id),
                )

        if refresh_transcript:
            deleted_transcript_files = _delete_youtube_transcript_cache(video)
            cursor.execute('''
            UPDATE youtube_videos
            SET transcript_status = 0,
                transcript_file_path = '',
                transcript_language = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = %s AND owner_user_id = %s
            ''', (video_id, owner_user_id))

        deleted_workflow_job_count = _delete_reset_youtube_workflow_history(
            cursor,
            video_id,
            owner_user_id,
            process_version,
        )
        sync_result = _sync_youtube_processed_state(cursor, video_id, owner_user_id)
        if deleted_materials and not sync_result.get("analysisCleared"):
            sync_result.update(_clear_youtube_analysis_state(cursor, video_id, owner_user_id))
        if delete_processed:
            cursor.execute('''
            UPDATE youtube_videos
            SET editing_body_path = '', editing_ass_path = '', editing_body_signature = '',
                editing_intro_signature = '', editing_highlight_snapshot = '[]', editing_intro_status = '',
                comment_burn_snapshot = '{}', comment_burn_signature = '', comment_burn_status = ''
            WHERE video_id = %s AND owner_user_id = %s
            ''', (video_id, owner_user_id))
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s", (video_id, owner_user_id))
        updated_video = _row_to_youtube_video(cursor.fetchone())

    return {
        "video": updated_video,
        "deletedMaterials": deleted_materials,
        "deletedMaterialCount": len(deleted_materials),
        "deletedTranscriptCount": len(deleted_transcript_files),
        "deletedWorkflowJobCount": deleted_workflow_job_count,
        "transcriptRefreshed": bool(refresh_transcript),
        "processVersion": process_version,
        "sync": sync_result,
    }


