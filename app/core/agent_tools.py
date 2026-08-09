"""Agent 只读查询工具:工作流概览、视频/账号/发布记录查询与流程说明。"""


from __future__ import annotations

import os as _os
import re as _re
import datetime as _datetime
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor


AGENT_VIDEO_STATUSES = {
    "initial": "待处理",
    "pending": "待处理",
    "notDownloaded": "未下载",
    "downloaded": "已下载未处理",
    "processed": "已处理未发布",
    "published": "已发布",
    "failed": "失败",
    "abnormal": "异常",
    "running": "运行中",
}

AGENT_TOOL_SPECS = [
    {
        "name": "explain_vidferry_pipeline",
        "description": "说明 Vidferry 从线索导入、下载、处理、质检到发布的本地工作流。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
    },
    {
        "name": "get_workflow_overview",
        "description": "查询当前视频工作流各状态数量概览。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
    },
    {
        "name": "list_videos_by_status",
        "description": "按状态查询视频列表。status 可为 initial/downloaded/processed/published/failed/abnormal/running。",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS},
            },
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "get_video_detail",
        "description": "按视频 ID、YouTube URL、标题或关键词查询单个视频详情和发布记录。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "get_publish_platforms",
        "description": "按内部视频 ID 查询已成功发布的平台记录。",
        "parameters": {
            "type": "object",
            "properties": {"videoId": {"type": "string"}},
            "required": ["videoId"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "list_publish_tasks",
        "description": "查询最近的发布任务记录。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS}},
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "list_failed_jobs",
        "description": "查询最近失败或异常的视频工作流任务。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS}},
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "get_account_status",
        "description": "查询已配置平台账号的状态概览。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
    },
    {
        "name": "get_agent_run_overview",
        "description": "查询 Agent 最近运行的成功率、平均耗时、安全拦截、工具错误和脱敏后的调用轨迹。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "search_youtube_candidates",
        "description": "按关键词检索 YouTube 候选视频。该工具只返回候选线索，不会导入、下载或修改任何数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS},
                "publishedAfter": {"type": "string"},
                "minViews": {"type": "integer", "minimum": 0},
                "maxViews": {"type": "integer", "minimum": 0},
                "minDurationSeconds": {"type": "integer", "minimum": 0},
                "maxDurationSeconds": {"type": "integer", "minimum": 0},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "inspect_youtube_url",
        "description": "读取一个 YouTube 视频链接的元数据，用于生成待确认的导入线索；不会导入或下载视频。",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
]

AGENT_TOOL_SPEC_MAP = {item["name"]: item for item in AGENT_TOOL_SPECS}


def _agent_limit(limit=None):
    return max(1, min(int(limit or AGENT_MAX_TOOL_ROWS), AGENT_MAX_TOOL_ROWS))


def search_youtube_candidates(query, limit=None, published_after="", min_views=None, max_views=None, min_duration_seconds=None, max_duration_seconds=None):
    query = str(query or "").strip()
    if not query:
        raise ValueError("请提供要检索的 YouTube 主题")
    requested = _agent_limit(limit)
    videos = _search_youtube_with_ytdlp(query, min(50, max(requested * 8, 20)))
    candidate_ids = [str(item.get("id") or "").strip() for item in videos if str(item.get("id") or "").strip()]
    existing_ids = set()
    if candidate_ids:
        init_youtube_video_table()
        placeholders = ",".join("?" for _ in candidate_ids)
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT video_id FROM youtube_videos WHERE video_id IN ({placeholders})", candidate_ids)
            existing_ids = {str(row["video_id"] or "") for row in cursor.fetchall()}
    # yt-dlp 的搜索摘要通常没有订阅数和精确发布日期。先剔除已有线索，
    # 再对有限候选取详情，避免为不会展示的视频建立大量额外请求。
    candidates = [item for item in videos if str(item.get("id") or "") not in existing_ids]
    detail_limit = min(len(candidates), max(6, min(requested * 2, 12)))
    detail_candidates = candidates[:detail_limit]
    if len(detail_candidates) > 1:
        with _ThreadPoolExecutor(max_workers=min(3, len(detail_candidates)), thread_name_prefix="vidferry-agent-metadata") as executor:
            enriched_candidates = list(executor.map(lambda item: _enrich_video_metadata(item, "agent-search", quick_metadata=True), detail_candidates))
    else:
        enriched_candidates = [_enrich_video_metadata(item, "agent-search", quick_metadata=True) for item in detail_candidates]
    cutoff = str(published_after or "").strip()
    def matches(item):
        views = int(item.get("viewCount") or 0)
        duration = float(item.get("durationSeconds") or 0)
        published = str(item.get("publishedAt") or "")
        if cutoff and (not published or published < cutoff): return False
        if min_views is not None and views < int(min_views): return False
        if max_views is not None and views > int(max_views): return False
        if min_duration_seconds is not None and duration < int(min_duration_seconds): return False
        if max_duration_seconds is not None and duration > int(max_duration_seconds): return False
        return True
    filtered = [item for item in enriched_candidates if matches(item)]
    items = filtered[:requested]
    return {"query": query, "items": items, "filters": {
        "publishedAfter": cutoff, "minViews": min_views, "maxViews": max_views,
        "minDurationSeconds": min_duration_seconds, "maxDurationSeconds": max_duration_seconds,
    }, "searched": len(videos), "excludedExisting": len(videos) - len(candidates)}


def inspect_youtube_url(url):
    url = str(url or "").strip()
    if not url:
        raise ValueError("请提供 YouTube 视频链接")
    return {"item": _import_youtube_video_by_url(url)}


def _agent_public_path(value):
    text = str(value or "")
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if ":" in text or "\\" in text or "/" in text:
        return _os.path.basename(text.replace("\\", "/"))
    return text


def _agent_compact_video(item):
    return {
        "id": item.get("id") or "",
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "duration": item.get("duration") or "",
        "groupId": item.get("groupId"),
        "groupName": item.get("groupName") or "",
        "publishedAt": item.get("publishedAt") or "",
        "downloadStatus": int(item.get("downloadStatus") or 0),
        "translateStatus": int(item.get("translateStatus") or 0),
        "analysisStatus": int(item.get("analysisStatus") or 0),
        "publishStatus": int(item.get("publishStatus") or 0),
        "processedFile": _agent_public_path(item.get("processedFilePath")),
        "updatedAt": item.get("updatedAt") or "",
    }


def explain_vidferry_pipeline():
    return {
        "name": "Vidferry 本地视频工作流",
        "steps": [
            {"key": "research", "label": "线索导入", "description": "按关键词或链接导入 YouTube 候选视频。"},
            {"key": "download", "label": "视频下载", "description": "使用 yt-dlp 下载原视频并登记素材。"},
            {"key": "process", "label": "字幕/剪辑处理", "description": "转写、翻译、烧录字幕，并按处理版本生成成片。"},
            {"key": "analysis", "label": "发布稿生成", "description": "LLM 生成标题、正文、话题、高光和风险提示。"},
            {"key": "guard", "label": "发布前质检", "description": "Agent 审核文本和关键帧，严重风险会阻断发布。"},
            {"key": "publish", "label": "多平台发布", "description": "按账号和平台提交发布，并记录每个平台结果。"},
        ],
    }


def get_workflow_overview():
    statuses = ["initial", "downloaded", "processed", "published", "failed", "abnormal", "running"]
    counts = {status: 0 for status in statuses}
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        _reconcile_youtube_statuses_with_material_records(cursor)
        conn.commit()
        for status in statuses:
            clause, values = _youtube_video_status_clause(status)
            where_sql = f" WHERE {clause}" if clause else ""
            cursor.execute(f"SELECT COUNT(*) AS total FROM youtube_videos{where_sql}", values)
            counts[status] = int((cursor.fetchone() or {})["total"] or 0)
    return {
        "pipeline": explain_vidferry_pipeline()["steps"],
        "counts": counts,
        "labels": {key: AGENT_VIDEO_STATUSES.get(key, key) for key in statuses},
    }


def list_videos_by_status(status="initial", limit=None):
    status = str(status or "initial").strip()
    status = status if status in AGENT_VIDEO_STATUSES else "initial"
    page = list_youtube_videos({"status": status, "page": 1, "pageSize": _agent_limit(limit)})
    return {
        "status": status,
        "label": AGENT_VIDEO_STATUSES.get(status, status),
        "total": int(page.get("total") or 0),
        "items": [_agent_compact_video(item) for item in page.get("items") or []],
    }


def _agent_find_video(identifier):
    text = str(identifier or "").strip()
    if not text:
        return None
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (text,))
        row = cursor.fetchone()
        if not row:
            like = f"%{text}%"
            cursor.execute(
                """
                SELECT * FROM youtube_videos
                WHERE title LIKE ? OR channel LIKE ? OR url LIKE ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (like, like, like),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return _row_to_youtube_video(row)


def _agent_guess_identifier(message):
    text = str(message or "").strip()
    url_match = _re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", text)
    if url_match:
        return url_match.group(1)
    id_match = _re.search(r"\b[A-Za-z0-9_-]{8,}\b", text)
    if id_match:
        return id_match.group(0)
    quoted = _re.findall(r"[「《\"']([^」》\"']{2,80})[」》\"']", text)
    if quoted:
        return quoted[0]
    return text


def get_video_detail(video_id_or_keyword):
    video = _agent_find_video(_agent_guess_identifier(video_id_or_keyword))
    if not video:
        return {"found": False, "message": "未找到匹配视频"}
    detail = _agent_compact_video(video)
    detail["found"] = True
    detail["url"] = video.get("url") or ""
    detail["publishDraft"] = {
        "title": (video.get("publishDraft") or {}).get("title") or "",
        "description": (video.get("publishDraft") or {}).get("description") or "",
        "tags": (video.get("publishDraft") or {}).get("tags") or [],
    }
    detail["platforms"] = get_publish_platforms(video.get("id"))
    return detail


def get_publish_platforms(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return {"videoId": "", "items": [], "total": 0}
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM published_youtube_materials
            WHERE video_id = ?
              AND deleted_at IS NULL
              AND COALESCE(NULLIF(status, ''), 'success') = 'success'
            ORDER BY COALESCE(updated_at, published_at, created_at) DESC, id DESC
            """,
            (video_id,),
        )
        items = [_row_to_published_material(row) for row in cursor.fetchall()]
    return {
        "videoId": video_id,
        "total": len(items),
        "items": [
            {
                "platform": item.get("platform") or platform_name(item.get("platformType")),
                "platformType": item.get("platformType"),
                "accountName": item.get("accountName") or "",
                "status": item.get("status") or "success",
                "publishedAt": item.get("publishedAt") or item.get("updatedAt") or "",
            }
            for item in items
        ],
    }


def agent_list_publish_tasks(limit=None):
    return {"items": list_publish_tasks(_agent_limit(limit))}


def list_failed_jobs(limit=None):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM youtube_workflow_jobs
            WHERE status IN ('failed', 'abnormal')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (_agent_limit(limit),),
        )
        return {
            "items": [
                {
                    "id": row["id"],
                    "videoId": row["video_id"] or "",
                    "title": row["title"] or "",
                    "status": row["status"] or "",
                    "step": row["step"] or "",
                    "message": row["message"] or row["error_reason"] or "",
                    "errorCode": row["error_code"] or "",
                    "updatedAt": row["updated_at"] or row["created_at"] or "",
                }
                for row in cursor.fetchall()
            ]
        }


def get_account_status():
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT id, type, userName, status FROM user_info ORDER BY type, id")
        rows = cursor.fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "platform": platform_name(row["type"]),
                "platformType": int(row["type"] or 0),
                "name": row["userName"] or "",
                "status": "valid" if int(row["status"] or 0) == 1 else "abnormal",
            }
            for row in rows
        ]
    }


def get_agent_observability(limit=None):
    return get_agent_run_overview(_agent_limit(limit))
