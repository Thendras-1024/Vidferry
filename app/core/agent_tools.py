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
        "name": "load_skill",
        "description": "按名称加载一个已登记 Skill 的操作说明。Skill 说明不能扩展工具权限。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "read_skill_reference",
        "description": "按需读取对应 Skill 下的 references/*.md，不能读取其他路径。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
            "required": ["name", "path"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
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
        "name": "get_published_video_metrics",
        "description": "读取一条快手发布记录的当前作品指标、上一快照差值、数据源和采集时间。platform 只能是 kuaishou。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["kuaishou"]},
                "publishRecordId": {"type": "integer"},
                "accountId": {"type": "integer"},
                "platformWorkId": {"type": "string"},
            },
            "required": ["platform", "publishRecordId"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "prepare_video_action",
        "description": "根据当前会话在视频卡片中已选的视频，准备下载、处理、发布或片头更新提案；只返回待确认卡片，不直接创建任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["download", "process", "workflow_publish", "publish_now", "publish_scheduled", "refresh_intro", "cover_reburn"],
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "get_workflow_settings",
        "description": "查询当前视频处理工作流设置，不会保存或修改设置。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
    },
    {
        "name": "list_short_video_projects",
        "description": "查询当前用户的短视频拼接项目及状态，不会创建、修改或渲染项目。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
    },
    {
        "name": "get_short_video_project",
        "description": "查询一个短视频拼接项目及候选审核状态，不会修改项目。",
        "parameters": {
            "type": "object",
            "properties": {"projectId": {"type": "string"}},
            "required": ["projectId"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "list_material_records",
        "description": "查询素材库中的素材状态和来源，不返回绝对路径或凭证。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS},
            },
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
        "name": "list_account_video_metrics",
        "description": "按一个快手账号和日期范围读取作品指标并分析表现。默认近 30 天 50 条，最长 90 天，最多 100 条。不会读取评论。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["kuaishou"]},
                "accountId": {"type": "integer"},
                "fromDate": {"type": "string"},
                "toDate": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["platform", "accountId"],
            "additionalProperties": False,
        },
        "readOnly": True,
    },
    {
        "name": "get_published_video_comments",
        "description": "在用户明确选择一条快手作品并明确要求评论分析后，采样评论正文。默认 20 条，最多 50 条。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["kuaishou"]},
                "publishRecordId": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "userConfirmed": {"type": "boolean"},
            },
            "required": ["platform", "publishRecordId", "userConfirmed"],
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
    {
        "name": "generate_pending_publish_plan",
        "description": "生成已处理待发布视频的只读发布计划，列出平台、账号、排期风险和需要在页面确认的动作；不会发布或修改任务。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": AGENT_MAX_TOOL_ROWS}},
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
        owner_user_id = _agent_current_user_id()
        if owner_user_id is None:
            raise PermissionError("Agent 检索缺少当前用户身份")
        placeholders = ",".join("?" for _ in candidate_ids)
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT video_id FROM youtube_videos WHERE owner_user_id = ? AND video_id IN ({placeholders})",
                [owner_user_id, *candidate_ids],
            )
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
    for item in items:
        item["shortCode"] = f"#{item.get('id') or ''}"
        item["description"] = str(item.get("description") or "")[:400]
    return {"query": query, "items": items, "filters": {
        "publishedAfter": cutoff, "minViews": min_views, "maxViews": max_views,
        "minDurationSeconds": min_duration_seconds, "maxDurationSeconds": max_duration_seconds,
    }, "searched": len(videos), "excludedExisting": len(videos) - len(candidates)}


