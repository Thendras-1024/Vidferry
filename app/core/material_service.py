def _material_file_path(record):
    raw_path = record.get("storage_key") or record.get("file_path") or ""
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return Path(BASE_DIR / "videoFile" / raw_path)


def _material_metadata(record):
    metadata = record.get("metadata") or {}
    if isinstance(metadata, dict):
        return metadata
    try:
        return json.loads(metadata)
    except (TypeError, ValueError):
        return {}


def _material_source_video_id(record):
    metadata = _material_metadata(record)
    return (
        record.get("source_video_id")
        or metadata.get("videoId")
        or metadata.get("sourceVideoId")
        or ""
    )


def _material_process_version(record):
    metadata = _material_metadata(record)
    return metadata.get("processVersion") or ""


def _material_subtitle_language(record):
    metadata = _material_metadata(record)
    return metadata.get("subtitleLanguage") or ""


def _find_latest_youtube_material(cursor, video_id, source_type):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = ?
    ORDER BY upload_time DESC, id DESC
    ''', (source_type,))
    for row in cursor.fetchall():
        record = dict(row)
        if _material_source_video_id(record) == video_id:
            return record
    return None


def _find_latest_processed_material(cursor, video_id, process_version=""):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    for row in cursor.fetchall():
        record = dict(row)
        if _material_source_video_id(record) != video_id:
            continue
        if process_version and _material_process_version(record) != process_version:
            continue
        return record
    return None


def _delete_replaced_processed_materials(cursor, video_id, process_version, keep_material_id):
    if not video_id or not process_version:
        return []

    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    deleted = []
    for row in cursor.fetchall():
        record = dict(row)
        if int(record.get("id") or 0) == int(keep_material_id or 0):
            continue
        if _material_source_video_id(record) != video_id:
            continue
        if _material_process_version(record) != process_version:
            continue

        deleted.append({
            "id": record.get("id"),
            "filename": record.get("filename"),
            "processVersion": process_version,
            "files": _delete_material_files(record),
        })
        cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
    return deleted


def _sync_youtube_processed_state(cursor, video_id):
    remaining = _find_latest_processed_material(cursor, video_id)
    remaining_path = str(_material_file_path(remaining)) if remaining else ""
    if remaining:
        cursor.execute('''
        UPDATE youtube_videos
        SET translate_status = CASE
                WHEN translate_status IN (1, 2) THEN translate_status
                ELSE 1
            END,
            processed_file_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (remaining_path, video_id))
        return {
            "changed": cursor.rowcount > 0,
            "translateStatus": 1,
            "processedFilePath": remaining_path,
            "remainingMaterialId": remaining.get("id"),
            "remainingProcessVersion": _material_process_version(remaining),
        }

    cursor.execute('''
    UPDATE youtube_videos
    SET translate_status = 0,
        publish_status = 0,
        processed_file_path = '',
        analysis_status = 0,
        analysis_result = '',
        publish_draft = '',
        analysis_updated_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE video_id = ?
    ''', (video_id,))
    return {
        "changed": cursor.rowcount > 0,
        "translateStatus": 0,
        "publishStatus": 0,
        "processedFilePath": "",
        "analysisStatus": 0,
        "analysisCleared": True,
    }


def _clear_youtube_analysis_state(cursor, video_id):
    cursor.execute('''
    UPDATE youtube_videos
    SET analysis_status = 0,
        analysis_result = '',
        publish_draft = '',
        analysis_updated_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE video_id = ?
    ''', (video_id,))
    return {
        "analysisStatus": 0,
        "analysisCleared": cursor.rowcount > 0,
    }


def _delete_material_files(record):
    deleted_files = []
    file_path = _material_file_path(record)
    candidates = []
    if file_path:
        candidates.append(file_path)
        if record.get("source_type") == "youtube_download":
            candidates.extend(file_path.with_suffix(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))

    seen = set()
    for path in candidates:
        if not path:
            continue
        path_key = str(path)
        if path_key in seen:
            continue
        seen.add(path_key)
        if path.exists():
            try:
                path.unlink()
                deleted_files.append(path_key)
            except Exception as exc:
                print(f"⚠️ 删除素材文件失败: {path} {exc}")
    return deleted_files


def delete_material_record(cursor, file_id):
    cursor.execute("SELECT * FROM file_records WHERE id = ?", (file_id,))
    record = cursor.fetchone()
    if not record:
        raise LookupError("File not found")

    record = dict(record)
    source_video_id = _material_source_video_id(record)
    if source_video_id:
        _assert_no_active_youtube_job(cursor, source_video_id)

    deleted_files = _delete_material_files(record)
    cursor.execute("DELETE FROM file_records WHERE id = ?", (file_id,))
    sync_result = _sync_youtube_video_after_material_delete(cursor, record)
    return {
        "id": record["id"],
        "filename": record["filename"],
        "deletedFiles": deleted_files,
        "sync": sync_result,
    }


