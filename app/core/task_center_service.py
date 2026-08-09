"""聚合工作流任务，供任务中心列表和流程详情使用。"""

import datetime
import json


_TASK_SUCCESS_RETENTION_HOURS = 12
_TASK_ACTIVE_STATUSES = {"queued", "running", "waiting_confirmation"}
_TASK_TERMINAL_STATUSES = {"success", "failed", "abnormal"}
_TASK_RECOVERABLE_STAGES = {"comment_fetch", "comment_review", "comment_render", "subtitle", "highlight_render"}
_TASK_STAGE_LABELS = {
    "workflow": "工作流",
    "download": "下载",
    "transcript": "转写",
    "analysis": "内容分析",
    "content_safety_detect": "内容安全检测",
    "content_safety_confirm": "风险确认",
    "content_trim": "风险裁剪",
    "subtitle": "字幕处理",
    "subtitle_burn": "字幕烧制",
    "body_burn": "正片烧制",
    "comment_fetch": "评论获取",
    "comment_review": "评论筛选",
    "comment_render": "评论烧制",
    "cover_render": "封面片头",
    "highlight_render": "高光生成",
    "editing_concat": "正片拼接",
    "editing": "视频编辑",
    "publish": "发布",
}
_TASK_PLATFORMS = (
    (3, "抖音", "publish_to_douyin", "account"),
    (5, "哔哩哔哩", "publish_to_bilibili", "bilibili_account"),
    (1, "小红书", "publish_to_xiaohongshu", "xiaohongshu_account"),
    (4, "快手", "publish_to_kuaishou", "kuaishou_account"),
    (2, "腾讯视频", "publish_to_tencent", "tencent_account"),
)


