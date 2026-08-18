"""Agent 视频状态卡：稳定分页、会话选择和受控缩略图定位。"""

from __future__ import annotations

import secrets as _secrets
import threading as _threading
import time as _time
from urllib.parse import quote as _urlquote


_AGENT_VIDEO_CARD_PAGE_SIZE = 5
_AGENT_VIDEO_CARD_TTL_SECONDS = 15 * 60
_AGENT_VIDEO_CARD_MAX_SNAPSHOTS = 12
_AGENT_VIDEO_CARD_SNAPSHOTS = {}
_AGENT_VIDEO_CARD_SNAPSHOTS_LOCK = _threading.Lock()


def _agent_video_card_cleanup(now=None):
    now = float(now if now is not None else _time.time())
    expired = [
        card_id for card_id, snapshot in _AGENT_VIDEO_CARD_SNAPSHOTS.items()
        if float(snapshot.get("expiresAt") or 0) <= now
    ]
    for card_id in expired:
        _AGENT_VIDEO_CARD_SNAPSHOTS.pop(card_id, None)


def _agent_video_card_store_snapshot(snapshot):
    session = get_agent_session(snapshot.get("sessionId"))
    context = session.get("context") if isinstance(session, dict) else {}
    persisted = context.get("agentVideoCardSnapshots") if isinstance(context, dict) else {}
    now = _time.time()
    active = {
        str(card_id): item
        for card_id, item in (persisted or {}).items()
        if isinstance(item, dict) and float(item.get("expiresAt") or 0) > now
    }
    active[str(snapshot["cardId"])] = snapshot
    if len(active) > _AGENT_VIDEO_CARD_MAX_SNAPSHOTS:
        active = dict(sorted(
            active.items(),
            key=lambda item: float(item[1].get("createdAt") or 0),
            reverse=True,
        )[:_AGENT_VIDEO_CARD_MAX_SNAPSHOTS])
    update_agent_session_context(snapshot["sessionId"], {"agentVideoCardSnapshots": active})


def _agent_video_card_snapshot(card_id, session_id):
    _agent_video_card_cleanup()
    snapshot = _AGENT_VIDEO_CARD_SNAPSHOTS.get(card_id)
    if snapshot and snapshot.get("sessionId") == session_id:
        return snapshot
    session = get_agent_session(session_id)
    context = session.get("context") if isinstance(session, dict) else {}
    persisted = context.get("agentVideoCardSnapshots") if isinstance(context, dict) else {}
    snapshot = persisted.get(card_id) if isinstance(persisted, dict) else None
    if isinstance(snapshot, dict) and snapshot.get("sessionId") == session_id:
        snapshot = dict(snapshot)
        snapshot["cardId"] = card_id
        if float(snapshot.get("expiresAt") or 0) <= _time.time():
            snapshot["expiresAt"] = _time.time() + _AGENT_VIDEO_CARD_TTL_SECONDS
            _agent_video_card_store_snapshot(snapshot)
        _AGENT_VIDEO_CARD_SNAPSHOTS[card_id] = snapshot
        return snapshot
    return None


def _agent_video_card_status_items(status):
    status = str(status or "initial").strip()
    if status == "pending":
        status = "initial"
    clause, values = _youtube_video_status_clause(status)
    init_youtube_video_table()
    owner_user_id = _agent_current_user_id()
    if owner_user_id is None:
        raise PermissionError("Agent 视频卡查询缺少当前用户身份")
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        _reconcile_youtube_statuses_with_material_records(cursor, owner_user_id)
        conn.commit()
        where_sql = f"WHERE owner_user_id = %s AND {clause}" if clause else "WHERE owner_user_id = %s"
        cursor.execute(
            f"SELECT * FROM youtube_videos {where_sql} ORDER BY updated_at DESC, video_id DESC",
            [owner_user_id, *values],
        )
        return [_row_to_youtube_video(row) for row in cursor.fetchall()]