def delete_material_records(file_ids):
    init_database_tables()
    results = []
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_id in file_ids:
            try:
                result = delete_material_record(cursor, file_id)
                results.append({"id": file_id, "success": True, "data": result})
            except WorkflowConflictError as exc:
                results.append({
                    "id": file_id,
                    "success": False,
                    "message": str(exc),
                    "errorCode": exc.error_code,
                    "errorType": exc.error_type,
                })
            except Exception as exc:
                results.append({"id": file_id, "success": False, "message": str(exc)})
        conn.commit()
    return {
        "total": len(file_ids),
        "success": sum(1 for item in results if item.get("success")),
        "failed": sum(1 for item in results if not item.get("success")),
        "items": results,
    }


def _delete_youtube_download_materials_for_video(cursor, video_id, video_row=None):
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_download'
    ORDER BY upload_time DESC, id DESC
    ''')
    records = [
        dict(row)
        for row in cursor.fetchall()
        if _material_source_video_id(dict(row)) == video_id
    ]

    deleted = []
    for record in records:
        deleted.append({
            "id": record.get("id"),
            "filename": record.get("filename"),
            "files": _delete_material_files(record),
        })
        cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))

    downloaded_file_path = (video_row or {}).get("downloaded_file_path") or ""
    if downloaded_file_path and not any(str(_material_file_path(record)) == downloaded_file_path for record in records):
        extra_record = {
            "source_type": "youtube_download",
            "file_path": downloaded_file_path,
            "storage_key": downloaded_file_path,
        }
        deleted.append({
            "id": None,
            "filename": Path(downloaded_file_path).name,
            "files": _delete_material_files(extra_record),
        })

    return deleted


def _sync_youtube_video_after_material_delete(cursor, deleted_record):
    source_type = deleted_record.get("source_type") or ""
    video_id = _material_source_video_id(deleted_record)
    if not video_id or source_type not in {"youtube_processed", "youtube_download"}:
        return None

    sync_result = {
        "videoId": video_id,
        "sourceType": source_type,
        "changed": False,
    }
    remaining = _find_latest_youtube_material(cursor, video_id, source_type)
    remaining_path = str(_material_file_path(remaining)) if remaining else ""

    if source_type == "youtube_processed":
        sync_result.update(_sync_youtube_processed_state(cursor, video_id))
        if not sync_result.get("analysisCleared"):
            sync_result.update(_clear_youtube_analysis_state(cursor, video_id))
    elif source_type == "youtube_download":
        if remaining:
            cursor.execute('''
            UPDATE youtube_videos
            SET download_status = 1,
                downloaded_file_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (remaining_path, video_id))
            sync_result.update({
                "changed": cursor.rowcount > 0,
                "downloadStatus": 1,
                "downloadedFilePath": remaining_path,
            })
        else:
            cursor.execute('''
            UPDATE youtube_videos
            SET download_status = 0,
                downloaded_file_path = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (video_id,))
            sync_result.update({
                "changed": cursor.rowcount > 0,
                "downloadStatus": 0,
                "downloadedFilePath": "",
            })

    cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
    row = cursor.fetchone()
    if row:
        sync_result["video"] = _row_to_youtube_video(row)
    return sync_result


def verify_youtube_file_consistency():
    init_database_tables()
    summary = {
        "checkedVideos": 0,
        "fixedDownloadStatus": 0,
        "fixedProcessStatus": 0,
        "removedMaterialRecords": 0,
        "issues": [],
    }
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM file_records")
        for row in cursor.fetchall():
            record = dict(row)
            source_type = record.get("source_type") or ""
            if source_type not in {"youtube_download", "youtube_processed"}:
                continue
            path = _material_file_path(record)
            if path and path.exists():
                continue
            cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
            summary["removedMaterialRecords"] += 1
            summary["issues"].append({
                "type": "missing_material_file",
                "materialId": record.get("id"),
                "sourceType": source_type,
                "videoId": _material_source_video_id(record),
                "path": str(path) if path else "",
            })
            _sync_youtube_video_after_material_delete(cursor, record)

        cursor.execute("SELECT * FROM youtube_videos")
        for row in cursor.fetchall():
            video = dict(row)
            video_id = video.get("video_id") or ""
            summary["checkedVideos"] += 1

            downloaded_file = video.get("downloaded_file_path") or ""
            if int(video.get("download_status") or 0) == 1 and downloaded_file:
                if not Path(downloaded_file).is_file():
                    remaining = _find_latest_youtube_material(cursor, video_id, "youtube_download")
                    if remaining:
                        remaining_path = str(_material_file_path(remaining) or "")
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET downloaded_file_path = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (remaining_path, video_id))
                    else:
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET download_status = 0,
                            downloaded_file_path = '',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (video_id,))
                        summary["fixedDownloadStatus"] += 1
                    summary["issues"].append({
                        "type": "missing_downloaded_file",
                        "videoId": video_id,
                        "path": downloaded_file,
                    })

            processed_file = video.get("processed_file_path") or ""
            if int(video.get("translate_status") or 0) in {1, 2} and processed_file:
                if not Path(processed_file).is_file():
                    remaining = _find_latest_youtube_material(cursor, video_id, "youtube_processed")
                    if remaining:
                        remaining_path = str(_material_file_path(remaining) or "")
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET processed_file_path = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (remaining_path, video_id))
                    else:
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET translate_status = 0,
                            publish_status = 0,
                            processed_file_path = '',
                            analysis_status = 0,
                            analysis_result = '',
                            publish_draft = '',
                            analysis_updated_at = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (video_id,))
                        summary["fixedProcessStatus"] += 1
                    summary["issues"].append({
                        "type": "missing_processed_file",
                        "videoId": video_id,
                        "path": processed_file,
                    })

        conn.commit()
    return summary


def _format_duration_label(seconds):
    seconds = int(round(float(seconds or 0)))
    if seconds <= 0:
        return ""
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def _material_duration(record, source_video=None, probe_missing=True):
    metadata = record.get("metadata") or {}
    duration = record.get("duration") or metadata.get("duration") or (source_video or {}).get("duration") or ""
    duration_seconds = float(record.get("duration_seconds") or 0)
    if duration:
        return duration, duration_seconds
    if not probe_missing:
        return "", 0

    file_path = _material_file_path(record)
    if not file_path or not file_path.is_file():
        return "", 0

    try:
        duration_seconds = _get_media_duration_seconds(file_path)
    except Exception:
        duration_seconds = 0
    return _format_duration_label(duration_seconds), duration_seconds


def _row_to_material(row):
    item = dict(row)
    metadata = _material_metadata(item)
    if not item.get("asset_id"):
        item["asset_id"] = ""
    item["uuid"] = item.get("asset_id") or ""
    item["storage_key"] = item.get("storage_key") or item.get("file_path") or ""
    item["storage_backend"] = item.get("storage_backend") or "local"
    item["source_type"] = item.get("source_type") or "manual_upload"
    item["source_video_id"] = item.get("source_video_id") or ""
    item["status"] = item.get("status") or "ready"
    item["metadata"] = metadata
    source_video = None
    if item["source_video_id"]:
        try:
            source_video = _get_youtube_video_record(item["source_video_id"])
        except Exception:
            source_video = None

    display_title = metadata.get("title") or (source_video or {}).get("title") or item.get("original_filename") or item.get("filename") or ""
    display_url = metadata.get("url") or (source_video or {}).get("url") or ""
    display_channel = metadata.get("channel") or (source_video or {}).get("channel") or ""
    display_subscribers = metadata.get("subscribers") or (source_video or {}).get("subscribers") or ""
    display_published_at = metadata.get("publishedAt") or (source_video or {}).get("publishedAt") or ""
    video_id = metadata.get("videoId") or item.get("source_video_id") or (source_video or {}).get("id") or ""
    display_thumbnail = metadata.get("thumbnail") or (source_video or {}).get("thumbnail") or _youtube_thumbnail_url(video_id)
    duration_label, duration_seconds = _material_duration(item, source_video)
    inferred_language = _infer_subtitle_language_from_filename(item.get("filename")) if item["source_type"] == "youtube_processed" else ""
    subtitle_language = metadata.get("subtitleLanguage") or inferred_language
    language_meta = None
    if subtitle_language:
        subtitle_language, language_meta = _subtitle_language_meta(subtitle_language)

    item["displayTitle"] = display_title
    item["displayUrl"] = display_url
    item["displayChannel"] = display_channel
    item["displaySubscribers"] = _format_subscribers_w(display_subscribers) if display_subscribers else ""
    item["displayPublishedAt"] = display_published_at
    item["displayThumbnail"] = display_thumbnail
    item["duration"] = duration_label
    item["durationSeconds"] = round(float(duration_seconds or 0), 2)
    item["processVersion"] = metadata.get("processVersion") or "translation_v1"
    item["processType"] = "字幕处理/信息烧录" if item["source_type"] == "youtube_processed" else "原视频下载"
    item["subtitleLanguage"] = subtitle_language or ""
    item["subtitleLanguageLabel"] = metadata.get("subtitleLanguageLabel") or (language_meta or {}).get("label") or ""
    item["analysisStatus"] = int((source_video or {}).get("analysisStatus") or 0)
    item["analysisResult"] = {}
    item["publishDraft"] = {}
    if item["source_type"] == "youtube_processed" and video_id:
        try:
            analysis = get_youtube_video_analysis(video_id)
            item["analysisResult"] = analysis.get("result") or {}
            item["publishDraft"] = analysis.get("draft") or {}
        except Exception:
            item["analysisResult"] = {}
            item["publishDraft"] = {}
    return item


def _row_to_material_fast(row, source_video=None, analysis=None, workflow_job=None):
    item = dict(row)
    metadata = _material_metadata(item)
    if not item.get("asset_id"):
        item["asset_id"] = ""
    item["uuid"] = item.get("asset_id") or ""
    item["storage_key"] = item.get("storage_key") or item.get("file_path") or ""
    item["storage_backend"] = item.get("storage_backend") or "local"
    item["source_type"] = item.get("source_type") or "manual_upload"
    item["source_video_id"] = item.get("source_video_id") or metadata.get("videoId") or ""
    item["status"] = item.get("status") or "ready"
    item["metadata"] = metadata

    video = source_video or {}
    display_title = metadata.get("title") or video.get("title") or item.get("original_filename") or item.get("filename") or ""
    display_url = metadata.get("url") or video.get("url") or ""
    display_channel = metadata.get("channel") or video.get("channel") or ""
    display_subscribers = metadata.get("subscribers") or video.get("subscribers") or ""
    display_published_at = metadata.get("publishedAt") or video.get("publishedAt") or ""
    video_id = metadata.get("videoId") or item.get("source_video_id") or video.get("id") or ""
    display_thumbnail = metadata.get("thumbnail") or video.get("thumbnail") or _youtube_thumbnail_url(video_id)
    duration_label, duration_seconds = _material_duration(item, video, probe_missing=False)
    inferred_language = _infer_subtitle_language_from_filename(item.get("filename")) if item["source_type"] == "youtube_processed" else ""
    subtitle_language = metadata.get("subtitleLanguage") or inferred_language
    language_meta = None
    if subtitle_language:
        subtitle_language, language_meta = _subtitle_language_meta(subtitle_language)

    item["displayTitle"] = display_title
    item["displayUrl"] = display_url
    item["displayChannel"] = display_channel
    item["displaySubscribers"] = _format_subscribers_w(display_subscribers) if display_subscribers else ""
    item["displayPublishedAt"] = display_published_at
    item["displayThumbnail"] = display_thumbnail
    item["duration"] = duration_label
    item["durationSeconds"] = round(float(duration_seconds or 0), 2)
    item["processVersion"] = metadata.get("processVersion") or "translation_v1"
    item["processType"] = "字幕处理/信息烧录" if item["source_type"] == "youtube_processed" else "原视频下载"
    item["subtitleLanguage"] = subtitle_language or ""
    item["subtitleLanguageLabel"] = metadata.get("subtitleLanguageLabel") or (language_meta or {}).get("label") or ""
    item["analysisStatus"] = int(video.get("analysisStatus") or 0)
    item["analysisResult"] = (analysis or {}).get("result") or {}
    item["publishDraft"] = (analysis or {}).get("draft") or {}
    return _attach_workflow_job_to_material(item, workflow_job)


def _material_where(params):
    where = []
    values = []
    source_type = str(params.get("sourceType") or params.get("source_type") or "").strip()
    video_ids = _split_request_values(params.get("videoIds") or params.get("ids"))
    if source_type == "other":
        where.append("(source_type IS NULL OR source_type NOT IN ('youtube_processed', 'youtube_download'))")
    elif source_type:
        where.append("source_type = ?")
        values.append(source_type)
    if video_ids:
        metadata_conditions = []
        for video_id in video_ids:
            metadata_conditions.extend([
                f'%"videoId": "{video_id}"%',
                f'%"videoId":"{video_id}"%',
                f'%"sourceVideoId": "{video_id}"%',
                f'%"sourceVideoId":"{video_id}"%',
            ])
        where.append(
            f"(source_video_id IN ({_sql_placeholders(video_ids)})"
            f" OR metadata LIKE {' OR metadata LIKE '.join('?' for _ in metadata_conditions)})"
        )
        values.extend(video_ids + metadata_conditions)

    keyword = str(params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        where.append("""(
            filename LIKE ? OR original_filename LIKE ? OR file_path LIKE ? OR
            storage_key LIKE ? OR source_video_id LIKE ? OR metadata LIKE ?
        )""")
        values.extend([like, like, like, like, like, like])

    return (" WHERE " + " AND ".join(where)) if where else "", values


def _material_summary(cursor, keyword=""):
    where = ""
    values = []
    if keyword:
        like = f"%{keyword}%"
        where = """WHERE (
            filename LIKE ? OR original_filename LIKE ? OR file_path LIKE ? OR
            storage_key LIKE ? OR source_video_id LIKE ? OR metadata LIKE ?
        )"""
        values = [like, like, like, like, like, like]
    cursor.execute(f'''
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN source_type = 'youtube_processed' THEN 1 ELSE 0 END) AS processed,
        SUM(CASE WHEN source_type = 'youtube_download' THEN 1 ELSE 0 END) AS downloaded,
        SUM(CASE WHEN lower(filename) LIKE '%.mp4'
                  OR lower(filename) LIKE '%.avi'
                  OR lower(filename) LIKE '%.mov'
                  OR lower(filename) LIKE '%.wmv'
                  OR lower(filename) LIKE '%.flv'
                  OR lower(filename) LIKE '%.mkv'
                 THEN 1 ELSE 0 END) AS videos,
        SUM(CASE WHEN lower(filename) LIKE '%.jpg'
                  OR lower(filename) LIKE '%.jpeg'
                  OR lower(filename) LIKE '%.png'
                  OR lower(filename) LIKE '%.gif'
                  OR lower(filename) LIKE '%.bmp'
                  OR lower(filename) LIKE '%.webp'
                 THEN 1 ELSE 0 END) AS images,
        SUM(CASE WHEN source_type IS NULL OR source_type NOT IN ('youtube_processed', 'youtube_download') THEN 1 ELSE 0 END) AS other
    FROM file_records
    {where}
    ''', values)
    row = cursor.fetchone()
    return {
        "total": int(row["total"] or 0) if row else 0,
        "processed": int(row["processed"] or 0) if row else 0,
        "downloaded": int(row["downloaded"] or 0) if row else 0,
        "videos": int(row["videos"] or 0) if row else 0,
        "images": int(row["images"] or 0) if row else 0,
        "other": int(row["other"] or 0) if row else 0,
    }


def list_material_records(params=None):
    init_youtube_video_table()
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize"), 20, 1, 100)
    offset = (page - 1) * page_size
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        where_sql, values = _material_where(params)
        cursor.execute(f"SELECT COUNT(*) AS total FROM file_records{where_sql}", values)
        total = int((cursor.fetchone() or {})["total"] or 0)
        cursor.execute(f'''
        SELECT * FROM file_records
        {where_sql}
        ORDER BY upload_time DESC, id DESC
        LIMIT ? OFFSET ?
        ''', values + [page_size, offset])
        rows = cursor.fetchall()
        raw_items = [dict(row) for row in rows]
        video_ids = _clean_unique_list(_material_source_video_id(record) for record in raw_items)

        videos_by_id = {}
        analysis_by_id = {}
        if video_ids:
            cursor.execute(f'''
            SELECT * FROM youtube_videos
            WHERE video_id IN ({_sql_placeholders(video_ids)})
            ''', video_ids)
            for video_row in cursor.fetchall():
                video = _row_to_youtube_video(video_row)
                videos_by_id[video.get("id")] = video
                analysis_by_id[video.get("id")] = {
                    "result": video.get("analysisResult") or {},
                    "draft": video.get("publishDraft") or {},
                }

        jobs_by_video, jobs_by_video_version = _latest_workflow_jobs_for_videos(cursor, video_ids)
        items = []
        for row in rows:
            record = dict(row)
            video_id = _material_source_video_id(record)
            source_video = videos_by_id.get(video_id)
            material = _row_to_material_fast(
                row,
                source_video=source_video,
                analysis=analysis_by_id.get(video_id),
            )
            workflow_job = _material_workflow_job(material, jobs_by_video, jobs_by_video_version)
            items.append(_attach_workflow_job_to_material(material, workflow_job))

        return {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": _material_summary(cursor, str(params.get("keyword") or "").strip()),
        }


def _row_to_published_material(row):
    item = dict(row)
    try:
        metadata = json.loads(item.get("metadata") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": item.get("id"),
        "videoId": item.get("video_id") or "",
        "sourceUrl": item.get("source_url") or "",
        "title": item.get("title") or "",
        "platform": item.get("platform") or "",
        "platformType": int(item.get("platform_type") or 0),
        "accountFile": item.get("account_file") or "",
        "accountCount": int(item.get("account_count") or 0),
        "materialId": item.get("material_id"),
        "filename": item.get("filename") or "",
        "filePath": item.get("file_path") or "",
        "filesize": float(item.get("filesize") or 0),
        "thumbnail": item.get("thumbnail") or "",
        "channel": item.get("channel") or "",
        "subscribers": item.get("subscribers") or "",
        "sourcePublishedAt": item.get("source_published_at") or "",
        "publishTitle": item.get("publish_title") or "",
        "metadata": metadata,
        "publishTaskId": item.get("publish_task_id") or "",
        "status": item.get("status") or "success",
        "message": item.get("message") or "",
        "durationMs": int(item.get("duration_ms") or 0),
        "accountName": item.get("account_name") or "",
        "deletedAt": item.get("deleted_at") or "",
        "updatedAt": item.get("updated_at") or item.get("published_at") or item.get("created_at") or "",
        "publishedAt": item.get("published_at") or item.get("created_at") or "",
        "createdAt": item.get("created_at") or "",
    }


def list_published_youtube_materials(limit=50):
    init_database_tables()
    limit = max(1, min(int(limit or 50), 200))
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM published_youtube_materials
        WHERE deleted_at IS NULL
          AND COALESCE(NULLIF(status, ''), 'success') = 'success'
        ORDER BY COALESCE(published_at, updated_at, created_at) DESC, id DESC
        LIMIT ?
        ''', (limit,))
        return [_row_to_published_material(row) for row in cursor.fetchall()]