def _task_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _task_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _task_iso(value):
    parsed = _task_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def _task_json(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _task_type_label(scope, job, events):
    if scope == "download":
        return "下载"
    if scope == "publish":
        return "发布"
    operation = str(job.get("operation") or "").lower()
    stages = {event.get("stage") for event in events}
    if operation in {"intro_refresh", "editing_intro"}:
        return "片头更新"
    if stages and stages <= {"workflow", "analysis"}:
        return "内容分析"
    return "剪辑处理"


def _task_bool(value):
    return str(value or "").lower() in {"1", "true", "yes", "on"} or value is True


def _task_option(job, name, default=False):
    snake_names = {
        "translationEnabled": "translation_enabled",
        "commentBurnEnabled": "comment_burn_enabled",
        "coverIntroEnabled": "cover_intro_enabled",
        "highlightIntroEnabled": "highlight_intro_enabled",
    }
    value = job.get(name) if name in job else job.get(snake_names.get(name, name), default)
    return default if value is None else _task_bool(value)


def _task_status(status):
    status = str(status or "pending").lower()
    return status if status in {"queued", "running", "waiting_confirmation", "success", "reused", "failed", "abnormal", "warning"} else "pending"


def _task_status_label(status):
    return {
        "queued": "排队中", "running": "进行中", "waiting_confirmation": "等待确认",
        "success": "已完成", "failed": "失败", "abnormal": "异常", "warning": "已降级继续",
        "reused": "已复用", "pending": "未开始", "waiting": "等待分支",
    }.get(status, status)


def _task_row(row):
    return dict(row) if row else {}


def _task_event(row):
    item = _task_row(row)
    return {
        "id": item.get("id"),
        "stage": str(item.get("stage") or "workflow"),
        "label": item.get("stage_label") or _TASK_STAGE_LABELS.get(item.get("stage"), item.get("stage") or "阶段"),
        "status": _task_status(item.get("status")),
        "message": str(item.get("message") or ""),
        "startedAt": _task_iso(item.get("started_at")),
        "endedAt": _task_iso(item.get("ended_at")),
        "durationSeconds": float(item.get("duration_seconds") or 0),
        "metadata": _task_json(item.get("metadata")),
    }


def _task_has_fallback(event, subtitle_fallback=False):
    metadata = event.get("metadata") or {}
    text = f"{event.get('message') or ''} {json.dumps(metadata, ensure_ascii=False)}".lower()
    if subtitle_fallback and event.get("stage") in {"subtitle", "subtitle_burn"}:
        return True, "字幕审查存在局部 fallback，已保留可用片段"
    if any(token in text for token in ("fallback", "degraded", "timedout", "降级", "回退", "部分成功")):
        reason = event.get("message") or metadata.get("fallbackReason") or metadata.get("reason") or "阶段发生降级，已继续后续流程"
        return True, str(reason)
    return False, ""


def _task_is_reused(event):
    metadata = event.get("metadata") or {}
    text = str(event.get("message") or "")
    return bool(metadata.get("cached") or metadata.get("reused") or "复用" in text or "已复用" in text)


def _task_only_download(job, events):
    stages = {event["stage"] for event in events}
    operation = str(job.get("operation") or "process").lower()
    non_download = stages - {"download", "workflow"}
    if operation in {"download", "download_only", "download-only"}:
        return True
    if non_download:
        return False
    return not any((
        _task_option(job, "translationEnabled", True),
        _task_option(job, "commentBurnEnabled"),
        _task_option(job, "coverIntroEnabled", True),
        _task_option(job, "highlightIntroEnabled", True),
        any(str(job.get(field) or "").strip() for _, _, _, field in _TASK_PLATFORMS),
    ))


def _task_targets(job, material_rows):
    targets = []
    for platform_type, label, flag, account_field in _TASK_PLATFORMS:
        records = [row for row in material_rows if int(row.get("platform_type") or 0) == platform_type]
        configured = _task_bool(job.get(flag)) and bool(str(job.get(account_field) or "").strip())
        if configured or records:
            targets.append({"type": platform_type, "label": label, "account": str(job.get(account_field) or ""), "records": records})
    return targets


def _task_node_state(event, job_status, subtitle_fallback=False):
    if not event:
        return "pending", "", ""
    status = event["status"]
    warning, reason = _task_has_fallback(event, subtitle_fallback)
    if status == "failed" and job_status not in {"failed", "abnormal"} and event["stage"] in _TASK_RECOVERABLE_STAGES:
        return "warning", event["message"], event["message"] or "该阶段失败后已跳过，主流程继续"
    if warning and status in {"success", "warning"}:
        return "warning", event["message"], reason
    if status == "success" and _task_is_reused(event):
        return "reused", event["message"], "已复用已有阶段结果"
    return status, event["message"], ""


def _task_publish_graph(job, events, material_rows):
    event_by_stage = {event["stage"]: event for event in events}
    lanes = [{"id": "publish", "label": "发布"}]
    nodes = []
    edges = []

    publish_event = event_by_stage.get("publish")
    status, message, fallback_reason = _task_node_state(publish_event, job.get("status"))
    parent = {
        "id": "publish", "stage": "publish", "label": "发布", "laneId": "publish", "column": 0,
        "status": status, "statusLabel": _task_status_label(status), "message": message,
        "startedAt": publish_event.get("startedAt", "") if publish_event else "", "endedAt": publish_event.get("endedAt", "") if publish_event else "",
        "durationSeconds": publish_event.get("durationSeconds", 0) if publish_event else 0, "dependencies": [],
        "parallelGroup": "publish", "platform": "", "fallbackReason": fallback_reason,
        "errorReason": message if status == "failed" else "", "inferred": not bool(publish_event), "synthetic": False,
    }
    nodes.append(parent)
    for target in _task_targets(job, material_rows):
        lane_id = f"publish-{target['type']}"
        lanes.append({"id": lane_id, "label": target["label"]})
        record = target["records"][-1] if target["records"] else {}
        target_status = _task_status(record.get("status")) if record else ("running" if status == "running" else "pending")
        nodes.append({
            "id": lane_id, "stage": "publish", "label": target["label"], "laneId": lane_id, "column": 1,
            "status": target_status, "statusLabel": _task_status_label(target_status),
            "message": str(record.get("message") or target.get("account") or "等待发布"),
            "startedAt": _task_iso(record.get("started_at")), "endedAt": _task_iso(record.get("published_at") or record.get("updated_at")),
            "durationSeconds": float(record.get("duration_ms") or 0) / 1000, "dependencies": ["publish"],
            "parallelGroup": "publish-platforms", "platform": target["label"], "fallbackReason": "",
            "errorReason": str(record.get("message") or "") if target_status == "failed" else "",
            "inferred": not bool(record), "synthetic": True,
        })
        edges.append({"from": "publish", "to": lane_id, "kind": "parallel", "status": "failed" if target_status == "failed" else "running" if target_status == "running" else "reused" if target_status == "reused" else "success" if status == "success" and target_status == "success" else "pending"})
    return {"lanes": lanes, "nodes": nodes, "edges": edges, "inferred": True}


def _task_graph(job, events, material_rows, subtitle_fallback=False, scope="full"):
    """按固定阶段规则补齐旧事件缺少的依赖元数据。"""
    if scope == "publish":
        return _task_publish_graph(job, events, material_rows)
    event_by_stage = {}
    for event in events:
        current = event_by_stage.get(event["stage"])
        if not current or (event.get("startedAt"), event.get("id")) >= (current.get("startedAt"), current.get("id")):
            event_by_stage[event["stage"]] = event

    nodes = []
    edges = []
    lanes = []

    def lane(lane_id, label):
        lanes.append({"id": lane_id, "label": label})

    def add_node(node_id, stage, label, lane_id, column, dependencies=(), synthetic=False, platform=""):
        event = event_by_stage.get(stage)
        if not event and stage == "subtitle_burn":
            event = event_by_stage.get("body_burn")
        status, message, fallback_reason = _task_node_state(event, job.get("status"), subtitle_fallback)
        node = {
            "id": node_id, "stage": stage, "label": label, "laneId": lane_id, "column": column,
            "status": status, "statusLabel": _task_status_label(status), "message": message,
            "startedAt": event.get("startedAt", "") if event else "", "endedAt": event.get("endedAt", "") if event else "",
            "durationSeconds": event.get("durationSeconds", 0) if event else 0, "dependencies": list(dependencies),
            "parallelGroup": lane_id, "platform": platform, "fallbackReason": fallback_reason,
            "errorReason": message if status == "failed" else "", "inferred": not bool(event), "synthetic": synthetic,
        }
        nodes.append(node)
        return node

    def connect(source, target, kind="serial"):
        source_node = next(item for item in nodes if item["id"] == source)
        target_node = next(item for item in nodes if item["id"] == target)
        target_status = target_node["status"]
        edge_status = "failed" if target_status == "failed" or source_node["status"] == "failed" else "warning" if target_status == "warning" or source_node["status"] == "warning" else "running" if target_status == "running" or source_node["status"] == "running" else "success" if target_status == "success" and source_node["status"] == "success" else "pending"
        edges.append({"from": source, "to": target, "kind": kind, "status": edge_status})

    column_offset = -1 if scope == "processing" else 0
    lane("core", "主流程")
    if scope != "processing":
        add_node("download", "download", "下载", "core", 0)
    transcript_dependencies = ("download",) if scope != "processing" else ()
    add_node("transcript", "transcript", "转写", "core", 1 + column_offset, transcript_dependencies)
    add_node("split", "workflow_split", "并行分叉", "core", 2 + column_offset, ("transcript",), True)
    if scope != "processing":
        connect("download", "transcript")
    connect("transcript", "split", "fork")

    if _task_bool(job.get("contentSafetyReviewEnabled")) or "content_safety_detect" in event_by_stage:
        lane("safety", "内容安全")
        add_node("safety", "content_safety_detect", "内容安全", "safety", 3 + column_offset, ("split",))
        connect("split", "safety", "parallel")

    lane("analysis", "分析与视觉")
    add_node("analysis", "analysis", "内容分析", "analysis", 3 + column_offset, ("split",))
    connect("split", "analysis", "parallel")
    if _task_option(job, "coverIntroEnabled", True) or "cover_render" in event_by_stage:
        add_node("cover", "cover_render", "封面片头", "analysis", 4 + column_offset, ("analysis",))
        connect("analysis", "cover", "fork")
    if _task_option(job, "highlightIntroEnabled", True) or "highlight_render" in event_by_stage:
        add_node("highlight", "highlight_render", "高光生成", "analysis", 4 + column_offset, ("analysis",))
        connect("analysis", "highlight", "fork")

    subtitle_enabled = _task_option(job, "translationEnabled", True) or "subtitle" in event_by_stage
    if subtitle_enabled:
        lane("subtitle", "字幕")
        add_node("subtitle", "subtitle", "字幕处理", "subtitle", 3 + column_offset, ("split",))
        add_node("subtitle_burn", "subtitle_burn", "正片字幕烧制", "subtitle", 4 + column_offset, ("subtitle",))
        connect("split", "subtitle", "parallel")
        connect("subtitle", "subtitle_burn")

    comment_enabled = _task_option(job, "commentBurnEnabled") or any(stage.startswith("comment_") for stage in event_by_stage)
    if comment_enabled:
        lane("comments", "评论")
        add_node("comment_fetch", "comment_fetch", "评论获取", "comments", 3 + column_offset, ("split",))
        add_node("comment_review", "comment_review", "评论筛选", "comments", 4 + column_offset, ("comment_fetch",))
        add_node("comment_render", "comment_render", "评论烧制", "comments", 5 + column_offset, ("comment_review",))
        connect("split", "comment_fetch", "parallel")
        connect("comment_fetch", "comment_review")
        connect("comment_review", "comment_render")

    burn_dependencies = [item["id"] for item in nodes if item["id"] in {"subtitle_burn", "comment_render"}]
    if burn_dependencies:
        add_node("burn_join", "workflow_join", "烧制汇合", "core", 6 + column_offset, burn_dependencies, True)
        for dependency in burn_dependencies:
            connect(dependency, "burn_join", "join")
    else:
        add_node("burn_join", "workflow_join", "烧制汇合", "core", 6 + column_offset, ("split",), True)
        connect("split", "burn_join", "join")

    final_dependencies = ["burn_join"]
    if any(item["id"] == "cover" for item in nodes):
        final_dependencies.append("cover")
    if any(item["id"] == "highlight" for item in nodes):
        final_dependencies.append("highlight")
    if scope == "processing":
        editing_stage = "editing" if "editing" in event_by_stage else "editing_concat" if "editing_concat" in event_by_stage else ""
        if editing_stage:
            editing_label = "视频拼接" if editing_stage == "editing_concat" else "片头高光拼接"
            add_node("editing", editing_stage, editing_label, "core", 7 + column_offset, final_dependencies, False)
            for dependency in final_dependencies:
                connect(dependency, "editing", "join")
    else:
        add_node("final_join", "workflow_join", "成片汇合", "core", 7 + column_offset, final_dependencies, True)
        for dependency in final_dependencies:
            connect(dependency, "final_join", "join")

    targets = _task_targets(job, material_rows)
    if targets and scope != "processing":
        lane("publish", "发布")
        add_node("publish", "publish", "发布", "publish", 8 + column_offset, ("final_join",))
        connect("final_join", "publish")
        for index, target in enumerate(targets):
            lane_id = f"publish-{target['type']}"
            lane(lane_id, target["label"])
            records = target["records"]
            record = records[-1] if records else {}
            status = _task_status(record.get("status")) if record else ("running" if event_by_stage.get("publish") and job.get("status") == "running" else "pending")
            message = str(record.get("message") or target.get("account") or "等待发布")
            node = add_node(f"publish-{target['type']}", "publish", target["label"], lane_id, 9 + column_offset, ("publish",), True, target["label"])
            node.update({"status": status, "statusLabel": _task_status_label(status), "message": message, "inferred": not bool(record)})
            connect("publish", node["id"], "parallel")

    status_by_id = {node["id"]: node["status"] for node in nodes}
    for node in nodes:
        if node["synthetic"] and node["dependencies"]:
            dependencies = [status_by_id.get(item, "pending") for item in node["dependencies"]]
            if any(item == "failed" for item in dependencies):
                node["status"] = "failed"
                node["errorReason"] = "依赖阶段失败，无法继续"
            elif any(item in {"running", "warning"} for item in dependencies):
                node["status"] = "waiting" if any(item == "running" for item in dependencies) else "warning"
                node["message"] = "等待并行分支完成" if node["status"] == "waiting" else "分支已降级后汇合"
            elif all(item in {"success", "reused"} for item in dependencies):
                node["status"] = "success"
            node["statusLabel"] = _task_status_label(node["status"])
            node["dependencySummary"] = {
                "completed": [node["dependencies"][i] for i, item in enumerate(dependencies) if item == "success"],
                "reused": [node["dependencies"][i] for i, item in enumerate(dependencies) if item == "reused"],
                "running": [node["dependencies"][i] for i, item in enumerate(dependencies) if item == "running"],
                "pending": [node["dependencies"][i] for i, item in enumerate(dependencies) if item in {"pending", "waiting"}],
                "blocked": [node["dependencies"][i] for i, item in enumerate(dependencies) if item == "failed"],
            }
    status_by_id = {node["id"]: node["status"] for node in nodes}
    for edge in edges:
        source_status = status_by_id.get(edge["from"], "pending")
        target_status = status_by_id.get(edge["to"], "pending")
        edge["status"] = "failed" if target_status == "failed" or source_status == "failed" else "warning" if target_status == "warning" or source_status == "warning" else "running" if target_status in {"running", "waiting"} or source_status in {"running", "waiting"} else "reused" if target_status == "reused" or source_status == "reused" else "success" if target_status == "success" and source_status == "success" else "pending"
    return {"lanes": lanes, "nodes": nodes, "edges": edges, "inferred": True}


def _task_load(job_id=None, *, active_only=False):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        if job_id:
            cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,))
            job = _task_row(cursor.fetchone())
            jobs = [job] if job else []
        elif active_only:
            statuses = tuple(sorted(_TASK_ACTIVE_STATUSES))
            marks = ",".join("?" for _ in statuses)
            cursor.execute(
                f"SELECT * FROM youtube_workflow_jobs WHERE status IN ({marks}) ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC",
                statuses,
            )
            jobs = [_task_row(row) for row in cursor.fetchall()]
        else:
            cursor.execute("SELECT * FROM youtube_workflow_jobs ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC")
            jobs = [_task_row(row) for row in cursor.fetchall()]
        if not jobs:
            return []
        ids = [job.get("id") for job in jobs]
        marks = ",".join("?" for _ in ids)
        cursor.execute(f"SELECT * FROM youtube_workflow_events WHERE job_id IN ({marks}) ORDER BY started_at, id", ids)
        event_map = {}
        for row in cursor.fetchall():
            event = _task_event(row)
            event_map.setdefault(str(row["job_id"]), []).append(event)
        video_ids = [job.get("video_id") for job in jobs if job.get("video_id")]
        title_translation_map = {}
        if video_ids:
            marks = ",".join("?" for _ in video_ids)
            cursor.execute(f'''
            SELECT video_id, metadata FROM youtube_workflow_events
            WHERE video_id IN ({marks})
              AND stage = 'source_title_translation'
              AND status = 'success'
            ORDER BY ended_at DESC, id DESC
            ''', video_ids)
            for row in cursor.fetchall():
                video_id = str(row["video_id"] or "")
                if video_id in title_translation_map:
                    continue
                metadata = _task_json(row["metadata"])
                title = str(metadata.get("sourceTitleZh") or "").strip()
                if title:
                    title_translation_map[video_id] = title
        material_map = {}
        if video_ids:
            marks = ",".join("?" for _ in video_ids)
            cursor.execute(f"SELECT * FROM published_youtube_materials WHERE video_id IN ({marks}) AND deleted_at IS NULL ORDER BY COALESCE(updated_at, published_at, created_at), id", video_ids)
            for row in cursor.fetchall():
                item = _task_row(row)
                material_map.setdefault(str(item.get("video_id")), []).append(item)
        for job in jobs:
            job["_task_chinese_title"] = title_translation_map.get(str(job.get("video_id") or ""), "")
        return [(job, event_map.get(str(job.get("id")), []), material_map.get(str(job.get("video_id")), [])) for job in jobs]


