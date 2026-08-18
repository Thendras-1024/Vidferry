"""本机实例级通知中心：服务端对账、聚合、状态流转与历史清理。"""

import datetime
import json


NOTIFICATION_HISTORY_RETENTION_DAYS = 30
NOTIFICATION_HISTORY_PAGE_SIZE = 50


def _notification_now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _notification_json(value, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _notification_time(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat(timespec="seconds")
    return value or ""


def _notification_item(row):
    item = dict(row)
    return {
        "id": int(item.get("id") or 0),
        "type": item.get("notification_type") or "",
        "severity": item.get("severity") or "warning",
        "aggregateKey": item.get("aggregate_key") or "",
        "title": item.get("title") or "",
        "content": item.get("content") or "",
        "actionRoute": _notification_json(item.get("action_route"), {}),
        "sourceRefs": _notification_json(item.get("source_refs"), []),
        "occurrenceCount": int(item.get("occurrence_count") or 1),
        "status": item.get("status") or "active",
        "firstSeenAt": _notification_time(item.get("first_seen_at")),
        "lastSeenAt": _notification_time(item.get("last_seen_at")),
        "acknowledgedAt": _notification_time(item.get("acknowledged_at")),
        "resolvedAt": _notification_time(item.get("resolved_at")),
        "updatedAt": _notification_time(item.get("updated_at") or item.get("last_seen_at")),
    }


def _notification_issue(notification_type, severity, aggregate_key, title, content, action_route, source_refs):
    return {
        "type": notification_type,
        "severity": severity,
        "aggregateKey": aggregate_key,
        "title": title,
        "content": content,
        "actionRoute": action_route or {},
        "sourceRefs": source_refs[:20],
    }


def _notification_platform(job):
    message = " ".join(str(job.get(key) or "") for key in ("message", "error_code", "error_reason", "error_detail")).lower()
    if "bilibili" in message or "b站" in message:
        return "B站"
    if "douyin" in message or "抖音" in message:
        return "抖音"
    if "xiaohongshu" in message or "小红书" in message:
        return "小红书"
    if "kuaishou" in message or "快手" in message:
        return "快手"
    if "tencent" in message or "视频号" in message:
        return "视频号"
    return "发布平台"


def _is_notification_upload_paused(job):
    message = " ".join(str(job.get(key) or "") for key in ("message", "error_code", "error_reason", "error_detail"))
    return any(marker in message for marker in ("VF-PUBLISH-UPLOAD-PAUSED", "上传已暂停", "暂停传输", "继续上传"))


def _workflow_notification_issues(cursor, owner_user_id):
    cursor.execute('''
    SELECT id, video_id, title, status, step, message, error_code, error_type, error_reason,
           error_detail, publish_confirmation_required, updated_at
    FROM youtube_workflow_jobs
    WHERE owner_user_id = %s AND status IN ('failed', 'abnormal', 'waiting_confirmation')
    ORDER BY updated_at DESC, id DESC
    ''', (owner_user_id,))
    grouped = {}
    for row in cursor.fetchall():
        job = dict(row)
        title = job.get("title") or job.get("video_id") or "未命名任务"
        route = {"path": "/youtube-research", "query": {"focusJob": job.get("id") or "", "focusAction": "error"}}
        if job.get("status") == "waiting_confirmation" and job.get("step") == "content_safety_confirm":
            key = "content-safety-confirmation"
            issue = grouped.setdefault(key, {"type": "content-safety-confirmation", "severity": "warning", "items": [], "route": {"path": "/subtitle-audit", "query": {"jobId": job.get("id") or ""}}})
        elif job.get("status") == "waiting_confirmation" and job.get("publish_confirmation_required"):
            key = "publish-confirmation"
            issue = grouped.setdefault(key, {"type": "publish-confirmation", "severity": "warning", "items": [], "route": route})
        elif job.get("status") == "abnormal":
            error_key = job.get("error_code") or job.get("error_type") or "unknown"
            key = f"workflow-abnormal:{error_key}"
            issue = grouped.setdefault(key, {"type": "workflow-abnormal", "severity": "danger", "items": [], "route": route, "error": error_key})
        elif _is_notification_upload_paused(job):
            platform = _notification_platform(job)
            key = f"publish-upload-paused:{platform}"
            issue = grouped.setdefault(key, {"type": "publish-upload-paused", "severity": "warning", "items": [], "route": {"path": "/publish-center"}, "platform": platform})
        else:
            error_key = job.get("error_code") or job.get("error_type") or "unknown"
            key = f"workflow-failed:{error_key}"
            issue = grouped.setdefault(key, {"type": "workflow-failed", "severity": "danger", "items": [], "route": route, "error": error_key})
        issue["items"].append({"id": job.get("id") or "", "title": title, "reason": job.get("error_reason") or job.get("message") or "任务需要处理"})

    issues = []
    for aggregate_key, group in grouped.items():
        count = len(group["items"])
        first = group["items"][0]
        suffix = f"等 {count} 个任务" if count > 1 else ""
        if group["type"] == "content-safety-confirmation":
            title = f"{count} 个视频等待广告裁剪确认"
            content = f"{first['title']}{suffix} 检测到站外引流或长广告，需要确认裁剪范围。"
        elif group["type"] == "publish-confirmation":
            title = f"{count} 个发布任务等待确认"
            content = f"{first['title']}{suffix} 检测到发布前风险，需要人工确认。"
        elif group["type"] == "publish-upload-paused":
            title = f"{group['platform']}上传已暂停"
            content = f"{first['title']}{suffix} 的上传需要恢复或重新发起。"
        elif group["type"] == "workflow-abnormal":
            title = f"{count} 个任务异常中断"
            content = f"{first['title']}{suffix}：{first['reason']}"
        else:
            title = f"{count} 个任务处理失败"
            content = f"{first['title']}{suffix}：{first['reason']}"
        issues.append(_notification_issue(group["type"], group["severity"], aggregate_key, title, content, group["route"], group["items"]))
    return issues


def _publish_target_notification_issues(cursor, owner_user_id):
    cursor.execute('''
    SELECT record.id, record.video_id, record.platform, record.status, record.message,
           COALESCE(video.title, record.title, record.video_id) AS title
    FROM published_youtube_materials record
    LEFT JOIN youtube_videos video ON video.video_id = record.video_id AND video.owner_user_id = record.owner_user_id
    WHERE record.owner_user_id = %s AND record.deleted_at IS NULL AND record.status IN ('failed', 'uncertain')
    ORDER BY record.updated_at DESC, record.id DESC
    ''', (owner_user_id,))
    groups = {"failed": [], "uncertain": []}
    for row in cursor.fetchall():
        item = dict(row)
        groups[item["status"]].append({
            "id": item.get("id"),
            "title": item.get("title") or "未命名视频",
            "platform": item.get("platform") or "平台",
            "reason": item.get("message") or "发布状态需要处理",
        })
    issues = []
    if groups["uncertain"]:
        items = groups["uncertain"]
        issues.append(_notification_issue(
            "publish-target-uncertain", "warning", "publish-target-uncertain",
            f"{len(items)} 个平台发布结果待核验",
            f"{items[0]['title']} 在 {items[0]['platform']} 的发布结果不确定，请核验后处理。",
            {"path": "/publish-center"}, items,
        ))
    if groups["failed"]:
        items = groups["failed"]
        issues.append(_notification_issue(
            "publish-target-failed", "danger", "publish-target-failed",
            f"{len(items)} 个平台发布失败",
            f"{items[0]['title']} 在 {items[0]['platform']} 发布失败，可在发布中心重试。",
            {"path": "/publish-center"}, items,
        ))
    return issues


def _account_notification_issues(cursor, owner_user_id):
    cursor.execute("SELECT source_refs FROM app_notifications WHERE owner_user_id = %s AND notification_type = 'publish-cookie-invalid' AND source_active = 1", (owner_user_id,))
    cookie_invalid_account_ids = {
        int(item.get("accountId"))
        for row in cursor.fetchall()
        for item in _notification_json(row["source_refs"], [])
        if isinstance(item, dict) and str(item.get("accountId") or "").isdigit()
    }
    cursor.execute("SELECT id, type, userName, status FROM user_info WHERE owner_user_id = %s AND COALESCE(status, 0) = 0 ORDER BY id DESC", (owner_user_id,))
    groups = {}
    for row in cursor.fetchall():
        item = row
        if int(item.get("id") or 0) in cookie_invalid_account_ids:
            continue
        platform = {1: "小红书", 2: "视频号", 3: "抖音", 4: "快手", 5: "B站"}.get(int(item.get("type") or 0), "平台")
        groups.setdefault(platform, []).append({"id": item.get("id"), "title": item.get("userName") or "未命名账号"})
    return [
        _notification_issue(
            "account-abnormal", "warning", f"account-abnormal:{platform}", f"{platform}账号需要重新连接",
            f"{items[0]['title']}{f' 等 {len(items)} 个账号' if len(items) > 1 else ''} 的登录状态异常，请在账号管理中处理。",
            {"path": "/account-management"}, items,
        )
        for platform, items in groups.items()
    ]


def create_publish_cookie_invalid_notification(task, reason):
    account_id = int(task.get("accountId") or 0)
    owner_user_id = int(task.get("ownerUserId") or 0)
    if not account_id or not owner_user_id:
        return
    platform = task.get("platformName") or platform_name(task.get("platformType"))
    publish_task_id = str(task.get("publishTaskId") or "")
    source_key = f"publish-cookie-invalid:{publish_task_id}:{task.get('platformType')}:{account_id}"
    source_ref = {
        "id": source_key,
        "accountId": account_id,
        "ownerUserId": owner_user_id,
        "publishTaskId": publish_task_id,
        "platformType": int(task.get("platformType") or 0),
        "platformName": platform,
        "title": task.get("title") or "当前视频",
        "reason": str(reason or "Cookie 已失效"),
    }
    issue = _notification_issue(
        "publish-cookie-invalid", "danger", source_key,
        f"{platform}账号 Cookie 已失效",
        f"{source_ref['title']} 发布失败：{source_ref['reason']}",
        {"path": "/account-management"}, [source_ref],
    )
    _sync_notification_issues([issue], owner_user_id=owner_user_id, resolve_stale=False)


def resolve_publish_cookie_invalid_notifications(account_id, owner_user_id):
    account_id = int(account_id or 0)
    owner_user_id = int(owner_user_id or 0)
    if not account_id or not owner_user_id:
        return
    now = _notification_now()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, source_refs FROM app_notifications WHERE owner_user_id = %s AND notification_type = 'publish-cookie-invalid' AND source_active = 1", (owner_user_id,))
        notification_ids = [
            row["id"]
            for row in cursor.fetchall()
            if any(
                int(item.get("accountId") or 0) == account_id and int(item.get("ownerUserId") or 0) == owner_user_id
                for item in _notification_json(row["source_refs"], [])
                if isinstance(item, dict)
            )
        ]
        if notification_ids:
            cursor.executemany(
                "UPDATE app_notifications SET status = 'resolved', source_active = 0, resolved_at = %s, updated_at = %s WHERE id = %s",
                [(now, now, notification_id) for notification_id in notification_ids],
            )


def _runtime_notification_issues():
    issues = []
    runtime_status = globals().get("get_runtime_config_status")
    if callable(runtime_status):
        for name, status in (runtime_status() or {}).items():
            if status and (not status.get("ready") or status.get("level") == "error"):
                issues.append(_notification_issue("runtime-config", "danger", f"runtime-config:{name}", "运行环境配置需要处理", status.get("message") or f"{name} 不可用", {"path": "/youtube-research"}, [{"id": name, "title": name}]))
    llm_status = globals().get("get_llm_config_status")
    if callable(llm_status):
        statuses = llm_status() or {}
        text = statuses.get("text") or {}
        agent = statuses.get("agent") or {}
        multimodal = statuses.get("multimodal") or {}
        if text and not text.get("ready"):
            issues.append(_notification_issue("llm-unavailable", "danger", "llm-unavailable", "文本 AI 功能不可用", text.get("message") or "请检查模型配置后重启后端。", {"path": "/youtube-research"}, [{"id": "text", "title": "文本模型"}]))
        if agent and not agent.get("ready"):
            issues.append(_notification_issue("agent-llm-unavailable", "danger", "agent-llm-unavailable", "Agent 模型不可用", agent.get("message") or "请检查 Agent 模型配置后重启后端。", {"path": "/agent"}, [{"id": "agent", "title": "Agent 模型"}]))
        if multimodal and (not multimodal.get("ready") or not multimodal.get("visionReady", True)):
            issues.append(_notification_issue("llm-multimodal-unavailable", "danger", "llm-multimodal-unavailable", "多模态 AI 功能不可用", multimodal.get("message") or "当前多模态模型不支持图片输入。", {"path": "/youtube-research"}, [{"id": "multimodal", "title": "多模态模型"}]))
        for channel, status in (("text", text), ("multimodal", multimodal)):
            if status.get("ready") and status.get("thinkingRequested") and not status.get("thinkingDisabled"):
                key = f"llm-thinking-enabled:{channel}:{status.get('provider')}:{status.get('model')}"
                issues.append(_notification_issue("llm-thinking-enabled", "warning", key, "模型推理未关闭", f"{channel} 模型 {status.get('model') or '未命名'} 不支持关闭推理，已按兼容模式继续调用。", {"path": "/youtube-research"}, [{"id": channel, "title": status.get("provider") or "模型服务"}]))
    return issues


def _sync_notification_issues(issues, owner_user_id, resolve_stale=True):
    init_youtube_workflow_table()
    now = _notification_now()
    active_keys = {issue["aggregateKey"] for issue in issues}
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        for issue in issues:
            cursor.execute("SELECT id, status, source_active, manual_resolved, source_refs, title, content, last_seen_at, updated_at FROM app_notifications WHERE owner_user_id = %s AND aggregate_key = %s", (owner_user_id, issue["aggregateKey"]))
            existing = cursor.fetchone()
            values = (
                issue["type"], issue["severity"], issue["title"], issue["content"],
                json.dumps(issue["actionRoute"], ensure_ascii=False), json.dumps(issue["sourceRefs"], ensure_ascii=False), now,
            )
            if existing:
                reopened = not bool(existing["source_active"])
                source_refs = json.dumps(issue["sourceRefs"], ensure_ascii=False)
                changed = any((
                    existing["source_refs"] != source_refs,
                    existing["title"] != issue["title"],
                    existing["content"] != issue["content"],
                ))
                cursor.execute('''
                UPDATE app_notifications
                SET notification_type = %s, severity = %s, title = %s, content = %s, action_route = %s, source_refs = %s,
                    occurrence_count = occurrence_count + %s, status = %s, last_seen_at = %s,
                    acknowledged_at = CASE WHEN %s THEN NULL ELSE acknowledged_at END,
                    resolved_at = CASE WHEN %s THEN NULL ELSE resolved_at END,
                    source_active = 1, manual_resolved = CASE WHEN %s THEN 0 ELSE manual_resolved END,
                    updated_at = %s
                WHERE id = %s
                ''', (*values[:6], int(changed or reopened), "active" if reopened else existing["status"], now if changed or reopened else existing["last_seen_at"], reopened, reopened, reopened, now if changed or reopened else existing["updated_at"], existing["id"]))
            else:
                cursor.execute('''
                INSERT INTO app_notifications (
                    owner_user_id, notification_type, severity, aggregate_key, title, content, action_route, source_refs,
                    occurrence_count, status, source_active, manual_resolved, first_seen_at, last_seen_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'active', 1, 0, %s, %s, %s)
                ''', (owner_user_id, issue["type"], issue["severity"], issue["aggregateKey"], *values[2:6], now, now, now))
        if resolve_stale:
            cursor.execute("SELECT id, aggregate_key FROM app_notifications WHERE owner_user_id = %s AND source_active = 1 AND notification_type NOT IN ('direct-publish-failed', 'publish-cookie-invalid')", (owner_user_id,))
            stale_ids = [row["id"] for row in cursor.fetchall() if row["aggregate_key"] not in active_keys]
            if stale_ids:
                cursor.executemany("UPDATE app_notifications SET status = 'resolved', source_active = 0, resolved_at = %s, updated_at = %s WHERE id = %s", [(now, now, item_id) for item_id in stale_ids])
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=NOTIFICATION_HISTORY_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM app_notifications WHERE owner_user_id = %s AND status = 'resolved' AND resolved_at IS NOT NULL AND resolved_at < %s", (owner_user_id, cutoff))


def reconcile_notifications(owner_user_id):
    init_youtube_workflow_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        issues = (
            _workflow_notification_issues(cursor, owner_user_id)
            + _publish_target_notification_issues(cursor, owner_user_id)
            + _account_notification_issues(cursor, owner_user_id)
        )
    _sync_notification_issues(issues + _runtime_notification_issues(), owner_user_id)


def notification_summary(owner_user_id):
    reconcile_notifications(owner_user_id)
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM app_notifications WHERE owner_user_id = %s AND status = 'active'", (owner_user_id,))
        active_count = int(cursor.fetchone()["total"] or 0)
        cursor.execute("SELECT COUNT(*) AS total FROM app_notifications WHERE owner_user_id = %s AND status = 'active' AND acknowledged_at IS NULL", (owner_user_id,))
        unread_count = int(cursor.fetchone()["total"] or 0)
    return {"activeCount": active_count, "unreadCount": unread_count, "badgeCount": min(unread_count, 9)}


def list_notifications(state="active", page=1, page_size=50, owner_user_id=None):
    reconcile_notifications(owner_user_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(NOTIFICATION_HISTORY_PAGE_SIZE, int(page_size or NOTIFICATION_HISTORY_PAGE_SIZE)))
    offset = (page - 1) * page_size
    status_filter = "status IN ('active', 'acknowledged')" if state == "active" else "status = 'resolved'"
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) AS total FROM app_notifications WHERE owner_user_id = %s AND {status_filter}", (owner_user_id,))
        total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(f"SELECT * FROM app_notifications WHERE owner_user_id = %s AND {status_filter} ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s", (owner_user_id, page_size, offset))
        items = [_notification_item(row) for row in cursor.fetchall()]
    return {"items": items, "total": total, "page": page, "pageSize": page_size, "summary": notification_summary(owner_user_id)}


def update_notification_state(notification_id, state, owner_user_id):
    if state not in {"acknowledged", "resolved"}:
        raise ValueError("通知状态仅支持 acknowledged 或 resolved")
    now = _notification_now()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM app_notifications WHERE id = %s AND owner_user_id = %s", (int(notification_id), owner_user_id))
        row = cursor.fetchone()
        if not row:
            raise LookupError("通知不存在")
        if state == "acknowledged" and row["status"] == "active":
            cursor.execute("UPDATE app_notifications SET status = 'acknowledged', acknowledged_at = %s, updated_at = %s WHERE id = %s", (now, now, notification_id))
        elif state == "resolved" and row["status"] != "resolved":
            cursor.execute("UPDATE app_notifications SET status = 'resolved', manual_resolved = 1, resolved_at = %s, updated_at = %s WHERE id = %s", (now, now, notification_id))
        cursor.execute("SELECT * FROM app_notifications WHERE id = %s AND owner_user_id = %s", (notification_id, owner_user_id))
        return _notification_item(cursor.fetchone())


def create_direct_publish_failure_notification(payload, owner_user_id):
    payload = payload or {}
    source_key = str(payload.get("publishTaskId") or payload.get("createdAt") or "").strip()
    if not source_key:
        raise ValueError("直接发布失败通知缺少任务标识")
    title = str(payload.get("title") or "当前视频").strip()
    target_results = [item for item in (payload.get("targetResults") or []) if isinstance(item, dict)]
    platforms = "、".join(str(item).strip() for item in (payload.get("failedPlatforms") or []) if str(item).strip())
    reason = str(payload.get("reason") or "请查看发布中心结果后重试。").strip()
    if target_results:
        labels = {"confirmed": "已确认发布", "reused": "复用已发布结果", "failed": "失败", "uncertain": "待核验", "waiting_existing": "等待已有任务"}
        reason = "；".join(
            f"{item.get('platformName') or '平台'}：{labels.get(item.get('status'), item.get('status') or '未知')}"
            + (f"（{item.get('message')}）" if item.get("message") else "")
            for item in target_results
        )
        platforms = "、".join(str(item.get("platformName") or "").strip() for item in target_results if item.get("platformName"))
    unresolved = any(item.get("status") in {"failed", "uncertain"} for item in target_results)
    issue = _notification_issue(
        "direct-publish-failed", "danger" if unresolved or not target_results else "warning", f"direct-publish-failed:{source_key}",
        "直接发布未完成" if unresolved or not target_results else "直接发布未重复提交",
        f"{title}{f' 在 {platforms}' if platforms else ''}：{reason}",
        {"path": "/publish-center"}, [{"id": source_key, "title": title}],
    )
    _sync_notification_issues([issue], owner_user_id=owner_user_id, resolve_stale=False)
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            "SELECT * FROM app_notifications WHERE owner_user_id = %s AND aggregate_key = %s",
            (owner_user_id, issue["aggregateKey"]),
        ).fetchone()
    return _notification_item(row)