def _published_youtube_identity_sets(cursor):
    cursor.execute('''
    SELECT video_id, source_url FROM published_youtube_materials
    WHERE deleted_at IS NULL
      AND COALESCE(NULLIF(status, ''), 'success') = 'success'
    ''')
    published_ids = set()
    published_urls = set()
    for row in cursor.fetchall():
        video_id = row["video_id"] or ""
        source_url = row["source_url"] or ""
        extracted_id = _extract_youtube_video_id(source_url)
        if video_id:
            published_ids.add(video_id)
        if extracted_id:
            published_ids.add(extracted_id)
        canonical_url = _canonical_youtube_url(source_url, video_id or extracted_id)
        if canonical_url:
            published_urls.add(canonical_url)
    return published_ids, published_urls


def _archive_published_material(
    cursor,
    material,
    video,
    platform_name,
    published_at,
    publish_title="",
    account_count=0,
    platform_type=0,
    account_file="",
    publish_task_id="",
    status="success",
    message="",
    duration_ms=0,
    account_name="",
):
    video_id = material.get("source_video_id") or _material_source_video_id(material) or (video or {}).get("id") or ""
    source_url = _canonical_youtube_url((video or {}).get("url") or material.get("displayUrl") or "", video_id)
    title = (video or {}).get("title") or material.get("displayTitle") or material.get("original_filename") or material.get("filename") or ""
    metadata = {
        "materialMetadata": material.get("metadata") or {},
        "sourceVideo": video or {},
        "archivedFrom": "publish_record",
        "publishTaskId": publish_task_id or "",
    }
    cursor.execute(
        """
        SELECT id FROM published_youtube_materials
        WHERE COALESCE(publish_task_id, '') = ?
          AND video_id = ?
          AND platform_type = ?
          AND deleted_at IS NULL
        LIMIT 1
        """,
        (publish_task_id or "", video_id, int(platform_type or 0)),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute('''
        UPDATE published_youtube_materials
        SET source_url = ?,
            title = ?,
            platform = ?,
            account_file = ?,
            account_count = ?,
            account_name = ?,
            material_id = ?,
            filename = ?,
            file_path = ?,
            filesize = ?,
            thumbnail = ?,
            channel = ?,
            subscribers = ?,
            source_published_at = ?,
            publish_title = ?,
            metadata = ?,
            status = ?,
            message = ?,
            duration_ms = ?,
            published_at = CASE WHEN ? = 'success' THEN ? ELSE published_at END,
            updated_at = ?,
            deleted_at = NULL
        WHERE id = ?
        ''', (
            source_url,
            title,
            platform_name or "",
            account_file or "",
            int(account_count or 0),
            account_name or "",
            material.get("id"),
            material.get("filename") or "",
            str(_material_file_path(material) or material.get("file_path") or ""),
            float(material.get("filesize") or 0),
            material.get("displayThumbnail") or (video or {}).get("thumbnail") or "",
            material.get("displayChannel") or (video or {}).get("channel") or "",
            material.get("displaySubscribers") or (video or {}).get("subscribers") or "",
            material.get("displayPublishedAt") or (video or {}).get("publishedAt") or "",
            publish_title or "",
            json.dumps(metadata, ensure_ascii=False),
            status or "success",
            message or "",
            int(duration_ms or 0),
            status or "success",
            published_at,
            published_at,
            existing["id"],
        ))
        return existing["id"]
    cursor.execute('''
    INSERT INTO published_youtube_materials (
        video_id, source_url, title, platform, platform_type, account_file, account_count, material_id,
        filename, file_path, filesize, thumbnail, channel, subscribers,
        source_published_at, publish_title, metadata, published_at,
        publish_task_id, status, message, duration_ms, account_name, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        video_id,
        source_url,
        title,
        platform_name or "",
        int(platform_type or 0),
        account_file or "",
        int(account_count or 0),
        material.get("id"),
        material.get("filename") or "",
        str(_material_file_path(material) or material.get("file_path") or ""),
        float(material.get("filesize") or 0),
        material.get("displayThumbnail") or (video or {}).get("thumbnail") or "",
        material.get("displayChannel") or (video or {}).get("channel") or "",
        material.get("displaySubscribers") or (video or {}).get("subscribers") or "",
        material.get("displayPublishedAt") or (video or {}).get("publishedAt") or "",
        publish_title or "",
        json.dumps(metadata, ensure_ascii=False),
        published_at if (status or "success") == "success" else None,
        publish_task_id or "",
        status or "success",
        message or "",
        int(duration_ms or 0),
        account_name or "",
        published_at,
    ))
    return cursor.lastrowid


def _list_processed_versions_for_video(cursor, video_id):
    if not video_id:
        return []
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    versions = {}
    for row in cursor.fetchall():
        record = _row_to_material(row)
        if _material_source_video_id(record) != video_id:
            continue
        process_version = record.get("processVersion") or _material_process_version(record) or "translation_v1"
        if process_version in versions:
            continue
        versions[process_version] = {
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
    return list(versions.values())


def register_material(
    source_file,
    *,
    original_filename=None,
    source_type="manual_upload",
    source_video_id="",
    metadata=None,
    copy_to_library=False,
):
    init_database_tables()
    asset_id = uuid.uuid4().hex
    source_path = Path(source_file)
    if copy_to_library:
        target_dir = _ensure_dir(Path(BASE_DIR / "videoFile"))
        suffix = source_path.suffix or ".mp4"
        storage_key = f"{asset_id}{suffix}"
        stored_path = target_dir / storage_key
        shutil.copy2(source_path, stored_path)
        file_path_value = storage_key
    else:
        stored_path = source_path
        file_path_value = str(source_path)

    metadata_payload = metadata or {}
    duration_seconds = 0
    duration_label = metadata_payload.get("duration") or ""
    if source_path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"}:
        try:
            duration_seconds = _get_media_duration_seconds(stored_path)
            duration_label = duration_label or _format_duration_label(duration_seconds)
        except Exception:
            duration_seconds = 0
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?", (file_path_value, file_path_value))
        existing = cursor.fetchone()
        if existing:
            return _row_to_material(existing)
        cursor.execute('''
        INSERT INTO file_records (
            asset_id, filename, original_filename, filesize, file_path, storage_key,
            storage_backend, source_type, source_video_id, status, duration, duration_seconds, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id,
            source_path.name,
            original_filename or source_path.name,
            round(float(stored_path.stat().st_size) / (1024 * 1024), 2),
            file_path_value,
            file_path_value,
            "local",
            source_type,
            source_video_id or "",
            "ready",
            duration_label,
            round(float(duration_seconds or 0), 2),
            json.dumps(metadata_payload, ensure_ascii=False),
        ))
        conn.commit()
        cursor.execute("SELECT * FROM file_records WHERE id = ?", (cursor.lastrowid,))
        return _row_to_material(cursor.fetchone())


def _youtube_material_metadata(job, stage):
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    return {
        "stage": stage,
        "videoId": job.get("videoId") or "",
        "url": job.get("url") or "",
        "title": job.get("title") or "",
        "channel": job.get("channel") or "",
        "subscribers": job.get("subscribers") or "",
        "publishedAt": job.get("publishedAt") or "",
        "processVersion": job.get("processVersion") or "translation_v1",
        "subtitleLanguage": target_language,
        "subtitleLanguageLabel": language_meta["label"],
        "subtitleSize": _normalize_subtitle_size(job.get("subtitleSize")),
        "translatorLabel": _normalize_translator_label(job.get("translatorLabel")),
    }


def _save_processed_video_to_material(file_path, job=None):
    job = job or {}
    material = register_material(
        file_path,
        source_type="youtube_processed",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "processed"),
        copy_to_library=True,
    )
    video_id = job.get("videoId") or ""
    process_version = job.get("processVersion") or "translation_v1"
    if video_id:
        with sqlite3.connect(_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            replaced = _delete_replaced_processed_materials(
                cursor,
                video_id,
                process_version,
                material.get("id"),
            )
            sync_result = _sync_youtube_processed_state(cursor, video_id)
            conn.commit()
        material["replacedMaterials"] = replaced
        material["sync"] = sync_result
    return material


def _register_downloaded_video_material(file_path, job=None):
    job = job or {}
    return register_material(
        file_path,
        source_type="youtube_download",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "downloaded"),
        copy_to_library=False,
    )