def _task_acknowledgements(user_id):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT task_key, acknowledged_at FROM task_acknowledgements WHERE user_id = ?", (int(user_id),))
        return {str(row["task_key"]): _task_iso(row["acknowledged_at"]) for row in cursor.fetchall()}


def _task_item(job, events, materials, acknowledged_at=""):
    job_status = _task_status(job.get("status"))
    task_key = f"workflow:{job.get('id')}"
    download_only = _task_only_download(job, events)
    stage_events = [event for event in events if event["stage"] != "workflow"]
    latest = next((event for event in reversed(stage_events) if event["status"] == "running"), None) or (stage_events[-1] if stage_events else None)
    warning_events = [event for event in stage_events if _task_has_fallback(event, False)[0]]
    completion_at = _task_datetime(job.get("updated_at")) or _task_datetime(job.get("created_at"))
    expires_at = completion_at + datetime.timedelta(hours=_TASK_SUCCESS_RETENTION_HOURS) if job_status == "success" and completion_at else None
    has_publish_event = any(event["stage"] == "publish" for event in events)
    is_publish = has_publish_event or str(job.get("step") or "") in {"publish", "publish_confirmation"}
    scope = "download" if download_only else "publish" if is_publish else "processing"
    chinese_title = job.get("_task_chinese_title") or ""
    english_title = job.get("title") or job.get("video_id") or "未命名视频"
    return {
        "taskKey": task_key, "jobId": job.get("id"), "videoId": job.get("video_id") or "", "title": english_title,
        "englishTitle": english_title, "chineseTitle": chinese_title, "type": scope, "typeLabel": _task_type_label(scope, job, events), "scope": scope,
        "status": job_status, "statusLabel": _task_status_label(job_status), "progress": round(float(job.get("progress") or 0), 1),
        "currentStage": latest.get("label") if latest else _TASK_STAGE_LABELS.get(job.get("step"), job.get("step") or "等待开始"),
        "currentStageKey": latest.get("stage") if latest else job.get("step") or "workflow",
        "message": str(job.get("message") or (latest.get("message") if latest else "")),
        "errorReason": str(job.get("error_reason") or job.get("error_detail") or (latest.get("message") if latest and latest["status"] in {"failed", "abnormal"} else "")),
        "warningSummary": warning_events[0].get("message") if warning_events else "", "hasWarning": bool(warning_events),
        "startedAt": _task_iso(job.get("started_at") or job.get("created_at")), "updatedAt": _task_iso(job.get("updated_at") or job.get("created_at")),
        "finishedAt": _task_iso(completion_at) if job_status in _TASK_TERMINAL_STATUSES else "", "expiresAt": _task_iso(expires_at),
        "acknowledged": bool(acknowledged_at), "acknowledgedAt": acknowledged_at,
    }


