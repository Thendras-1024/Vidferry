"""YouTube 原题中文翻译缓存：新建即时排队，列表只补齐当前页。"""

import json as _title_translation_json
import threading as _title_translation_threading


_TITLE_TRANSLATION_ACTIVE = set()
_TITLE_TRANSLATION_LOCK = _title_translation_threading.Lock()
_TITLE_TRANSLATION_FAILURE_BACKOFF_SECONDS = 6 * 3600
_TITLE_TRANSLATION_PAGE_LIMIT = 20


def _source_title_translation_map(cursor, video_ids, owner_user_id):
    video_ids = [str(video_id or "").strip() for video_id in video_ids if str(video_id or "").strip()]
    if not video_ids:
        return {}
    cursor.execute(f'''
    SELECT video_id, metadata
    FROM youtube_workflow_events
    WHERE owner_user_id = %s
      AND stage = 'source_title_translation'
      AND status = 'success'
      AND video_id IN ({_sql_placeholders(video_ids)})
    ORDER BY ended_at DESC NULLS LAST, id DESC
    ''', [owner_user_id, *video_ids])
    titles = {}
    for row in cursor.fetchall():
        video_id = str(row["video_id"] or "")
        if not video_id or video_id in titles:
            continue
        metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        if not metadata:
            try:
                metadata = _title_translation_json.loads(row["metadata"] or "{}")
            except (TypeError, ValueError):
                continue
        title = str(metadata.get("sourceTitleZh") or "").strip()
        if _is_valid_source_title_translation(title):
            titles[video_id] = title
    return titles


def _attach_source_title_translations(cursor, videos, owner_user_id):
    titles = _source_title_translation_map(cursor, [video.get("id") for video in videos], owner_user_id)
    for video in videos:
        video["chineseTitle"] = titles.get(str(video.get("id") or ""), "")
    return any(
        not str(video.get("chineseTitle") or "").strip() and bool(str(video.get("title") or "").strip())
        for video in videos
    )


def _source_title_translation_candidates(cursor, videos, owner_user_id, limit=None):
    """只用调用方给出的页或管理端快照查询待补齐项，不扫描历史表。"""
    page = []
    seen = set()
    for video in videos or []:
        video_id = str(video.get("id") or video.get("video_id") or "").strip()
        title = str(video.get("title") or "").strip()
        if video_id and title and video_id not in seen:
            seen.add(video_id)
            page.append((video_id, title))
    if not page:
        return []
    values_sql = ", ".join("(%s, %s)" for _ in page)
    limit_sql = "" if limit is None else "LIMIT %s"
    page_params = [value for item in page for value in item]
    params = [*page_params, owner_user_id, owner_user_id, owner_user_id, _TITLE_TRANSLATION_FAILURE_BACKOFF_SECONDS]
    if limit is not None:
        params.append(int(limit))
    cursor.execute(f'''
    WITH page(video_id, title) AS (VALUES {values_sql})
    SELECT page.video_id, page.title
    FROM page
    WHERE NOT EXISTS (
        SELECT 1 FROM youtube_workflow_events event
        WHERE event.owner_user_id = %s AND event.video_id = page.video_id
          AND event.stage = 'source_title_translation' AND event.status = 'success'
    )
      AND NOT EXISTS (
        SELECT 1 FROM youtube_workflow_events event
        WHERE event.owner_user_id = %s AND event.video_id = page.video_id
          AND event.stage = 'source_title_translation' AND event.status = 'running'
    )
      AND NOT EXISTS (
        SELECT 1 FROM youtube_workflow_events event
        WHERE event.owner_user_id = %s AND event.video_id = page.video_id
          AND event.stage = 'source_title_translation' AND event.status = 'failed'
          AND event.ended_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
    )
    {limit_sql}
    ''', params)
    return [dict(row) for row in cursor.fetchall()]


def _run_source_title_translation_batch(owner_user_id, videos):
    try:
        for video in videos:
            video_id = str(video.get("video_id") or "").strip()
            if video_id:
                _ensure_source_title_translation({
                    "ownerUserId": owner_user_id,
                    "videoId": video_id,
                    "title": video.get("title") or "",
                })
    finally:
        with _TITLE_TRANSLATION_LOCK:
            for video in videos:
                _TITLE_TRANSLATION_ACTIVE.discard((int(owner_user_id), str(video.get("video_id") or "")))


def _queue_source_title_translation_batch(owner_user_id, videos):
    owner_user_id = int(owner_user_id)
    selected = []
    with _TITLE_TRANSLATION_LOCK:
        for video in videos or []:
            video_id = str(video.get("video_id") or "").strip()
            if not video_id or (owner_user_id, video_id) in _TITLE_TRANSLATION_ACTIVE:
                continue
            _TITLE_TRANSLATION_ACTIVE.add((owner_user_id, video_id))
            selected.append(video)
    if not selected:
        return 0
    try:
        _submit_background_task(
            "title_translation",
            _run_source_title_translation_batch,
            owner_user_id,
            selected,
            owner_user_id=owner_user_id,
        )
        return len(selected)
    except Exception as exc:
        with _TITLE_TRANSLATION_LOCK:
            for video in selected:
                _TITLE_TRANSLATION_ACTIVE.discard((owner_user_id, str(video.get("video_id") or "")))
        backend_logger.warning(
            "source title translation queue failed : owner_user_id = %s | error_type = %s",
            owner_user_id,
            type(exc).__name__,
        )
        return 0


def _queue_source_title_translations(owner_user_id, videos, limit=_TITLE_TRANSLATION_PAGE_LIMIT):
    owner_user_id = int(owner_user_id)
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        candidates = _source_title_translation_candidates(conn.cursor(), videos, owner_user_id, limit)
    return _queue_source_title_translation_batch(owner_user_id, candidates)


def queue_all_source_title_translations(owner_user_id):
    """仅供管理入口主动触发全量历史标题整理。"""
    owner_user_id = int(owner_user_id)
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT video_id, title
            FROM youtube_videos video
            WHERE video.owner_user_id = %s AND COALESCE(video.title, '') <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM youtube_workflow_events event
                  WHERE event.owner_user_id = video.owner_user_id AND event.video_id = video.video_id
                    AND event.stage = 'source_title_translation' AND event.status = 'success'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM youtube_workflow_events event
                  WHERE event.owner_user_id = video.owner_user_id AND event.video_id = video.video_id
                    AND event.stage = 'source_title_translation' AND event.status = 'running'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM youtube_workflow_events event
                  WHERE event.owner_user_id = video.owner_user_id AND event.video_id = video.video_id
                    AND event.stage = 'source_title_translation' AND event.status = 'failed'
                    AND event.ended_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
              )
            ORDER BY video.updated_at DESC, video.video_id DESC
            """,
            (owner_user_id, _TITLE_TRANSLATION_FAILURE_BACKOFF_SECONDS),
        )
        candidates = [dict(row) for row in cursor.fetchall()]
    return _queue_source_title_translation_batch(owner_user_id, candidates)