def _validate_publish_processed_files(file_list):
    if not file_list:
        raise ValueError("文件列表不能为空")

    normalized_paths = [str(item or "").strip() for item in file_list if str(item or "").strip()]
    if len(normalized_paths) != len(file_list):
        raise ValueError("文件列表包含无效路径")

    if len(normalized_paths) != 1:
        raise ValueError("发布中心每次只能选择一个处理后视频")

    materials = []
    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_path in normalized_paths:
            cursor.execute(
                "SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?",
                (file_path, file_path),
            )
            record = cursor.fetchone()
            if not record:
                raise ValueError(f"发布文件未登记到素材库: {file_path}")
            material = _row_to_material(record)
            if material.get("source_type") != "youtube_processed":
                raise ValueError("发布中心只支持处理后视频，请先完成字幕处理和兼容转码。")
            resolved_path = _material_file_path(material)
            if not resolved_path or not resolved_path.is_file():
                raise ValueError(f"处理后视频文件不存在: {file_path}")
            materials.append(material)
    return normalized_paths, materials


def _assert_publish_targets_available(material, targets):
    video_id = material.get("source_video_id") or _material_source_video_id(material)
    if not video_id:
        raise ValueError("发布素材未绑定视频线索，无法校验平台发布状态")

    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for target in targets:
            platform_type = int(target.get("platformType") or 0)
            cursor.execute(
                """
                SELECT id FROM published_youtube_materials
                WHERE video_id = ? AND platform_type = ?
                  AND deleted_at IS NULL
                  AND COALESCE(NULLIF(status, ''), 'success') IN ('pending', 'running', 'success')
                LIMIT 1
                """,
                (video_id, platform_type),
            )
            if cursor.fetchone():
                raise WorkflowConflictError(
                    f"该视频已发布或正在发布到{platform_name(platform_type)}，不能重复发布到同一平台。",
                    "VF-PUBLISH-DUPLICATE-PLATFORM",
                    "PUBLISH_DUPLICATE_PLATFORM",
                    {"videoId": video_id, "platformType": platform_type},
                )
    return video_id