def list_task_center(user_id, *, history=False, active_only=False):
    acknowledgements = _task_acknowledgements(user_id)
    now = _task_now()
    items = []
    for job, events, materials in _task_load(active_only=active_only):
        if _task_only_download(job, events):
            continue
        item = _task_item(job, events, materials, acknowledgements.get(f"workflow:{job.get('id')}", ""))
        status = item["status"]
        if status == "success" and item["expiresAt"] and _task_datetime(item["expiresAt"]) <= now and not history:
            continue
        if item["acknowledged"] and not history:
            continue
        items.append(item)
    groups = {"active": [], "waitingConfirmation": [], "recentCompleted": [], "abnormal": []}
    for item in items:
        if item["status"] in {"queued", "running"}:
            groups["active"].append(item)
        elif item["status"] == "waiting_confirmation":
            groups["waitingConfirmation"].append(item)
        elif item["status"] == "success":
            groups["recentCompleted"].append(item)
        else:
            groups["abnormal"].append(item)
    return {
        "items": items, "groups": groups,
        "summary": {
            "activeCount": len(groups["active"]), "waitingCount": len(groups["waitingConfirmation"]),
            "completedCount": len(groups["recentCompleted"]), "abnormalCount": len(groups["abnormal"]),
            "badgeCount": len(groups["active"]) + len(groups["waitingConfirmation"]) + len(groups["abnormal"]),
        },
    }