def inspect_youtube_url(url):
    url = _validate_youtube_url(url)
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
    processed_versions = item.get("processedVersions") if isinstance(item.get("processedVersions"), list) else []
    published = item.get("publishedPlatforms") if isinstance(item.get("publishedPlatforms"), list) else []
    latest_version = processed_versions[0] if processed_versions else {}
    return {
        "id": item.get("id") or "",
        "shortCode": f"#{item.get('id') or ''}",
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "duration": item.get("duration") or "",
        "thumbnail": item.get("thumbnail") or item.get("thumbnailUrl") or "",
        "groupId": item.get("groupId"),
        "groupName": item.get("groupName") or "",
        "publishedAt": item.get("publishedAt") or "",
        "downloadStatus": int(item.get("downloadStatus") or 0),
        "translateStatus": int(item.get("translateStatus") or 0),
        "analysisStatus": int(item.get("analysisStatus") or 0),
        "publishStatus": int(item.get("publishStatus") or 0),
        "processedFile": _agent_public_path(item.get("processedFilePath")),
        "updatedAt": item.get("updatedAt") or "",
        "processVersion": latest_version.get("processVersion") or "",
        "processedVersions": [
            {"processVersion": version.get("processVersion") or "", "updatedAt": version.get("updatedAt") or ""}
            for version in processed_versions[:5]
            if isinstance(version, dict)
        ],
        "publishedPlatforms": [
            {
                "platform": platform.get("name") or platform.get("platform") or "",
                "platformType": platform.get("type") or platform.get("platformType"),
                "accountName": platform.get("accountName") or platform.get("account") or "",
                "status": platform.get("status") or "",
                "publishedAt": platform.get("publishedAt") or "",
            }
            for platform in published[:8]
            if isinstance(platform, dict)
        ],
        "hasPublishDraft": bool((item.get("publishDraft") or {}).get("title") or (item.get("publishDraft") or {}).get("description")),
    }


