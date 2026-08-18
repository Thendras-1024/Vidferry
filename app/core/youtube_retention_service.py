"""已发布 YouTube 线索的本地媒体保留与清理。"""

import datetime as _retention_datetime_module
from pathlib import Path as _RetentionPath


def _youtube_storage_scope_clause(scope):
    scope = str(scope or "active").strip().lower()
    if scope == "history":
        return "local_files_state = 'purged'", []
    return "local_files_state != 'purged'", []


def _retention_datetime(value):
    if not value:
        return None
    try:
        return _retention_datetime_module.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _youtube_local_retention_eligible(records, anchor_at, now=None):
    records = list(records or [])
    anchor = _retention_datetime(anchor_at)
    current = _retention_datetime(now) if now else _retention_datetime_module.datetime.now(anchor.tzinfo if anchor else None)
    return bool(
        records
        and anchor
        and all(str(record.get("status") or "") in {"confirmed", "reused"} for record in records)
        and current >= anchor + _retention_datetime_module.timedelta(days=VIDEO_LOCAL_RETENTION_DAYS)
    )


def _refresh_youtube_video_retention(cursor, video_id, owner_user_id):
    cursor.execute('''
    SELECT status, published_at
    FROM published_youtube_materials
    WHERE video_id = %s AND owner_user_id = %s
      AND deleted_at IS NULL AND invalidated_at IS NULL
    ORDER BY published_at DESC, id DESC
    ''', (video_id, owner_user_id))
    records = [dict(row) for row in cursor.fetchall()]
    if records and all(str(record.get("status") or "") in {"confirmed", "reused"} for record in records):
        anchors = [record.get("published_at") for record in records if record.get("published_at")]
        anchor = max(anchors) if anchors else None
    else:
        anchor = None
    cursor.execute('''
    UPDATE youtube_videos
    SET retention_anchor_at = %s, updated_at = CURRENT_TIMESTAMP
    WHERE video_id = %s AND owner_user_id = %s AND local_files_state != 'purged'
    ''', (anchor, video_id, owner_user_id))
    return records, anchor


def _retention_path(path):
    candidate = _RetentionPath(str(path or ""))
    if not candidate.is_file():
        return None
    try:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in (YOUTUBE_DOWNLOAD_DIR, YOUTUBE_PROCESSED_DIR)):
            return resolved
    except (OSError, ValueError):
        return None
    return None


