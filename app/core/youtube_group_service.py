"""YouTube 视频线索分组管理。"""


def _row_to_youtube_video_group(row):
    item = dict(row)
    return {
        "id": int(item.get("id") or 0),
        "name": item.get("name") or "",
        "isDefault": bool(item.get("is_default") or 0),
        "videoCount": int(item.get("video_count") or 0),
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def _normalize_youtube_group_name(value):
    name = str(value or "").strip()
    if not name:
        raise ValueError("分组名称不能为空")
    if len(name) > 30:
        raise ValueError("分组名称不能超过 30 个字符")
    if any(ord(char) < 32 for char in name):
        raise ValueError("分组名称不能包含控制字符")
    return name


def _default_youtube_group(cursor, owner_user_id):
    cursor.execute("SELECT * FROM youtube_video_groups WHERE owner_user_id = ? AND is_default = 1 LIMIT 1", (owner_user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO youtube_video_groups (name, is_default, owner_user_id) VALUES (?, 1, ?) RETURNING id",
            (YOUTUBE_DEFAULT_GROUP_NAME, owner_user_id),
        )
        group_id = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM youtube_video_groups WHERE id = ? AND owner_user_id = ?", (group_id, owner_user_id))
        row = cursor.fetchone()
    return row


def _resolve_youtube_group(cursor, owner_user_id, group_id=None):
    if group_id in (None, ""):
        return _default_youtube_group(cursor, owner_user_id)
    try:
        normalized_id = int(group_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("groupId 必须是整数") from exc
    cursor.execute("SELECT * FROM youtube_video_groups WHERE id = ? AND owner_user_id = ?", (normalized_id, owner_user_id))
    row = cursor.fetchone()
    if not row:
        raise LookupError("视频分组不存在")
    return row


def list_youtube_video_groups(owner_user_id):
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT groups.*, COUNT(videos.id) AS video_count
        FROM youtube_video_groups groups
        LEFT JOIN youtube_videos videos ON videos.group_id = groups.id AND videos.owner_user_id = groups.owner_user_id
        WHERE groups.owner_user_id = ?
        GROUP BY groups.id
        ORDER BY groups.is_default DESC, groups.created_at ASC, groups.id ASC
        ''', (owner_user_id,))
        items = [_row_to_youtube_video_group(row) for row in cursor.fetchall()]
        if not items:
            default_row = _default_youtube_group(cursor, owner_user_id)
            items = [_row_to_youtube_video_group({**dict(default_row), "video_count": 0})]
    default_group = next((item for item in items if item["isDefault"]), None)
    return {"items": items, "defaultGroupId": default_group["id"] if default_group else None}


def create_youtube_video_group(name, owner_user_id):
    normalized_name = _normalize_youtube_group_name(name)
    init_youtube_video_table()
    try:
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "INSERT INTO youtube_video_groups (name, is_default, owner_user_id) VALUES (?, 0, ?) RETURNING id",
                (normalized_name, owner_user_id),
            )
            group_id = cursor.fetchone()[0]
            cursor.execute("SELECT *, 0 AS video_count FROM youtube_video_groups WHERE id = ? AND owner_user_id = ?", (group_id, owner_user_id))
            return _row_to_youtube_video_group(cursor.fetchone())
    except DATABASE_INTEGRITY_ERRORS as exc:
        raise ValueError("分组名称已存在") from exc


def rename_youtube_video_group(group_id, name, owner_user_id):
    normalized_name = _normalize_youtube_group_name(name)
    init_youtube_video_table()
    try:
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            group = _resolve_youtube_group(cursor, owner_user_id, group_id)
            if bool(group["is_default"]):
                raise ValueError("默认分组不能重命名")
            cursor.execute(
                "UPDATE youtube_video_groups SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_user_id = ?",
                (normalized_name, int(group_id), owner_user_id),
            )
            cursor.execute('''
            SELECT groups.*, COUNT(videos.id) AS video_count
            FROM youtube_video_groups groups
            LEFT JOIN youtube_videos videos ON videos.group_id = groups.id
            WHERE groups.id = ? AND groups.owner_user_id = ? GROUP BY groups.id
            ''', (int(group_id), owner_user_id))
            return _row_to_youtube_video_group(cursor.fetchone())
    except DATABASE_INTEGRITY_ERRORS as exc:
        raise ValueError("分组名称已存在") from exc


def delete_youtube_video_group(group_id, owner_user_id):
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        group = _resolve_youtube_group(cursor, owner_user_id, group_id)
        if bool(group["is_default"]):
            raise ValueError("默认分组不能删除")
        cursor.execute(
            "SELECT COUNT(*) AS count FROM youtube_search_jobs WHERE group_id = ? AND owner_user_id = ? AND status IN ('queued', 'running')",
            (int(group_id), owner_user_id),
        )
        if int(cursor.fetchone()["count"] or 0):
            raise RuntimeError("该分组存在运行中的检索任务，请等待任务结束后再删除")
        default_group = _default_youtube_group(cursor, owner_user_id)
        cursor.execute("UPDATE youtube_videos SET group_id = ?, updated_at = CURRENT_TIMESTAMP WHERE group_id = ? AND owner_user_id = ?", (default_group["id"], int(group_id), owner_user_id))
        moved_count = cursor.rowcount
        cursor.execute("UPDATE youtube_search_jobs SET group_id = NULL WHERE group_id = ? AND owner_user_id = ?", (int(group_id), owner_user_id))
        cursor.execute("DELETE FROM youtube_video_groups WHERE id = ? AND owner_user_id = ?", (int(group_id), owner_user_id))
        backend_logger.info(
            "video group deleted : groupId = %s | movedCount = %s",
            group_id,
            moved_count,
        )
        return {"groupId": int(group_id), "movedCount": moved_count, "defaultGroupId": int(default_group["id"])}


def move_youtube_videos_to_group(video_ids, group_id, owner_user_id):
    if not isinstance(video_ids, list):
        raise ValueError("videoIds 必须是数组")
    if len(video_ids) > 500:
        raise ValueError("每次最多移动 500 条视频线索")
    normalized_ids = list(dict.fromkeys(str(item or "").strip() for item in (video_ids or []) if str(item or "").strip()))
    if not normalized_ids:
        raise ValueError("请选择要移动的视频线索")
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        group = _resolve_youtube_group(cursor, owner_user_id, group_id)
        placeholders = _sql_placeholders(normalized_ids)
        cursor.execute(f"SELECT video_id, group_id FROM youtube_videos WHERE owner_user_id = ? AND video_id IN ({placeholders})", [owner_user_id, *normalized_ids])
        rows = cursor.fetchall()
        found_ids = {row["video_id"] for row in rows}
        missing_ids = [video_id for video_id in normalized_ids if video_id not in found_ids]
        if missing_ids:
            raise LookupError(f"视频线索不存在: {', '.join(missing_ids[:5])}")
        unchanged_count = sum(1 for row in rows if int(row["group_id"] or 0) == int(group["id"]))
        cursor.execute(
            f"UPDATE youtube_videos SET group_id = ?, updated_at = CURRENT_TIMESTAMP WHERE owner_user_id = ? AND video_id IN ({placeholders}) AND COALESCE(group_id, 0) != ?",
            [int(group["id"]), owner_user_id, *normalized_ids, int(group["id"])],
        )
        moved_count = cursor.rowcount
        backend_logger.info(
            "video group move completed : groupId = %s | movedCount = %s | unchangedCount = %s",
            group["id"],
            moved_count,
            unchanged_count,
        )
        return {
            "group": _row_to_youtube_video_group({**dict(group), "video_count": 0}),
            "movedCount": moved_count,
            "unchangedCount": unchanged_count,
        }


def youtube_video_research_context(video_id, owner_user_id):
    if not video_id:
        return {}
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT videos.title, videos.query, groups.id AS group_id, groups.name AS group_name
        FROM youtube_videos videos
        LEFT JOIN youtube_video_groups groups ON groups.id = videos.group_id
        WHERE videos.video_id = ? AND videos.owner_user_id = ?
        ''', (video_id, owner_user_id))
        row = cursor.fetchone()
    if not row:
        return {}
    return {
        "title": row["title"] or "",
        "query": row["query"] or "",
        "groupId": row["group_id"],
        "groupName": row["group_name"] or "",
    }
