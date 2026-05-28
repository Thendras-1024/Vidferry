def _row_to_youtube_video(row):
    item = dict(row)
    analysis_result = _parse_json_object(item.get("analysis_result"))
    publish_draft = _parse_publish_draft(item.get("publish_draft"), analysis_result)
    return {
        "dbId": item.get("id"),
        "id": item.get("video_id"),
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "subscribers": _format_subscribers_w(item.get("subscribers")),
        "publishedAt": item.get("published_at") or "",
        "url": item.get("url") or "",
        "thumbnail": item.get("thumbnail") or "",
        "duration": item.get("duration") or "",
        "query": item.get("query") or "",
        "downloadStatus": int(item.get("download_status") or 0),
        "publishStatus": int(item.get("publish_status") or 0),
        "translateStatus": int(item.get("translate_status") or 0),
        "downloadedFilePath": item.get("downloaded_file_path") or "",
        "processedFilePath": item.get("processed_file_path") or "",
        "transcriptStatus": int(item.get("transcript_status") or 0),
        "transcriptFilePath": item.get("transcript_file_path") or "",
        "transcriptLanguage": item.get("transcript_language") or "",
        "analysisStatus": int(item.get("analysis_status") or 0),
        "hasAnalysis": int(item.get("analysis_status") or 0) == 1,
        "analysisResult": analysis_result,
        "publishDraft": publish_draft,
        "analysisUpdatedAt": item.get("analysis_updated_at") or "",
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def save_new_youtube_videos(videos, query):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
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
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"SELECT video_id FROM youtube_videos WHERE video_id IN ({placeholders})", ids)
        existing_ids = {row["video_id"] for row in cursor.fetchall()}
        published_ids, published_urls = _published_youtube_identity_sets(cursor)
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
                video_id, title, channel, subscribers, published_at, url, thumbnail, duration, query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        placeholders = ",".join("?" for _ in new_ids)
        cursor.execute(f'''
        SELECT * FROM youtube_videos
        WHERE video_id IN ({placeholders})
        ORDER BY CASE video_id {' '.join(f'WHEN ? THEN {index}' for index, _ in enumerate(new_ids))} END
        ''', new_ids + new_ids)
        return {
            "items": [_row_to_youtube_video(row) for row in cursor.fetchall()],
            "created": len(new_videos),
            "duplicate": len(normalized_videos) - len(new_videos),
            "publishedDuplicate": published_duplicate_count,
            "requested": len(videos),
        }


def upsert_youtube_videos(videos, query):
    result = save_new_youtube_videos(videos, query)
    return result["items"]


def _youtube_video_status_clause(status):
    active_job_sql = """video_id IN (
            SELECT video_id FROM youtube_workflow_jobs
            WHERE status IN ('queued', 'running') AND video_id IS NOT NULL AND video_id != ''
        )"""
    failed_job_sql = """video_id IN (
            SELECT video_id FROM youtube_workflow_jobs
            WHERE status = 'failed' AND video_id IS NOT NULL AND video_id != ''
        )"""
    abnormal_job_sql = """video_id IN (
            SELECT video_id FROM youtube_workflow_jobs
            WHERE status = 'abnormal' AND video_id IS NOT NULL AND video_id != ''
        )"""
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