def get_task_center_detail(task_key, user_id):
    if not str(task_key or "").startswith("workflow:"):
        raise LookupError("任务标识无效")
    job_id = str(task_key).split(":", 1)[1]
    rows = _task_load(job_id)
    if not rows:
        raise LookupError("任务不存在")
    job, events, materials = rows[0]
    acknowledgements = _task_acknowledgements(user_id)
    item = _task_item(job, events, materials, acknowledgements.get(task_key, ""))
    if item["scope"] == "download":
        return {
            "task": item,
            "downloadOnly": True,
            "message": item["errorReason"] or item["message"] or "下载任务未进入后续处理阶段",
            "events": [],
            "graph": None,
        }
    subtitle_fallback = False
    try:
        with _db_connect(row_factory=True) as conn:
            row = conn.execute("SELECT review_status, fallback_segment_count FROM youtube_subtitle_audits WHERE job_id = ?", (job_id,)).fetchone()
            subtitle_fallback = bool(row and (str(row["review_status"] or "") == "partial_fallback" or int(row["fallback_segment_count"] or 0) > 0))
    except Exception:
        subtitle_fallback = False
    graph = _task_graph(job, events, materials, subtitle_fallback, item["scope"])
    nodes_by_stage = {}
    for node in graph["nodes"]:
        nodes_by_stage.setdefault(node["stage"], node)
    enriched_events = []
    for event in events:
        node = nodes_by_stage.get(event["stage"])
        if not node and event["stage"] == "body_burn":
            node = nodes_by_stage.get("subtitle_burn")
        enriched_events.append({
            **event,
            "laneId": node.get("laneId", "") if node else "",
            "dependencies": node.get("dependencies", []) if node else [],
            "parallelGroup": node.get("parallelGroup", "") if node else "",
            "platform": node.get("platform", "") if node else "",
            "fallbackReason": node.get("fallbackReason", "") if node else "",
            "inferred": bool(node and node.get("inferred")),
        })
    return {"task": item, "events": enriched_events, "graph": graph}


def acknowledge_task_center_task(task_key, user_id):
    detail = get_task_center_detail(task_key, user_id)
    acknowledged_at = _task_iso(_task_now())
    with _db_connect() as conn:
        conn.execute("""
            INSERT INTO task_acknowledgements (user_id, task_key, acknowledged_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, task_key) DO UPDATE SET acknowledged_at = EXCLUDED.acknowledged_at
        """, (int(user_id), task_key, acknowledged_at))
    detail["task"]["acknowledged"] = True
    detail["task"]["acknowledgedAt"] = acknowledged_at
    return detail["task"]