def _mark_published_materials(
    file_list,
    platform_type=None,
    title="",
    account_count=0,
    account_file="",
    publish_task_id="",
    status="success",
    message="发布成功",
    duration_ms=0,
    account_name="",
):
    if not file_list:
        return []

    platform_name_value = platform_name(platform_type)
    published_at = _now_iso()
    updated = []

    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_path in file_list:
            cursor.execute(
                "SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?",
                (file_path, file_path),
            )
            record = cursor.fetchone()
            if not record:
                continue
            material = _row_to_material(record)
            video_id = material.get("source_video_id") or _material_source_video_id(material)
            if not video_id:
                continue

            video = _get_youtube_video_record(video_id) or {}
            _archive_published_material(
                cursor,
                material,
                video,
                platform_name_value,
                published_at,
                publish_title=title,
                account_count=account_count,
                platform_type=platform_type,
                account_file=account_file,
                publish_task_id=publish_task_id,
                status=status,
                message=message,
                duration_ms=duration_ms,
                account_name=account_name,
            )
            if status == "success":
                cursor.execute(
                    """
                    UPDATE youtube_videos
                    SET publish_status = 1, updated_at = ?
                    WHERE video_id = ?
                    """,
                    (published_at, video_id),
                )
            cursor.execute(
                """
                UPDATE youtube_workflow_jobs
                SET step = 'publish',
                    message = ?,
                    published_at = ?,
                    publish_command = ?,
                    updated_at = ?
                WHERE video_id = ?
                """,
                (
                    "发布中心已提交发布任务" if status == "success" else f"发布中心记录平台状态：{message or status}",
                    published_at,
                    f"platform={platform_name_value}; title={title}; accounts={account_count}; status={status}",
                    published_at,
                    video_id,
                ),
            )
            updated.append(video_id)
        conn.commit()
    return updated