def _agent_video_card_details(videos):
    """Attach compact, user-safe workflow details to cards in one query per table."""
    videos = [item for item in videos if isinstance(item, dict) and item.get("id")]
    if not videos:
        return videos
    video_ids = [str(item["id"]) for item in videos]
    placeholders = ",".join("%s" for _ in video_ids)
    owner_user_id = _agent_current_user_id()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT video_id, process_version, operation, status, step, message, updated_at
            FROM youtube_workflow_jobs
            WHERE owner_user_id = %s AND video_id IN ({placeholders})
            ORDER BY updated_at DESC, created_at DESC
            """,
            [owner_user_id, *video_ids],
        )
        latest_jobs = {}
        for row in cursor.fetchall():
            latest_jobs.setdefault(str(row["video_id"] or ""), dict(row))
        cursor.execute(
            f"""
            SELECT video_id, platform, platform_type, account_name, status
            FROM published_youtube_materials
            WHERE owner_user_id = %s AND video_id IN ({placeholders})
              AND deleted_at IS NULL AND invalidated_at IS NULL
              AND COALESCE(NULLIF(status, ''), 'confirmed') IN ('confirmed', 'success', 'reused')
            ORDER BY platform_type, id
            """,
            [owner_user_id, *video_ids],
        )
        published = {}
        for row in cursor.fetchall():
            published.setdefault(str(row["video_id"] or ""), []).append({
                "platform": row["platform"] or platform_name(row["platform_type"]),
                "platformType": int(row["platform_type"] or 0),
                "accountName": row["account_name"] or "",
            })
    for video in videos:
        video_id = str(video["id"])
        latest = latest_jobs.get(video_id) or {}
        video["latestJob"] = {
            "status": latest.get("status") or "",
            "step": latest.get("step") or "",
            "message": str(latest.get("message") or "")[:160],
            "updatedAt": latest.get("updated_at") or "",
        }
        video["processVersion"] = latest.get("process_version") or ""
        video["publishedPlatforms"] = published.get(video_id, [])
        video["hasPublishDraft"] = bool((video.get("publishDraft") or {}).get("title") or (video.get("publishDraft") or {}).get("description"))
    return videos


def _agent_video_card_thumbnail(video, session_id=""):
    processed = int(video.get("translateStatus") or 0) in {1, 2} or int(video.get("publishStatus") or 0) == 1
    video_id = str(video.get("id") or "")
    if processed and video_id:
        return {
            "thumbnail": f"/agents/videos/{_urlquote(video_id, safe='')}/thumbnail?variant=processed&sessionId={_urlquote(str(session_id or ''), safe='')}",
            "thumbnailVariant": "processed",
        }
    return {"thumbnail": video.get("thumbnail") or "", "thumbnailVariant": "source"}


def _agent_video_status_card_item(video, label="", session_id=""):
    video = video if isinstance(video, dict) else {}
    publish_draft = video.get("publishDraft") or {}
    state = label or (
        "已发布" if int(video.get("publishStatus") or 0) else
        "已处理未发布" if int(video.get("translateStatus") or 0) in {1, 2} else
        "已下载未处理" if int(video.get("downloadStatus") or 0) else "待处理"
    )
    return {
        "id": str(video.get("id") or ""),
        "shortCode": f"#{str(video.get('id') or '')}",
        "title": video.get("title") or "未命名视频",
        "channel": video.get("channel") or "",
        "duration": video.get("duration") or "",
        "status": state,
        "updatedAt": video.get("updatedAt") or "",
        "processVersion": video.get("processVersion") or "",
        "latestJob": video.get("latestJob") or {},
        "publishedPlatforms": video.get("publishedPlatforms") or [],
        "hasPublishDraft": bool(video.get("hasPublishDraft")),
        "draftTitle": publish_draft.get("title") or "",
        "draftDescription": publish_draft.get("description") or "",
        "draftTags": publish_draft.get("tags") or [],
        "detail": " · ".join(value for value in (video.get("channel"), video.get("duration"), state) if value),
        "videoContext": {
            "videoId": str(video.get("id") or ""),
            "title": video.get("title") or "",
            "channel": video.get("channel") or "",
            "duration": video.get("duration") or "",
        },
        **_agent_video_card_thumbnail(video, session_id),
    }


def _agent_video_card_page(snapshot, page):
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    snapshot_items = snapshot.get("items") or []
    total = len(snapshot_items)
    page_count = max(1, (total + _AGENT_VIDEO_CARD_PAGE_SIZE - 1) // _AGENT_VIDEO_CARD_PAGE_SIZE)
    page = max(1, min(page, page_count))
    items = snapshot_items[(page - 1) * _AGENT_VIDEO_CARD_PAGE_SIZE:page * _AGENT_VIDEO_CARD_PAGE_SIZE]
    return {
        "cardId": snapshot["cardId"],
        "type": "video_status",
        "title": str(snapshot.get("label") or "视频") if str(snapshot.get("label") or "").endswith("视频") else f"{snapshot.get('label') or '视频'}视频",
        "status": snapshot.get("status") or "initial",
        "count": total,
        "page": page,
        "pageSize": _AGENT_VIDEO_CARD_PAGE_SIZE,
        "pageCount": page_count,
        "items": items,
        "expiresAt": snapshot.get("expiresAt"),
    }


def create_agent_video_status_card(session_id, status, label=""):
    session_id = str(session_id or "").strip()
    if not get_agent_session(session_id):
        raise ValueError("Agent 会话不存在或已失效。")
    status = str(status or "initial").strip()
    videos = _agent_video_card_details(_agent_video_card_status_items(status))
    now = _time.time()
    snapshot = {
        "cardId": _secrets.token_urlsafe(18),
        "sessionId": session_id,
        "status": status,
        "label": str(label or AGENT_VIDEO_STATUSES.get(status, "")),
        "items": [_agent_video_status_card_item(video, str(label or AGENT_VIDEO_STATUSES.get(status, "")), session_id) for video in videos],
        "createdAt": now,
        "expiresAt": now + _AGENT_VIDEO_CARD_TTL_SECONDS,
    }
    with _AGENT_VIDEO_CARD_SNAPSHOTS_LOCK:
        _agent_video_card_cleanup(now)
        _AGENT_VIDEO_CARD_SNAPSHOTS[snapshot["cardId"]] = snapshot
    _agent_video_card_store_snapshot(snapshot)
    update_agent_video_selection(session_id, [], snapshot["cardId"])
    return _agent_video_card_page(snapshot, 1)


def create_agent_video_selection_card(session_id, videos, label="视频信息"):
    """Create the same signed, session-scoped selection card for arbitrary local videos."""
    session_id = str(session_id or "").strip()
    if not get_agent_session(session_id):
        raise ValueError("Agent 会话不存在或已失效。")
    now = _time.time()
    items = [_agent_video_status_card_item(video, session_id=session_id) for video in _agent_video_card_details(list(videos or []))]
    snapshot = {
        "cardId": _secrets.token_urlsafe(18),
        "sessionId": session_id,
        "status": "detail",
        "label": str(label or "视频信息"),
        "items": items,
        "createdAt": now,
        "expiresAt": now + _AGENT_VIDEO_CARD_TTL_SECONDS,
    }
    with _AGENT_VIDEO_CARD_SNAPSHOTS_LOCK:
        _agent_video_card_cleanup(now)
        _AGENT_VIDEO_CARD_SNAPSHOTS[snapshot["cardId"]] = snapshot
    _agent_video_card_store_snapshot(snapshot)
    return _agent_video_card_page(snapshot, 1)


def get_agent_video_status_card_page(card_id, session_id, page):
    card_id = str(card_id or "").strip()
    session_id = str(session_id or "").strip()
    with _AGENT_VIDEO_CARD_SNAPSHOTS_LOCK:
        snapshot = _agent_video_card_snapshot(card_id, session_id)
        if not snapshot:
            raise ValueError("视频状态卡已失效，请重新查询。")
        return _agent_video_card_page(snapshot, page)


def update_agent_video_selection(session_id, video_ids, card_id):
    session_id = str(session_id or "").strip()
    card_id = str(card_id or "").strip()
    if not isinstance(video_ids, list):
        raise ValueError("视频选择格式不正确。")
    selected = []
    for video_id in video_ids:
        normalized = str(video_id or "").strip()
        if normalized and normalized not in selected:
            selected.append(normalized)
    if len(selected) > 100:
        raise ValueError("一次最多选择 100 个视频。")
    if selected:
        if not card_id:
            raise ValueError("请在视频卡片中选择视频。")
        with _AGENT_VIDEO_CARD_SNAPSHOTS_LOCK:
            snapshot = _agent_video_card_snapshot(card_id, session_id)
            if not snapshot:
                raise ValueError("视频选择卡已失效，请重新查询后选择。")
            allowed = {str(item.get("id") or "") for item in snapshot.get("items") or []}
        if any(video_id not in allowed for video_id in selected):
            raise ValueError("所选视频不在当前视频卡片中。")
    context = update_agent_session_context(session_id, {
        "agentVideoSelection": selected,
        "agentVideoSelectionCardId": card_id if selected else "",
    })
    if context is None:
        raise ValueError("Agent 会话不存在或已失效。")
    invalidate = globals().get("invalidate_agent_copywriting_selection")
    if callable(invalidate):
        invalidate(session_id)
    proposals = globals().get("_AGENT_EXECUTION_PROPOSALS")
    proposal_lock = globals().get("_AGENT_EXECUTION_PROPOSALS_LOCK")
    if isinstance(proposals, dict) and proposal_lock is not None:
        with proposal_lock:
            expired = [proposal_id for proposal_id, proposal in proposals.items() if proposal.get("sessionId") == session_id]
            for proposal_id in expired:
                proposals.pop(proposal_id, None)
    return {"sessionId": session_id, "videoIds": selected}


def get_agent_video_selection(session_id):
    session = get_agent_session(session_id)
    context = session.get("context") if isinstance(session, dict) else {}
    selected = context.get("agentVideoSelection") if isinstance(context, dict) else []
    return [str(item) for item in selected if str(item).strip()] if isinstance(selected, list) else []


def agent_video_processed_thumbnail_path(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        owner_user_id = _agent_current_user_id()
        video_row = cursor.execute(
            "SELECT * FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s",
            (video_id, owner_user_id),
        ).fetchone()
        material = _find_latest_youtube_material(cursor, video_id, "youtube_processed", owner_user_id)
    if not video_row or not material:
        return None
    material = dict(material)
    path = _local_youtube_thumbnail_path(
        video_id,
        str(_material_file_path(material) or ""),
        _material_metadata(material),
    )
    return path or None


def agent_video_source_thumbnail(video_id):
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            "SELECT thumbnail FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s",
            (str(video_id or "").strip(), _agent_current_user_id()),
        ).fetchone()
    return row["thumbnail"] if row else ""