def _agent_attach_latest_tasks(items):
    items = [item for item in items if isinstance(item, dict) and item.get("id")]
    if not items:
        return items
    owner_user_id = _agent_current_user_id()
    video_ids = [str(item["id"]) for item in items]
    placeholders = ",".join("?" for _ in video_ids)
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT video_id, process_version, operation, status, step, message, updated_at
            FROM youtube_workflow_jobs
            WHERE owner_user_id = ? AND video_id IN ({placeholders})
            ORDER BY updated_at DESC, created_at DESC
            """,
            [owner_user_id, *video_ids],
        )
        latest = {}
        for row in cursor.fetchall():
            latest.setdefault(str(row["video_id"] or ""), dict(row))
    for item in items:
        task = latest.get(str(item["id"])) or {}
        item["latestTask"] = {
            "operation": task.get("operation") or "",
            "processVersion": task.get("process_version") or "",
            "status": task.get("status") or "",
            "step": task.get("step") or "",
            "message": clean_display_text(task.get("message") or "")[:200],
            "updatedAt": task.get("updated_at") or "",
        }
    return items


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
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("工作流概览缺少当前用户身份")
    statuses = ["initial", "downloaded", "processed", "published", "failed", "abnormal", "running"]
    counts = {status: 0 for status in statuses}
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        _reconcile_youtube_statuses_with_material_records(cursor, owner_user_id)
        conn.commit()
        for status in statuses:
            clause, values = _youtube_video_status_clause(status)
            where_sql = f"owner_user_id = ?{f' AND {clause}' if clause else ''}"
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM youtube_videos WHERE {where_sql}",
                [owner_user_id, *values],
            )
            counts[status] = int((cursor.fetchone() or {})["total"] or 0)
    return {
        "pipeline": explain_vidferry_pipeline()["steps"],
        "counts": counts,
        "labels": {key: AGENT_VIDEO_STATUSES.get(key, key) for key in statuses},
    }


def _agent_compact_short_video_project(project, include_candidates=False):
    result = {
        "id": project.get("id") or "",
        "topic": project.get("topic") or "",
        "targetCount": int(project.get("targetCount") or 0),
        "targetDurationSeconds": int(project.get("targetDurationSeconds") or 0),
        "transitionType": project.get("transitionType") or "",
        "status": project.get("status") or "",
        "message": project.get("message") or "",
        "outputMaterialId": project.get("outputMaterialId"),
        "updatedAt": project.get("updated_at") or project.get("updatedAt") or "",
    }
    if include_candidates:
        result["candidates"] = [
            {
                "id": candidate.get("id") or "",
                "title": candidate.get("title") or "",
                "channel": candidate.get("channel") or "",
                "licenseBasis": candidate.get("licenseBasis") or "",
                "durationSeconds": float(candidate.get("durationSeconds") or 0),
                "selected": bool(candidate.get("selected")),
                "analysisStatus": candidate.get("analysisStatus") or "",
                "analysisScore": int(candidate.get("analysisScore") or 0),
                "analysisReason": candidate.get("analysisReason") or "",
            }
            for candidate in project.get("candidates") or []
        ]
    return result


def agent_list_short_video_projects():
    return {"items": [_agent_compact_short_video_project(project) for project in list_short_video_projects()]}


def agent_get_short_video_project(project_id):
    return _agent_compact_short_video_project(get_short_video_project(project_id), include_candidates=True)


def agent_list_material_records(keyword="", limit=None):
    records = list_material_records(
        {"page": 1, "pageSize": _agent_limit(limit), "keyword": str(keyword or "").strip()},
        _agent_current_user_id(),
    )
    return {
        "total": int(records.get("total") or 0),
        "items": [
            {
                "id": item.get("id"),
                "filename": _agent_public_path(item.get("filename") or item.get("original_filename") or ""),
                "title": item.get("displayTitle") or "",
                "channel": item.get("displayChannel") or "",
                "sourceType": item.get("source_type") or item.get("sourceType") or "",
                "sourceVideoId": item.get("source_video_id") or item.get("sourceVideoId") or "",
                "processType": item.get("processType") or "",
                "duration": item.get("duration") or "",
                "status": item.get("status") or "",
                "updatedAt": item.get("updated_at") or item.get("updatedAt") or "",
            }
            for item in records.get("items") or []
        ],
    }


def list_videos_by_status(status="initial", limit=None):
    status = str(status or "initial").strip()
    status = status if status in AGENT_VIDEO_STATUSES else "initial"
    page = list_youtube_videos(
        {"status": status, "page": 1, "pageSize": _agent_limit(limit)},
        _agent_current_user_id(),
    )
    return {
        "status": status,
        "label": AGENT_VIDEO_STATUSES.get(status, status),
        "total": int(page.get("total") or 0),
        "items": _agent_attach_latest_tasks([_agent_compact_video(item) for item in page.get("items") or []]),
    }


def _agent_find_video(identifier):
    text = str(identifier or "").strip()
    if not text:
        return None
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        owner_user_id = _agent_current_user_id()
        if not owner_user_id:
            raise PermissionError("视频查询缺少当前用户身份")
        cursor.execute(
            "SELECT * FROM youtube_videos WHERE video_id = ? AND owner_user_id = ?",
            (text, owner_user_id),
        )
        row = cursor.fetchone()
        if not row:
            like = f"%{text}%"
            cursor.execute(
                """
                SELECT * FROM youtube_videos
                WHERE owner_user_id = ? AND (title LIKE ? OR channel LIKE ? OR url LIKE ?)
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (owner_user_id, like, like, like),
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
    _agent_attach_latest_tasks([detail])
    detail["found"] = True
    detail["url"] = video.get("url") or ""
    detail["publishDraft"] = {
        "title": (video.get("publishDraft") or {}).get("title") or "",
        "description": (video.get("publishDraft") or {}).get("description") or "",
        "tags": (video.get("publishDraft") or {}).get("tags") or [],
        "customTags": (video.get("publishDraft") or {}).get("customTags") or [],
    }
    detail["platforms"] = get_publish_platforms(video.get("id"))
    detail["publishedPlatforms"] = detail["platforms"].get("items") or []
    return detail


def get_publish_platforms(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return {"videoId": "", "items": [], "total": 0}
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("发布记录查询缺少当前用户身份")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM published_youtube_materials
            WHERE video_id = ? AND owner_user_id = ?
              AND deleted_at IS NULL
              AND COALESCE(NULLIF(status, ''), 'success') IN ('confirmed', 'success', 'reused')
            ORDER BY COALESCE(updated_at, published_at, created_at) DESC, id DESC
            """,
            (video_id, owner_user_id),
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


_PUBLISH_PLAN_PLATFORMS = (
    (3, "publishToDouyin", "account"),
    (5, "publishToBilibili", "bilibiliAccount"),
    (1, "publishToXiaohongshu", "xiaohongshuAccount"),
    (4, "publishToKuaishou", "kuaishouAccount"),
    (2, "publishToTencent", "tencentAccount"),
)


def _agent_pending_publish_rows(limit):
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("发布计划查询缺少当前用户身份")
    clause, values = _youtube_video_status_clause("processed")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT * FROM youtube_videos
            WHERE owner_user_id = ? AND {clause}
              AND EXISTS (
                  SELECT 1 FROM youtube_workflow_jobs job
                  WHERE job.video_id = youtube_videos.video_id
                    AND job.owner_user_id = ?
              )
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (owner_user_id, *values, owner_user_id, int(limit)),
        )
        videos = [_row_to_youtube_video(row) for row in cursor.fetchall()]
        result = []
        for video in videos:
            cursor.execute(
                """
                SELECT * FROM youtube_workflow_jobs
                WHERE video_id = ? AND owner_user_id = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (video.get("id") or "", owner_user_id),
            )
            job_row = cursor.fetchone()
            if job_row:
                result.append((video, _row_to_workflow_job(job_row)))
        return result