def _active_success_publish_count(cursor, video_id):
    if not video_id:
        return 0
    cursor.execute('''
    SELECT COUNT(*) AS total
    FROM published_youtube_materials
    WHERE video_id = ?
      AND deleted_at IS NULL
      AND COALESCE(NULLIF(status, ''), 'success') = 'success'
    ''', (video_id,))
    row = cursor.fetchone()
    return int((row or {})["total"] or 0)


def _sync_video_publish_status_from_records(cursor, video_id):
    if not video_id:
        return 0
    success_count = _active_success_publish_count(cursor, video_id)
    cursor.execute('''
    UPDATE youtube_videos
    SET publish_status = ?, updated_at = ?
    WHERE video_id = ?
    ''', (1 if success_count else 0, _now_iso(), video_id))
    return 1 if success_count else 0


def _strip_publish_title_meta(value=""):
    return str(value or "").split("; description=", 1)[0].strip()


def _publish_record_time(record):
    return record.get("updatedAt") or record.get("publishedAt") or record.get("createdAt") or ""


def _publish_task_status(targets):
    statuses = [str(item.get("status") or "success") for item in targets]
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "pending" for status in statuses):
        return "pending"
    success_count = sum(1 for status in statuses if status == "success")
    failed_count = sum(1 for status in statuses if status in {"failed", "timeout"})
    if success_count and failed_count:
        return "partial"
    if success_count:
        return "success"
    if failed_count:
        return "failed"
    return statuses[0] if statuses else "unknown"