def _retention_path_shared(path, video_id, owner_user_id):
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT 1 FROM file_records
        WHERE (file_path = %s OR storage_key = %s)
          AND NOT (owner_user_id = %s AND source_video_id = %s)
        LIMIT 1
        ''', (str(path), str(path), owner_user_id, video_id))
        return bool(cursor.fetchone())


def _purge_youtube_video_local_files(video_id, owner_user_id):
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        cursor.execute('''
        SELECT * FROM youtube_videos
        WHERE video_id = %s AND owner_user_id = %s
          AND local_files_state IN ('available', 'purge_failed')
        FOR UPDATE
        ''', (video_id, owner_user_id))
        video = cursor.fetchone()
        if not video:
            return {"status": "skipped", "videoId": video_id}
        _assert_no_active_youtube_job(cursor, video_id, owner_user_id)
        cursor.execute('''
        SELECT 1 FROM scheduled_publish_tasks
        WHERE video_id = %s AND owner_user_id = %s AND status IN ('scheduled', 'queued', 'running')
        LIMIT 1
        ''', (video_id, owner_user_id))
        if cursor.fetchone():
            return {"status": "skipped", "videoId": video_id}
        records, anchor = _refresh_youtube_video_retention(cursor, video_id, owner_user_id)
        now = _now_iso()
        if not _youtube_local_retention_eligible(records, anchor, now):
            return {"status": "skipped", "videoId": video_id}
        cursor.execute('''
        UPDATE youtube_videos
        SET local_files_state = 'purging', purge_attempted_at = %s, purge_error = ''
        WHERE video_id = %s AND owner_user_id = %s
        ''', (now, video_id, owner_user_id))
        cursor.execute('''
        SELECT id, file_path, storage_key
        FROM file_records
        WHERE owner_user_id = %s AND source_video_id = %s
          AND source_type IN ('youtube_download', 'youtube_processed') AND status != 'purged'
        ''', (owner_user_id, video_id))
        materials = [dict(row) for row in cursor.fetchall()]
        video_record = dict(video)

    candidates = {
        str(value or "") for value in (
            video_record.get("downloaded_file_path"), video_record.get("processed_file_path"),
            video_record.get("editing_body_path"), video_record.get("editing_ass_path"),
            *(item.get("file_path") or item.get("storage_key") for item in materials),
        ) if value
    }
    download_path = _retention_path(video_record.get("downloaded_file_path"))
    if download_path:
        candidates.update(str(download_path.with_suffix(extension)) for extension in (".webp", ".jpg", ".jpeg", ".png"))
    deleted_count, errors = 0, []
    for raw_path in candidates:
        path = _retention_path(raw_path)
        if not path:
            continue
        if _retention_path_shared(path, video_id, owner_user_id):
            continue
        try:
            path.unlink()
            deleted_count += 1
        except OSError as exc:
            errors.append(type(exc).__name__)

    with _db_connect() as conn:
        cursor = conn.cursor()
        now = _now_iso()
        if errors:
            cursor.execute('''
            UPDATE youtube_videos
            SET local_files_state = 'purge_failed', purge_error = %s, updated_at = %s
            WHERE video_id = %s AND owner_user_id = %s
            ''', (",".join(sorted(set(errors))), now, video_id, owner_user_id))
            return {"status": "failed", "videoId": video_id, "deleted": deleted_count}
        cursor.execute('''
        UPDATE file_records
        SET status = 'purged', purged_at = %s, file_path = '', storage_key = ''
        WHERE owner_user_id = %s AND source_video_id = %s
          AND source_type IN ('youtube_download', 'youtube_processed')
        ''', (now, owner_user_id, video_id))
        cursor.execute('''
        UPDATE youtube_videos
        SET local_files_state = 'purged', local_files_purged_at = %s, purge_error = '',
            downloaded_file_path = '', processed_file_path = '', editing_body_path = '', editing_ass_path = '',
            download_status = 0, translate_status = 0, updated_at = %s
        WHERE video_id = %s AND owner_user_id = %s
        ''', (now, now, video_id, owner_user_id))
    return {"status": "purged", "videoId": video_id, "deleted": deleted_count}


def _youtube_local_cleanup_candidates(now=None):
    current = _retention_datetime(now) if now else _retention_datetime_module.datetime.now()
    cutoff = current - _retention_datetime_module.timedelta(days=VIDEO_LOCAL_RETENTION_DAYS)
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute('''
        SELECT video_id, owner_user_id
        FROM youtube_videos AS video
        WHERE local_files_state IN ('available', 'purge_failed')
          AND EXISTS (
              SELECT 1 FROM published_youtube_materials AS material
              WHERE material.video_id = video.video_id AND material.owner_user_id = video.owner_user_id
                AND material.deleted_at IS NULL AND material.invalidated_at IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM published_youtube_materials AS material
              WHERE material.video_id = video.video_id AND material.owner_user_id = video.owner_user_id
                AND material.deleted_at IS NULL AND material.invalidated_at IS NULL
                AND material.status NOT IN ('confirmed', 'reused')
          )
          AND (
              SELECT MAX(material.published_at) FROM published_youtube_materials AS material
              WHERE material.video_id = video.video_id AND material.owner_user_id = video.owner_user_id
                AND material.deleted_at IS NULL AND material.invalidated_at IS NULL
          ) <= %s
          AND NOT EXISTS (
              SELECT 1 FROM scheduled_publish_tasks AS task
              WHERE task.video_id = video.video_id AND task.owner_user_id = video.owner_user_id
                AND task.status IN ('scheduled', 'queued', 'running')
          )
          AND NOT EXISTS (
              SELECT 1 FROM youtube_workflow_jobs AS job
              WHERE job.video_id = video.video_id AND job.owner_user_id = video.owner_user_id
                AND job.status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish')
          )
        ORDER BY video.updated_at ASC
        LIMIT %s
        ''', (cutoff.isoformat(), VIDEO_LOCAL_CLEANUP_BATCH_SIZE))
        return [dict(row) for row in cursor.fetchall()]


def run_youtube_local_cleanup_once():
    if VIDEO_LOCAL_CLEANUP_MODE == "off":
        return {"mode": "off", "processed": 0}
    init_youtube_video_table()
    candidates = _youtube_local_cleanup_candidates()
    if VIDEO_LOCAL_CLEANUP_MODE == "report":
        backend_logger.info("youtube local cleanup report : candidates = %s", len(candidates))
        return {"mode": "report", "processed": 0, "candidates": len(candidates)}
    results = []
    for item in candidates:
        try:
            results.append(_purge_youtube_video_local_files(item["video_id"], item["owner_user_id"]))
        except WorkflowConflictError:
            results.append({"status": "skipped", "videoId": item["video_id"]})
    backend_logger.info("youtube local cleanup completed : candidates = %s | purged = %s", len(candidates), sum(item.get("status") == "purged" for item in results))
    return {"mode": "delete", "processed": len(results), "results": results}