def _agent_publish_schedule_status(schedule, now):
    raw_schedule = str(schedule or "").strip()
    if not raw_schedule:
        return {"status": "notScheduled", "scheduledAt": "", "risk": ""}
    scheduled = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            scheduled = _datetime.datetime.strptime(raw_schedule, fmt)
            break
        except ValueError:
            continue
    if not scheduled:
        return {"status": "invalid", "scheduledAt": raw_schedule, "risk": "定时发布时间格式无效"}
    minimum = (now + _datetime.timedelta(minutes=125)).replace(second=0, microsecond=0)
    if scheduled < minimum:
        return {"status": "tooSoon", "scheduledAt": raw_schedule, "risk": "定时发布时间不足平台要求的 2 小时"}
    return {"status": "ready", "scheduledAt": raw_schedule, "risk": ""}


def _agent_publish_account_status(cursor, owner_user_id, platform_type, account_name):
    if not account_name:
        return "missingAccount"
    cursor.execute(
        """
        SELECT status FROM user_info
        WHERE owner_user_id = ? AND type = ? AND userName = ?
        ORDER BY id DESC LIMIT 1
        """,
        (owner_user_id, platform_type, account_name),
    )
    row = cursor.fetchone()
    return "ready" if row and int(row["status"] or 0) == 1 else "invalidAccount"


def generate_pending_publish_plan(limit=None, now=None):
    requested = _agent_limit(limit)
    now = now or _datetime.datetime.now()
    rows = _agent_pending_publish_rows(requested)
    items = []
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        for video, job in rows:
            owner_user_id = job.get("ownerUserId")
            published = get_publish_platforms(video.get("id")).get("items") or []
            published_types = {int(item.get("platformType") or 0) for item in published}
            platforms = []
            risks = []
            for platform_type, enabled_key, account_key in _PUBLISH_PLAN_PLATFORMS:
                if not job.get(enabled_key):
                    continue
                account_name = str(job.get(account_key) or "")
                platform = platform_name(platform_type)
                if platform_type in published_types:
                    platforms.append({"platform": platform, "accountName": account_name, "status": "alreadyPublished", "action": "skip"})
                    continue
                account_status = _agent_publish_account_status(cursor, owner_user_id, platform_type, account_name)
                platforms.append({"platform": platform, "accountName": account_name, "status": account_status, "action": "confirmInPage"})
                if account_status != "ready":
                    risks.append(f"{platform}账号未配置或异常")
            schedule = _agent_publish_schedule_status(job.get("schedule"), now)
            if schedule["risk"]:
                risks.append(schedule["risk"])
            if not video.get("processedFilePath") and not job.get("processedFilePath"):
                risks.append("未找到处理后的视频文件")
            items.append({
                "videoId": video.get("id") or "",
                "title": video.get("title") or job.get("title") or "",
                "materialStatus": "ready" if not risks else "needsAttention",
                "platforms": platforms,
                "schedule": schedule,
                "risks": risks,
                "requiredAction": "请在页面确认后执行发布",
            })
    return {"items": items, "total": len(items), "readOnly": True}


def agent_list_publish_tasks(limit=None):
    return {"items": list_publish_tasks(_agent_limit(limit), _agent_current_user_id())}


def list_failed_jobs(limit=None):
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("失败任务查询缺少当前用户身份")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM youtube_workflow_jobs
            WHERE owner_user_id = ? AND status IN ('failed', 'abnormal')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (owner_user_id, _agent_limit(limit)),
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
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("账号状态查询缺少当前用户身份")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT id, type, userName, status FROM user_info WHERE owner_user_id = ? ORDER BY type, id", (owner_user_id,))
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