def _publish_task_summary(targets):
    summary = {"success": 0, "failed": 0, "timeout": 0, "running": 0, "pending": 0, "total": len(targets)}
    for target in targets:
        status = str(target.get("status") or "success")
        if status in summary:
            summary[status] += 1
        elif status in {"failed", "timeout"}:
            summary["failed"] += 1
    return summary


def _row_to_publish_task(task_id, targets):
    first = targets[0] if targets else {}
    targets = sorted(targets, key=lambda item: (int(item.get("platformType") or 0), int(item.get("id") or 0)))
    task_time = max((_publish_record_time(item) for item in targets), default="")
    chinese_title = (
        _strip_publish_title_meta(first.get("publishTitle"))
        or (first.get("metadata") or {}).get("publishTitle")
        or (first.get("metadata") or {}).get("title")
        or first.get("filename")
        or "未命名发布任务"
    )
    english_title = first.get("title") or first.get("filename") or first.get("sourceUrl") or "暂无英文标题"
    return {
        "taskId": task_id,
        "videoId": first.get("videoId") or "",
        "chineseTitle": chinese_title,
        "englishTitle": english_title,
        "filesize": first.get("filesize") or 0,
        "thumbnail": first.get("thumbnail") or "",
        "filePath": first.get("filePath") or "",
        "sourceUrl": first.get("sourceUrl") or "",
        "publishedAt": task_time,
        "overallStatus": _publish_task_status(targets),
        "summary": _publish_task_summary(targets),
        "targets": targets,
    }