def _duration_text_to_seconds(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if len(parts) in (2, 3) and all(part.strip().isdigit() for part in parts):
        numbers = [int(part) for part in parts]
        if len(numbers) == 2:
            minutes, seconds = numbers
            return minutes * 60 + seconds
        hours, minutes, seconds = numbers
        return hours * 3600 + minutes * 60 + seconds
    match = re.match(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*$", text, re.I)
    if match and any(match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    return None


def _published_newest_order_sql():
    return """
    CASE WHEN julianday(published_at) IS NULL THEN 1 ELSE 0 END ASC,
    julianday(published_at) DESC,
    created_at DESC,
    id DESC
    """


def _active_job_exists_sql():
    return """EXISTS (
        SELECT 1 FROM youtube_workflow_jobs job
        WHERE job.video_id = youtube_videos.video_id
          AND job.status IN ('queued', 'running')
    )"""


def _job_status_exists_sql(status):
    return f"""EXISTS (
        SELECT 1 FROM youtube_workflow_jobs job
        WHERE job.video_id = youtube_videos.video_id
          AND job.status = '{status}'
    )"""


def _default_stage_order_sql():
    return f"""
    CASE
        WHEN {_job_status_exists_sql('failed')} OR {_job_status_exists_sql('abnormal')} THEN 0
        WHEN {_active_job_exists_sql()} THEN 1
        WHEN (publish_status IS NULL OR publish_status != 1) AND translate_status IN (1, 2) THEN 2
        WHEN download_status = 1 AND (translate_status IS NULL OR translate_status NOT IN (1, 2)) THEN 3
        WHEN (download_status IS NULL OR download_status != 1) THEN 4
        WHEN publish_status = 1 THEN 5
        ELSE 6
    END ASC,
    {_published_newest_order_sql()}
    """


def _youtube_video_sort_sql(sort):
    if sort == "publishedNewest":
        return _published_newest_order_sql()
    if sort == "durationShortest":
        return """
        CASE WHEN duration_to_seconds(duration) IS NULL THEN 1 ELSE 0 END ASC,
        duration_to_seconds(duration) ASC,
        CASE WHEN julianday(published_at) IS NULL THEN 1 ELSE 0 END ASC,
        julianday(published_at) DESC,
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


def _youtube_video_where(params):
    where = []
    values = []
    ids = _split_request_values(params.get("ids"))
    if ids:
        where.append(f"video_id IN ({_sql_placeholders(ids)})")
        values.extend(ids)
    keyword = str(params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        where.append("(title LIKE ? OR channel LIKE ? OR url LIKE ? OR query LIKE ?)")
        values.extend([like, like, like, like])
    status_clause, status_values = _youtube_video_status_clause(str(params.get("status") or "all"))
    if status_clause:
        where.append(status_clause)
        values.extend(status_values)
    return (" WHERE " + " AND ".join(where)) if where else "", values, ids


def _attach_processed_versions_for_videos(cursor, videos):
    video_ids = [video.get("id") for video in videos if video.get("id")]
    for video in videos:
        video["processedVersions"] = []
    if not video_ids:
        return videos

    cursor.execute(f'''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
      AND source_video_id IN ({_sql_placeholders(video_ids)})
    ORDER BY upload_time DESC, id DESC
    ''', video_ids)
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
        }

    for video in videos:
        video["processedVersions"] = list(versions_by_video.get(video.get("id"), {}).values())
    return videos


def _youtube_video_summary(cursor, keyword=""):
    where = ""
    values = []
    if keyword:
        like = f"%{keyword}%"
        where = "WHERE title LIKE ? OR channel LIKE ? OR url LIKE ? OR query LIKE ?"
        values = [like, like, like, like]
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
    cursor.execute('''
    SELECT COUNT(DISTINCT video_id) AS running
    FROM youtube_workflow_jobs
    WHERE status IN ('queued', 'running') AND video_id IS NOT NULL AND video_id != ''
    ''')
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


def _reconcile_youtube_statuses_with_material_records(cursor):
    cursor.execute('''
    UPDATE youtube_videos
    SET download_status = 0,
        downloaded_file_path = '',
        updated_at = CURRENT_TIMESTAMP
    WHERE download_status = 1
      AND NOT EXISTS (
        SELECT 1
        FROM file_records
        WHERE file_records.source_type = 'youtube_download'
          AND file_records.source_video_id = youtube_videos.video_id
      )
    ''')
    cursor.execute('''
    UPDATE youtube_videos
    SET translate_status = 0,
        publish_status = 0,
        processed_file_path = '',
        updated_at = CURRENT_TIMESTAMP
    WHERE translate_status IN (1, 2)
      AND NOT EXISTS (
        SELECT 1
        FROM file_records
        WHERE file_records.source_type = 'youtube_processed'
          AND file_records.source_video_id = youtube_videos.video_id
      )
    ''')


def list_youtube_videos(params=None):
    init_youtube_video_table()
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize"), 20, 1, 100)
    offset = (page - 1) * page_size
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        conn.create_function("duration_to_seconds", 1, _duration_text_to_seconds)
        cursor = conn.cursor()
        _reconcile_youtube_statuses_with_material_records(cursor)
        conn.commit()
        where_sql, values, ids = _youtube_video_where(params)
        sort_sql = _youtube_video_sort_sql(str(params.get("sort") or "default"))
        cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_videos{where_sql}", values)
        total = int((cursor.fetchone() or {})["total"] or 0)

        if ids:
            order_sql = f"CASE video_id {' '.join(f'WHEN ? THEN {index}' for index, _ in enumerate(ids))} END"
            query_values = values + ids + [page_size, offset]
        else:
            order_sql = sort_sql
            query_values = values + [page_size, offset]
        cursor.execute('''
        SELECT * FROM youtube_videos
        {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        '''.format(where_sql=where_sql, order_sql=order_sql), query_values)
        videos = [_row_to_youtube_video(row) for row in cursor.fetchall()]
        _attach_processed_versions_for_videos(cursor, videos)
        return {
            "items": videos,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": _youtube_video_summary(cursor, str(params.get("keyword") or "").strip()),
        }


def normalize_existing_youtube_subscribers():
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        for table in ("youtube_videos", "youtube_workflow_jobs"):
            cursor.execute(f"SELECT id, subscribers FROM {table} WHERE subscribers IS NOT NULL AND subscribers != ''")
            rows = cursor.fetchall()
            for row_id, subscribers in rows:
                normalized = _format_subscribers_w(subscribers)
                if normalized and normalized != subscribers:
                    cursor.execute(
                        f"UPDATE {table} SET subscribers = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (normalized, row_id),
                    )
        conn.commit()


def update_youtube_video_status(video_id, download_status=None, publish_status=None, translate_status=None):
    init_youtube_video_table()
    fields = []
    values = []
    if download_status is not None:
        fields.append("download_status = ?")
        values.append(int(download_status))
    if publish_status is not None:
        fields.append("publish_status = ?")
        values.append(int(publish_status))
    if translate_status is not None:
        fields.append("translate_status = ?")
        values.append(int(translate_status))
    if not fields:
        raise ValueError("没有可更新的状态字段")
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
        if cursor.rowcount == 0:
            raise LookupError("视频记录不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def delete_youtube_video_record(video_id):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        video_record = dict(video)
        _assert_no_active_youtube_job(cursor, video_id)
        published_ids, _ = _published_youtube_identity_sets(cursor)
        has_publish_status = int(video_record.get("publish_status") or 0) == 1
        if has_publish_status and video_id not in published_ids:
            legacy_material = (
                _find_latest_youtube_material(cursor, video_id, "youtube_processed")
                or _find_latest_youtube_material(cursor, video_id, "youtube_download")
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

        processed_material = _find_latest_youtube_material(cursor, video_id, "youtube_processed")
        processed_path = Path(video_record["processed_file_path"]) if video_record["processed_file_path"] else None
        if not is_published_archived and (processed_material or (processed_path and processed_path.exists())):
            raise WorkflowConflictError(
                "该视频已存在处理后视频，请先删除对应处理后视频，再删除视频线索。",
                WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS,
                "PROCESSED_VIDEO_EXISTS",
            )

        download_material = _find_latest_youtube_material(cursor, video_id, "youtube_download")
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
                    "downloadedFilePath": downloaded_file_path,
                    "materialId": (download_material or {}).get("id"),
                },
            )

        cursor.execute("DELETE FROM youtube_videos WHERE video_id = ?", (video_id,))
        deleted = cursor.rowcount
        conn.commit()
    if not deleted:
        raise LookupError("视频线索不存在")
    return {"videoId": video_id}


def delete_youtube_video_records(video_ids):
    results = []
    for video_id in video_ids:
        try:
            results.append({
                "videoId": video_id,
                "success": True,
                "data": delete_youtube_video_record(video_id),
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


def reset_youtube_video_processing(video_id, delete_processed=True, process_version=""):
    init_youtube_workflow_table()
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    process_version = _normalize_process_version(process_version) if process_version else ""

    deleted_materials = []
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        _assert_no_active_youtube_job(cursor, video_id)

        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = ? AND source_type = 'youtube_processed'
        ORDER BY upload_time DESC, id DESC
        ''', (video_id,))
        material_rows = cursor.fetchall()

        if delete_processed:
            for row in material_rows:
                record = _row_to_material(row)
                if process_version and record.get("processVersion") != process_version:
                    continue
                file_path = _material_file_path(record)
                if file_path and file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as exc:
                        print(f"删除处理后素材文件失败: {file_path} {exc}")
                deleted_materials.append({
                    "id": record.get("id"),
                    "filename": record.get("filename"),
                    "filePath": str(file_path) if file_path else "",
                    "processVersion": record.get("processVersion") or "",
                })
            if process_version:
                for record in deleted_materials:
                    cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
            else:
                cursor.execute(
                    "DELETE FROM file_records WHERE source_video_id = ? AND source_type = 'youtube_processed'",
                    (video_id,),
                )

        sync_result = _sync_youtube_processed_state(cursor, video_id)
        if deleted_materials and not sync_result.get("analysisCleared"):
            sync_result.update(_clear_youtube_analysis_state(cursor, video_id))
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        updated_video = _row_to_youtube_video(cursor.fetchone())

    return {
        "video": updated_video,
        "deletedMaterials": deleted_materials,
        "deletedMaterialCount": len(deleted_materials),
        "processVersion": process_version,
        "sync": sync_result,
    }


