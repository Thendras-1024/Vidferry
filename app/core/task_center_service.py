"""聚合工作流任务，供任务中心列表和流程详情使用。"""

import datetime
import json
_TASK_SUCCESS_RETENTION_HOURS = 12
_TASK_ACTIVE_STATUSES = {"queued", "running", "waiting_confirmation", "waiting_publish"}
_TASK_TERMINAL_STATUSES = {"success", "reused", "partial", "needs_verification", "failed", "abnormal", "cancelled"}
_TASK_RECOVERABLE_STAGES = {"comment_fetch", "comment_review", "comment_render", "subtitle", "highlight_render"}
_TASK_STAGE_LABELS = {
    "workflow": "工作流", "download": "下载", "transcript": "转写", "analysis": "内容分析",
    "content_safety_detect": "内容安全检测", "content_safety_confirm": "风险确认", "content_trim": "风险裁剪",
    "subtitle": "字幕处理", "subtitle_burn": "字幕烧制", "body_burn": "正片烧制",
    "comment_fetch": "评论获取", "comment_review": "评论筛选", "comment_render": "评论烧制",
    "cover_render": "封面片头", "highlight_render": "高光生成", "editing_concat": "正片拼接",
    "editing": "视频编辑", "publish": "发布",
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
    if operation in {"intro_refresh", "editing_intro", "cover_reburn"}:
        return "封面更新" if operation == "cover_reburn" else "片头更新"
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
    return status if status in {"queued", "running", "waiting_existing", "waiting_confirmation", "waiting_publish", "success", "confirmed", "reused", "partial", "uncertain", "needs_verification", "failed", "abnormal", "cancelled", "warning"} else "pending"


def _task_status_label(status):
    if status == "waiting_publish":
        return "发布排队中"
    return {
        "queued": "排队中", "running": "进行中", "waiting_confirmation": "等待确认",
        "success": "已完成", "confirmed": "已确认发布", "failed": "失败", "abnormal": "异常", "cancelled": "已取消", "warning": "已降级继续",
        "reused": "已复用", "partial": "部分完成", "uncertain": "待核验", "needs_verification": "待核验", "waiting_existing": "等待已有任务", "pending": "未开始", "waiting": "等待分支",
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
    dispatch_targets = {
        int(item.get("platform_type") or 0): item
        for item in (job.get("publishProgress") or {}).get("targets") or []
        if str(item.get("platform_type") or "").strip()
    }
    for target in _task_targets(job, material_rows):
        lane_id = f"publish-{target['type']}"
        lanes.append({"id": lane_id, "label": target["label"]})
        record = dispatch_targets.get(target["type"]) or (target["records"][-1] if target["records"] else {})
        target_status = _task_status(record.get("status")) if record else ("running" if status == "running" else "pending")
        nodes.append({
            "id": lane_id, "stage": "publish", "label": target["label"], "laneId": lane_id, "column": 1,
            "status": target_status, "statusLabel": _task_status_label(target_status),
            "message": str(record.get("message") or target.get("account") or "等待发布"),
            "startedAt": _task_iso(record.get("started_at")), "endedAt": _task_iso(record.get("finished_at") or record.get("published_at") or record.get("updated_at")),
            "durationSeconds": float(record.get("duration_ms") or 0) / 1000, "dependencies": ["publish"],
            "parallelGroup": "publish-platforms", "platform": target["label"], "fallbackReason": "",
            "errorReason": str(record.get("message") or "") if target_status == "failed" else "",
            "inferred": not bool(record), "synthetic": True,
        })
        edges.append({"from": "publish", "to": lane_id, "kind": "parallel", "status": "failed" if target_status == "failed" else "warning" if target_status in {"uncertain", "needs_verification", "cancelled"} else "running" if target_status in {"running", "queued", "waiting_existing"} else "reused" if target_status == "reused" else "success" if target_status in {"success", "confirmed"} else "pending"})
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
            elif all(item in {"success", "confirmed", "reused"} for item in dependencies):
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


def _task_load(job_id=None, *, active_only=False, owner_user_id=None, terminal_statuses=(), query_conditions=(), query_values=(), order_by="", page=None, page_size=None, include_meta=False):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        conditions = []
        values = []
        if job_id:
            conditions.append("id = %s")
            values.append(job_id)
        if owner_user_id is not None:
            conditions.append("owner_user_id = %s")
            values.append(int(owner_user_id))
        if active_only:
            statuses = tuple(sorted(_TASK_ACTIVE_STATUSES))
            marks = ",".join("%s" for _ in statuses)
            conditions.append(f"status IN ({marks})")
            values.extend(statuses)
        elif terminal_statuses:
            marks = ",".join("%s" for _ in terminal_statuses)
            conditions.append(f"status IN ({marks})")
            values.extend(terminal_statuses)
        conditions.extend(query_conditions)
        values.extend(query_values)
        where_sql = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        total = 0
        summary = {}
        if include_meta:
            cursor.execute(f"SELECT status, COUNT(*) AS total FROM youtube_workflow_jobs{where_sql} GROUP BY status", values)
            summary = {str(row["status"] or "pending"): int(row["total"] or 0) for row in cursor.fetchall()}
            total = sum(summary.values())
        order_sql = order_by or "COALESCE(updated_at, created_at) DESC, created_at DESC, id DESC"
        limit_sql = ""
        query_params = list(values)
        if page is not None and page_size is not None:
            limit_sql = " LIMIT %s OFFSET %s"
            query_params.extend([int(page_size), (int(page) - 1) * int(page_size)])
        cursor.execute(
            f"SELECT * FROM youtube_workflow_jobs{where_sql} "
            f"ORDER BY {order_sql}{limit_sql}",
            query_params,
        )
        jobs = [_task_row(row) for row in cursor.fetchall()]
        if not jobs:
            return ([], total, summary) if include_meta else []
        ids = [job.get("id") for job in jobs]
        marks = ",".join("%s" for _ in ids)
        cursor.execute(f"SELECT * FROM youtube_workflow_events WHERE job_id IN ({marks}) ORDER BY started_at, id", ids)
        event_map = {}
        for row in cursor.fetchall():
            event = _task_event(row)
            event_map.setdefault(str(row["job_id"]), []).append(event)
        owner_video_pairs = sorted({
            (int(job["owner_user_id"]), str(job["video_id"]))
            for job in jobs
            if str(job.get("owner_user_id") or "").strip().isdigit() and job.get("video_id")
        })
        owner_video_where = " OR ".join("(owner_user_id = %s AND video_id = %s)" for _ in owner_video_pairs)
        owner_video_values = [value for pair in owner_video_pairs for value in pair]
        title_translation_map = {}
        if owner_video_pairs:
            cursor.execute(f'''
            SELECT owner_user_id, video_id, metadata FROM youtube_workflow_events
            WHERE ({owner_video_where})
              AND stage = 'source_title_translation'
              AND status = 'success'
            ORDER BY ended_at DESC, id DESC
            ''', owner_video_values)
            for row in cursor.fetchall():
                key = (int(row["owner_user_id"]), str(row["video_id"] or ""))
                if key in title_translation_map:
                    continue
                metadata = _task_json(row["metadata"])
                title = str(metadata.get("sourceTitleZh") or "").strip()
                if title:
                    title_translation_map[key] = title
        material_map = {}
        if owner_video_pairs:
            cursor.execute(f"SELECT * FROM published_youtube_materials WHERE ({owner_video_where}) AND deleted_at IS NULL ORDER BY COALESCE(updated_at, published_at, created_at), id", owner_video_values)
            for row in cursor.fetchall():
                item = _task_row(row)
                key = (int(item["owner_user_id"]), str(item.get("video_id") or ""))
                material_map.setdefault(key, []).append(item)
        job_marks = ",".join("%s" for _ in ids)
        cursor.execute(
            f"SELECT id, source_ref_id, status, message FROM publish_dispatch_jobs "
            f"WHERE source = 'workflow' AND source_ref_id IN ({job_marks}) "
            "ORDER BY source_ref_id, created_at DESC, id DESC",
            ids,
        )
        dispatch_rows = [dict(row) for row in cursor.fetchall()]
        latest_dispatch_by_job = {}
        for dispatch in dispatch_rows:
            latest_dispatch_by_job.setdefault(str(dispatch.get("source_ref_id") or ""), dispatch)
        dispatch_ids = [item["id"] for item in latest_dispatch_by_job.values()]
        targets_by_dispatch = {}
        if dispatch_ids:
            dispatch_marks = ",".join("%s" for _ in dispatch_ids)
            cursor.execute(
                f"SELECT platform_type, status, message, duration_ms, started_at, finished_at, job_id "
                f"FROM publish_dispatch_targets WHERE job_id IN ({dispatch_marks}) ORDER BY platform_type, id",
                dispatch_ids,
            )
            for row in cursor.fetchall():
                target = _task_row(row)
                targets_by_dispatch.setdefault(str(target.get("job_id") or ""), []).append(target)
        for job in jobs:
            dispatch = latest_dispatch_by_job.get(str(job.get("id") or ""))
            if not dispatch:
                continue
            targets = targets_by_dispatch.get(str(dispatch["id"]), [])
            progress = _publish_dispatch_progress(targets)
            progress.update({
                "publishTaskId": dispatch["id"],
                "status": dispatch.get("status") or "pending",
                "message": clean_display_text(dispatch.get("message")),
                "updatedAt": _task_iso(dispatch.get("updated_at")),
                "finishedAt": _task_iso(dispatch.get("finished_at")),
                "targets": targets,
            })
            job["publishProgress"] = progress
        for job in jobs:
            key = (int(job["owner_user_id"]), str(job.get("video_id") or ""))
            job["_task_chinese_title"] = title_translation_map.get(key, "")
        owner_ids = sorted({
            int(job["owner_user_id"])
            for job in jobs
            if str(job.get("owner_user_id") or "").strip().isdigit()
        })
        owner_names = {}
        if owner_ids:
            marks = ",".join("%s" for _ in owner_ids)
            cursor.execute(f"SELECT id, display_name, username FROM auth_users WHERE id IN ({marks})", owner_ids)
            owner_names = {
                int(row["id"]): str(row["display_name"] or row["username"] or "")
                for row in cursor.fetchall()
            }
        for job in jobs:
            owner_id = job.get("owner_user_id")
            job["_task_owner_display_name"] = owner_names.get(int(owner_id)) if str(owner_id or "").strip().isdigit() else ""
        rows = []
        for job in jobs:
            materials = material_map.get((int(job["owner_user_id"]), str(job.get("video_id") or "")), [])
            task_id = f"workflow:{job.get('id')}"
            rows.append((
                job,
                event_map.get(str(job.get("id")), []),
                [item for item in materials if str(item.get("publish_task_id") or "") == task_id],
            ))
        return (rows, total, summary) if include_meta else rows


def _task_acknowledgements(user_id):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT task_key, acknowledged_at FROM task_acknowledgements WHERE user_id = %s", (int(user_id),))
        return {str(row["task_key"]): _task_iso(row["acknowledged_at"]) for row in cursor.fetchall()}


def _task_history_statuses(result):
    if result == "success":
        return ("success", "reused")
    if result == "problem":
        return ("partial", "needs_verification", "failed", "abnormal")
    return tuple(sorted(_TASK_TERMINAL_STATUSES))


def _task_unified_query(*, keyword="", task_type="all", status="all", updated_from="", updated_to=""):
    download_sql = "LOWER(COALESCE(operation, '')) IN ('download', 'download_only', 'download-only')"
    publish_sql = "(EXISTS (SELECT 1 FROM youtube_workflow_events event WHERE event.job_id = youtube_workflow_jobs.id AND event.stage = 'publish') OR COALESCE(step, '') IN ('publish', 'publish_confirmation'))"
    editing_sql = "LOWER(COALESCE(operation, '')) IN ('intro_refresh', 'editing_intro', 'cover_reburn', 'editing', 'editing_concat')"
    type_sql = {
        "download": download_sql,
        "publish": publish_sql,
        "editing": editing_sql,
        "processing": f"NOT ({download_sql} OR {publish_sql} OR {editing_sql})",
    }.get(str(task_type or "all").lower())
    conditions = []
    values = []
    if type_sql:
        conditions.append(type_sql)
    status_key = str(status or "all").lower()
    status_groups = {
        "active": tuple(sorted(_TASK_ACTIVE_STATUSES)),
        "waiting_confirmation": ("waiting_confirmation",),
        "success": ("success", "reused"),
        "problem": ("partial", "needs_verification", "failed", "abnormal"),
        "reused": ("reused",),
        "partial": ("partial",),
        "needs_verification": ("needs_verification",),
        "failed": ("failed",),
        "abnormal": ("abnormal",),
        "cancelled": ("cancelled",),
    }
    if status_key in status_groups:
        statuses = status_groups[status_key]
        marks = ",".join("%s" for _ in statuses)
        conditions.append(f"status IN ({marks})")
        values.extend(statuses)
    if keyword:
        like = f"%{str(keyword).strip()}%"
        conditions.append("(" + " OR ".join(
            "COALESCE({0}, '') ILIKE %s".format(field)
            for field in ("id", "video_id", "title", "message", "error_reason", "error_detail")
        ) + ")")
        values.extend([like] * 6)
    if updated_from:
        conditions.append("COALESCE(updated_at, created_at) >= %s")
        values.append(f"{updated_from} 00:00:00")
    if updated_to:
        conditions.append("COALESCE(updated_at, created_at) <= %s")
        values.append(f"{updated_to} 23:59:59")
    return conditions, values


def _task_unified_sort(sort):
    field = {
        "created_desc": "COALESCE(created_at, updated_at) DESC, id DESC",
        "finished_desc": "COALESCE(updated_at, created_at) DESC, id DESC",
    }.get(str(sort or "updated_desc").lower(), "COALESCE(updated_at, created_at) DESC, id DESC")
    return f"CASE WHEN status IN ('queued', 'running', 'waiting_confirmation', 'waiting_publish') THEN 0 ELSE 1 END, {field}"


def _task_unified_item(job, events, materials, acknowledged_at=""):
    item = _task_item(job, events, materials, acknowledged_at)
    operation = str(job.get("operation") or "").lower()
    if operation in {"intro_refresh", "editing_intro", "cover_reburn", "editing", "editing_concat"}:
        item["type"] = "editing"
        item["scope"] = "editing"
        item["typeLabel"] = _task_type_label("processing", job, events)
    return item


def list_all_task_center(user_id, *, is_admin=False, task_type="all", status="all", keyword="", owner="all", updated_from="", updated_to="", sort="updated_desc", page=1, page_size=20):
    page = _task_page(page, 1, 1, 100000)
    page_size = _task_page(page_size, 20, 1, 100)
    owner_user_id = None if is_admin and str(owner or "all").lower() == "all" else user_id
    query_conditions, query_values = _task_unified_query(
        keyword=keyword, task_type=task_type, status=status, updated_from=updated_from, updated_to=updated_to,
    )
    rows, total, status_counts = _task_load(
        owner_user_id=owner_user_id,
        query_conditions=query_conditions,
        query_values=query_values,
        order_by=_task_unified_sort(sort),
        page=page,
        page_size=page_size,
        include_meta=True,
    )
    acknowledgements = _task_acknowledgements(user_id)
    items = [
        _task_unified_item(job, events, materials, acknowledgements.get(f"workflow:{job.get('id')}", ""))
        for job, events, materials in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "summary": {
            "total": total,
            "active": sum(status_counts.get(value, 0) for value in _TASK_ACTIVE_STATUSES),
            "waitingConfirmation": status_counts.get("waiting_confirmation", 0),
            "success": status_counts.get("success", 0) + status_counts.get("reused", 0),
            "reused": status_counts.get("reused", 0),
            "partial": status_counts.get("partial", 0),
            "needsVerification": status_counts.get("needs_verification", 0),
            "failed": status_counts.get("failed", 0),
            "abnormal": status_counts.get("abnormal", 0),
            "cancelled": status_counts.get("cancelled", 0),
        },
    }


def _task_page(value, default, minimum, maximum):
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def list_task_center(user_id, *, is_admin=False, history=False, active_only=False, result="all", scope="all", page=1, page_size=20):
    acknowledgements = _task_acknowledgements(user_id)
    now = _task_now()
    items = []
    seen_video_keys = set()
    owner_user_id = None if history and is_admin and scope != "mine" else user_id
    rows = _task_load(
        active_only=active_only and not history,
        owner_user_id=owner_user_id,
        terminal_statuses=_task_history_statuses(result) if history else (),
    )
    for job, events, materials in rows:
        if _task_only_download(job, events):
            continue
        item = _task_item(job, events, materials, acknowledgements.get(f"workflow:{job.get('id')}", ""))
        if not history:
            video_id = str(item.get("videoId") or "").strip()
            video_key = (item.get("ownerUserId"), video_id) if video_id else (item.get("ownerUserId"), item.get("taskKey"))
            if video_key in seen_video_keys:
                continue
            seen_video_keys.add(video_key)
        status = item["status"]
        if status == "success" and item["expiresAt"] and _task_datetime(item["expiresAt"]) <= now and not history:
            continue
        if item["acknowledged"] and not history:
            continue
        items.append(item)
    if history:
        page = _task_page(page, 1, 1, 100000)
        page_size = _task_page(page_size, 20, 1, 100)
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "total": total, "page": page, "pageSize": page_size}
    groups = {"active": [], "waitingConfirmation": [], "recentCompleted": [], "abnormal": []}
    for item in items:
        if item["status"] in {"queued", "running", "waiting_publish"}:
            groups["active"].append(item)
        elif item["status"] == "waiting_confirmation":
            groups["waitingConfirmation"].append(item)
        elif item["status"] in {"success", "reused"}:
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


def get_task_center_detail(task_key, user_id, *, is_admin=False):
    if not str(task_key or "").startswith("workflow:"):
        raise LookupError("任务标识无效")
    job_id = str(task_key).split(":", 1)[1]
    rows = _task_load(job_id)
    if not rows:
        raise LookupError("任务不存在")
    job, events, materials = rows[0]
    if not is_admin and job.get("owner_user_id") != int(user_id):
        raise LookupError("任务不存在")
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
            row = conn.execute("SELECT review_status, fallback_segment_count FROM youtube_subtitle_audits WHERE job_id = %s", (job_id,)).fetchone()
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


def acknowledge_task_center_task(task_key, user_id, *, is_admin=False):
    detail = get_task_center_detail(task_key, user_id, is_admin=is_admin)
    acknowledged_at = _task_iso(_task_now())
    with _db_connect() as conn:
        conn.execute("""
            INSERT INTO task_acknowledgements (user_id, task_key, acknowledged_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, task_key) DO UPDATE SET acknowledged_at = EXCLUDED.acknowledged_at
        """, (int(user_id), task_key, acknowledged_at))
    detail["task"]["acknowledged"] = True
    detail["task"]["acknowledgedAt"] = acknowledged_at
    return detail["task"]