def list_publish_tasks(limit=20):
    init_database_tables()
    limit = max(1, min(int(limit or 20), 100))
    fetch_limit = max(limit * 8, 80)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM published_youtube_materials
        WHERE deleted_at IS NULL
        ORDER BY COALESCE(updated_at, published_at, created_at) DESC, id DESC
        LIMIT ?
        ''', (fetch_limit,))
        grouped = {}
        for row in cursor.fetchall():
            record = _row_to_published_material(row)
            task_id = record.get("publishTaskId") or f"legacy:{record.get('videoId') or record.get('sourceUrl') or record.get('id')}"
            grouped.setdefault(task_id, []).append(record)
        tasks = [_row_to_publish_task(task_id, targets) for task_id, targets in grouped.items()]
        tasks.sort(key=lambda item: item.get("publishedAt") or "", reverse=True)
        return tasks[:limit]


def delete_publish_target_record(record_id):
    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM published_youtube_materials WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("发布记录不存在")
        record = dict(row)
        status = record.get("status") or "success"
        if status in {"pending", "running"}:
            raise WorkflowConflictError(
                "发布中或等待发布的记录不能删除。",
                "VF-PUBLISH-RECORD-ACTIVE",
                "PUBLISH_RECORD_ACTIVE",
                {"recordId": record_id, "status": status},
            )

        now = _now_iso()
        cursor.execute('''
        UPDATE published_youtube_materials
        SET deleted_at = ?, updated_at = ?
        WHERE id = ?
        ''', (now, now, record_id))
        publish_status = _sync_video_publish_status_from_records(cursor, record.get("video_id") or "")
        conn.commit()
        record["deleted_at"] = now
        record["updated_at"] = now
        return {
            "record": _row_to_published_material(record),
            "videoId": record.get("video_id") or "",
            "publishStatus": publish_status,
            "message": "已删除本地发布记录，平台上的已发布视频不会被删除。",
        }

