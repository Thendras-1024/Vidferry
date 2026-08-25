"""本地定时发布任务的持久化与执行。"""


def _scheduled_now():
    # 定时发布的时间基准：naive 本地时间，秒级精度。本工具为本地优先、单机单实例、固定
    # 时区（中国，无 DST）部署，故不做 UTC/时区转换；若迁移到多时区或容器环境，需把这里与
    # _parse_scheduled_publish_time、_claim_due_scheduled_publish_task 一并改为 UTC 存储。
    return datetime.datetime.now().replace(microsecond=0)


def _parse_scheduled_publish_time(value):
    text = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            scheduled_at = datetime.datetime.strptime(text, fmt)
            break
        except ValueError:
            scheduled_at = None
    if not scheduled_at:
        raise ValueError("定时发布时间格式错误")
    now = _scheduled_now()
    if scheduled_at <= now:
        raise ValueError("定时发布时间必须晚于当前时间")
    if scheduled_at.date() > now.date() + datetime.timedelta(days=9):
        raise ValueError("定时发布时间只能选择今天起 10 个自然日内")
    return scheduled_at.replace(second=0, microsecond=0)


def _scheduled_task_targets(cursor, task_id):
    cursor.execute(
        "SELECT * FROM scheduled_publish_targets WHERE task_id = %s ORDER BY platform_type, id",
        (task_id,),
    )
    targets = []
    for row in cursor.fetchall():
        item = dict(row)
        try:
            settings = json.loads(item.get("settings") or "{}")
        except (TypeError, ValueError):
            settings = {}
        targets.append({
            "id": item.get("id"),
            "platformType": int(item.get("platform_type") or 0),
            "platformName": platform_name(item.get("platform_type")),
            "accountId": item.get("account_id"),
            "accountName": item.get("account_name") or "",
            "settings": settings,
            "status": item.get("status") or "queued",
            "message": clean_display_text(item.get("message")),
            "durationMs": int(item.get("duration_ms") or 0),
            "startedAt": item.get("started_at") or "",
            "finishedAt": item.get("finished_at") or "",
        })
    return targets


def _scheduled_task_payload(cursor, row):
    item = dict(row)
    targets = _scheduled_task_targets(cursor, item["id"])
    success_count = sum(target["status"] in {"confirmed", "reused"} for target in targets)
    failed_count = sum(target["status"] == "failed" for target in targets)
    unknown_count = sum(target["status"] == "uncertain" for target in targets)
    cursor.execute(
        "SELECT title, thumbnail, publish_draft FROM youtube_videos WHERE video_id = %s AND owner_user_id = %s",
        (item["video_id"], item.get("owner_user_id")),
    )
    video = cursor.fetchone()
    cursor.execute(
        "SELECT asset_id FROM file_records WHERE id = %s AND owner_user_id = %s",
        (item.get("material_id"), item.get("owner_user_id")),
    )
    material = cursor.fetchone()
    title = video["title"] if video else ""
    if video:
        try:
            draft = json.loads(video["publish_draft"] or "{}")
            title = draft.get("title") or title
        except (TypeError, ValueError):
            pass
    return {
        "id": item["id"],
        "videoId": item.get("video_id") or "",
        "materialId": item.get("material_id"),
        "assetId": (material or {}).get("asset_id") or "",
        "title": title or "未命名视频",
        "thumbnail": video["thumbnail"] if video else "",
        "scheduledAt": item.get("scheduled_at") or "",
        "status": item.get("status") or "scheduled",
        "overdue": bool(item.get("overdue") or 0),
        "message": clean_display_text(item.get("message")),
        "summary": {"success": success_count, "failed": failed_count, "unknown": unknown_count, "total": len(targets)},
        "targets": targets,
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "finishedAt": item.get("finished_at") or "",
        "canceledAt": item.get("canceled_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def create_scheduled_publish_task(data):
    data = data or {}
    scheduled_at = _parse_scheduled_publish_time(data.get("scheduledAt"))
    targets = normalize_publish_targets(data)
    owner_user_id = _current_account_owner_id()
    file_list, materials = _validate_publish_processed_files(data.get("fileList") or [], owner_user_id)
    if len(file_list) != 1:
        raise ValueError("定时发布一次只能选择一个视频")
    material = materials[0]
    video_id = material.get("source_video_id") or _material_source_video_id(material)
    if not video_id:
        raise ValueError("发布素材未绑定视频线索")
    accounts = _check_accounts_for_publish(targets)
    _resolve_publish_tags(targets, data.get("tags"), data.get("customTags"))
    validate_prepublish_guard_or_raise(data, file_list, targets, materials, check_agent=False)
    task_id = uuid.uuid4().hex
    now = _now_iso()
    video = _get_youtube_video_record(video_id, owner_user_id) or {}

    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        for target in targets:
            platform_type = int(target["platformType"])
            cursor.execute('''
            SELECT 1 FROM published_youtube_materials
            WHERE video_id = %s AND platform_type = %s AND owner_user_id = %s AND deleted_at IS NULL
              AND COALESCE(NULLIF(status, ''), 'confirmed') IN ('queued', 'running', 'confirmed', 'uncertain')
            LIMIT 1
            ''', (video_id, platform_type, owner_user_id))
            if cursor.fetchone():
                raise WorkflowConflictError(
                    f"该视频已发布、正在发布或已排期到{platform_name(platform_type)}，不能重复发布。",
                    "VF-PUBLISH-DUPLICATE-PLATFORM",
                    "PUBLISH_DUPLICATE_PLATFORM",
                    {"videoId": video_id, "platformType": platform_type},
                )
        risk_override_json = json.dumps(data.get("riskOverride") or {}, ensure_ascii=False)
        cursor.execute('''
        INSERT INTO scheduled_publish_tasks (
            id, video_id, material_id, file_path, scheduled_at, status, message, created_at, updated_at, risk_override, owner_user_id
        ) VALUES (%s, %s, %s, %s, %s, 'scheduled', '等待执行', %s, %s, %s, %s)
        ''', (task_id, video_id, material.get("id"), file_list[0], scheduled_at.strftime("%Y-%m-%d %H:%M:%S"), now, now, risk_override_json, owner_user_id))
        for target, account in zip(targets, accounts):
            settings = {
                "tags": target.get("tags") or [],
                "bilibiliTid": target.get("bilibiliTid"),
                "productLink": target.get("productLink") or "",
                "productTitle": target.get("productTitle") or "",
                "isDraft": bool(target.get("isDraft")),
            }
            cursor.execute('''
            INSERT INTO scheduled_publish_targets (
                task_id, platform_type, account_id, account_name, settings, status, message, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'queued', '等待执行', %s)
            ''', (task_id, target["platformType"], account["id"], account["name"], json.dumps(settings, ensure_ascii=False), now))
            publish_title = data.get("title") or video.get("title") or "YouTube 视频"
            _archive_published_material(
                cursor, material, video, target["platformName"], now,
                publish_title=publish_title, account_count=1, platform_type=target["platformType"],
                account_file=account["filePath"], publish_task_id=task_id, status="queued",
                message="等待定时发布", account_name=account["name"], account_id=account["id"],
            )
        conn.commit()
        cursor.execute(
            "SELECT * FROM scheduled_publish_tasks WHERE id = %s AND owner_user_id = %s",
            (task_id, owner_user_id),
        )
        return _scheduled_task_payload(cursor, cursor.fetchone())


def list_scheduled_publish_tasks(params=None, owner_user_id=None):
    params = params or {}
    page = _parse_positive_int(params.get("page"), 1, 1, 100000)
    page_size = _parse_positive_int(params.get("pageSize"), 20, 1, 100)
    status = str(params.get("status") or "all")
    keyword = str(params.get("keyword") or "").strip()
    clauses, values = [], []
    if owner_user_id is not None:
        clauses.append("task.owner_user_id = %s")
        values.append(owner_user_id)
    if status == "failed":
        clauses.append("task.status IN ('partial', 'failed')")
    elif status != "all":
        clauses.append("task.status = %s")
        values.append(status)
    if keyword:
        clauses.append("(video.title ILIKE %s OR task.video_id ILIKE %s)")
        values.extend([f"%{keyword}%", f"%{keyword}%"])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(f'''SELECT COUNT(*) AS total FROM scheduled_publish_tasks task
            LEFT JOIN youtube_videos video ON video.video_id = task.video_id AND video.owner_user_id = task.owner_user_id{where}''', values)
        total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(f'''SELECT task.* FROM scheduled_publish_tasks task
            LEFT JOIN youtube_videos video ON video.video_id = task.video_id AND video.owner_user_id = task.owner_user_id{where}
            ORDER BY task.scheduled_at DESC, task.created_at DESC LIMIT %s OFFSET %s''', values + [page_size, (page - 1) * page_size])
        items = [_scheduled_task_payload(cursor, row) for row in cursor.fetchall()]
        count_where = " WHERE owner_user_id = %s" if owner_user_id is not None else ""
        count_values = [owner_user_id] if owner_user_id is not None else []
        cursor.execute(f'''SELECT status, COUNT(*) AS total FROM scheduled_publish_tasks{count_where} GROUP BY status''', count_values)
        counts = {row["status"]: int(row["total"] or 0) for row in cursor.fetchall()}
        return {
            "items": items, "total": total, "page": page, "pageSize": page_size,
            "summary": {
                "all": sum(counts.values()), "pending": counts.get("scheduled", 0),
                "scheduled": counts.get("scheduled", 0),
                "queued": counts.get("queued", 0), "running": counts.get("running", 0), "success": counts.get("confirmed", 0),
                "failed": counts.get("failed", 0) + counts.get("partial", 0),
                "canceled": counts.get("cancelled", 0),
            },
        }


def cancel_scheduled_publish_task(task_id, owner_user_id=None):
    owner_user_id = owner_user_id or _current_account_owner_id()
    now = _now_iso()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("UPDATE scheduled_publish_tasks SET status = 'cancelled', message = '已取消', canceled_at = %s, updated_at = %s WHERE id = %s AND owner_user_id = %s AND status = 'scheduled'", (now, now, task_id, owner_user_id))
        if cursor.rowcount != 1:
            cursor.execute("SELECT status FROM scheduled_publish_tasks WHERE id = %s AND owner_user_id = %s", (task_id, owner_user_id))
            row = cursor.fetchone()
            if not row:
                raise LookupError("定时发布任务不存在")
            raise WorkflowConflictError("只有未执行任务可以取消。", "VF-SCHEDULED-PUBLISH-ACTIVE", "SCHEDULED_PUBLISH_ACTIVE", {"status": row["status"]})
        cursor.execute("UPDATE scheduled_publish_targets SET status = 'cancelled', message = '已取消', finished_at = %s, updated_at = %s WHERE task_id = %s AND status = 'queued'", (now, now, task_id))
        cursor.execute("UPDATE published_youtube_materials SET deleted_at = %s, updated_at = %s WHERE publish_task_id = %s AND owner_user_id = %s AND status = 'queued' AND deleted_at IS NULL", (now, now, task_id, owner_user_id))
        conn.commit()
        cursor.execute("SELECT * FROM scheduled_publish_tasks WHERE id = %s AND owner_user_id = %s", (task_id, owner_user_id))
        return _scheduled_task_payload(cursor, cursor.fetchone())


def _claim_due_scheduled_publish_task():
    now = _now_iso()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT id, scheduled_at FROM scheduled_publish_tasks WHERE status = 'scheduled' AND scheduled_at <= %s ORDER BY scheduled_at, created_at LIMIT 1", (now,))
        row = cursor.fetchone()
        if not row:
            return ""
        scheduled_at = datetime.datetime.fromisoformat(str(row["scheduled_at"]))
        current_minute = _scheduled_now().replace(second=0, microsecond=0)
        overdue = int(scheduled_at < current_minute)
        cursor.execute("UPDATE scheduled_publish_tasks SET status = 'running', overdue = %s, message = %s, started_at = %s, updated_at = %s WHERE id = %s AND status = 'scheduled'", (overdue, "逾期补发" if overdue else "正在执行", now, now, row["id"]))
        conn.commit()
        return row["id"] if cursor.rowcount == 1 else ""


def _scheduled_publish_content(video_id, owner_user_id):
    video = _get_youtube_video_record(video_id, owner_user_id) or {}
    draft = video.get("publishDraft") or {}
    return video, {
        "title": draft.get("title") or video.get("title") or "YouTube 视频",
        "description": draft.get("description") or "",
        "tags": draft.get("tags") or [],
    }


def _aggregate_scheduled_task_status(cursor, task_id):
    # 由 targets 状态派生 task 终态，避免任务表与目标表手动同步漂移。
    # 用下标取值，兼容按列名行模式或默认 tuple 的连接。
    cursor.execute("SELECT status FROM scheduled_publish_targets WHERE task_id = %s", (task_id,))
    statuses = [row[0] for row in cursor.fetchall()]
    if not statuses:
        return None
    success_count = sum(status in {"confirmed", "reused"} for status in statuses)
    failed_count = statuses.count("failed")
    unknown_count = statuses.count("uncertain")
    skipped_count = statuses.count("reused")
    status = aggregate_publish_status([{"status": item} for item in statuses])
    return status, success_count, failed_count, unknown_count, skipped_count


def _load_scheduled_task_payload(task_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduled_publish_tasks WHERE id = %s", (task_id,))
        row = cursor.fetchone()
        return _scheduled_task_payload(cursor, row) if row else None


def _revalidate_scheduled_publish(task, targets):
    """触发执行前重新校验（B1/B2/B4/B5）：创建任务后到触发之间，处理后文件、素材记录、
    平台占用状态、来源内容风险确认都可能变化。任一校验失败抛异常，由调用方标记任务失败。"""
    revalidate_targets = [{"platformType": target["platformType"]} for target in targets]
    try:
        risk_override = json.loads(task.get("risk_override") or "{}") or {}
    except (TypeError, ValueError):
        risk_override = {}
    # B2：底层处理后文件仍存在且已登记到素材库
    file_list, materials = _validate_publish_processed_files([task["file_path"]], task.get("owner_user_id"))
    material = materials[0]
    # B4：素材记录仍是创建时那条（未被删除/重建导致 id 漂移）
    if str(material.get("id") or "") != str(task.get("material_id") or ""):
        raise ValueError("底层素材已变更，请重新创建任务")
    # 平台目标被占用或发布结果待核验时，不允许重复提交。
    validate_prepublish_guard_or_raise(
        {"riskOverride": risk_override}, file_list, revalidate_targets, materials, check_agent=False
    )


def run_scheduled_publish_task(task_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduled_publish_tasks WHERE id = %s AND status = 'running'", (task_id,))
        task = cursor.fetchone()
        if not task:
            return None
        task = dict(task)
        targets = _scheduled_task_targets(cursor, task_id)
    try:
        _revalidate_scheduled_publish(task, targets)
    except Exception as exc:
        backend_logger.exception("scheduled publish revalidation failed : task_id = %s | error_type = %s", task_id, type(exc).__name__)
        fail_scheduled_publish_task(task_id, f"发布前校验未通过：{exc}")
        return _load_scheduled_task_payload(task_id)
    _, content = _scheduled_publish_content(task["video_id"], task.get("owner_user_id"))
    publish_tasks = []
    owner_user_id = None
    for target in targets:
        with _db_connect() as conn:
            conn.row_factory = True
            account = conn.execute(
                "SELECT * FROM user_info WHERE id = %s AND type = %s AND owner_user_id = %s",
                (target["accountId"], target["platformType"], task.get("owner_user_id")),
            ).fetchone()
        if not account or int(account["status"] or 0) != 1:
            fail_scheduled_publish_task(task_id, f"{target['platformName']}账号不存在或状态异常")
            return _load_scheduled_task_payload(task_id)
        settings = target["settings"]
        publish_target = {
            "platformType": target["platformType"], "platformName": target["platformName"],
            "accountFile": account["filePath"], "accountId": account["id"], "accountName": account["userName"],
            "ownerUserId": account["owner_user_id"], "tags": content["tags"], **settings,
        }
        publish_target["_resolvedTags"] = True
        data = {**content, "fileList": [task["file_path"]], "targets": [publish_target], "enableTimer": False, **settings}
        publish_tasks.extend(_build_publish_tasks(data, [publish_target], [task["file_path"]], publish_task_id=task_id))
        owner_user_id = account["owner_user_id"]
    try:
        dispatch_task = enqueue_publish_tasks(
            publish_tasks,
            source="scheduled",
            source_ref_id=task_id,
            owner_user_id=owner_user_id,
            publish_task_id=task_id,
        )
    except PublishQueueFullError as exc:
        now = _now_iso()
        with _db_connect() as conn:
            conn.execute(
                "UPDATE scheduled_publish_tasks SET status = 'scheduled', message = %s, updated_at = %s WHERE id = %s AND status = 'running'",
                (clean_display_text(str(exc)), now, task_id),
            )
        return _load_scheduled_task_payload(task_id)
    except Exception as exc:
        fail_scheduled_publish_task(task_id, str(exc))
        return _load_scheduled_task_payload(task_id)
    if dispatch_task.get("status") == "waiting_existing":
        now = _now_iso()
        with _db_connect() as conn:
            conn.execute(
                "UPDATE scheduled_publish_tasks SET status = 'waiting_existing', message = '等待已有发布任务完成', updated_at = %s WHERE id = %s AND status = 'running'",
                (now, task_id),
            )
        return _load_scheduled_task_payload(task_id)
    if dispatch_task.get("status") in {"reused", "uncertain"}:
        return _load_scheduled_task_payload(task_id)
    now = _now_iso()
    with _db_connect() as conn:
        conn.execute("UPDATE scheduled_publish_tasks SET status = 'queued', message = '已进入发布队列', updated_at = %s WHERE id = %s AND status = 'running'", (now, task_id))
    return _load_scheduled_task_payload(task_id)


def finish_scheduled_publish_dispatch(task_id, results, status, message):
    now = _now_iso()
    by_platform = {int(item.get("platformType") or 0): item for item in results or []}
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        for platform_type, result in by_platform.items():
            cursor.execute(
                "UPDATE scheduled_publish_targets SET status = %s, message = %s, duration_ms = %s, finished_at = %s, updated_at = %s WHERE task_id = %s AND platform_type = %s",
                (result.get("status") or "failed", clean_display_text(result.get("message")), int(result.get("durationMs") or 0), now, now, task_id, platform_type),
            )
        aggregated = _aggregate_scheduled_task_status(cursor, task_id)
        final_status = aggregated[0] if aggregated else status
        cursor.execute("UPDATE scheduled_publish_tasks SET status = %s, message = %s, finished_at = %s, updated_at = %s WHERE id = %s", (final_status, clean_display_text(message), now, now, task_id))


def _run_scheduled_publish_task_direct(task_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduled_publish_tasks WHERE id = %s AND status = 'running'", (task_id,))
        task = cursor.fetchone()
        if not task:
            return None
        task = dict(task)
        targets = _scheduled_task_targets(cursor, task_id)
    # B1/B2/B4/B5：触发前复查。失败则标记任务失败并返回，绝不用「创建后被改动的状态」上传。
    try:
        _revalidate_scheduled_publish(task, targets)
    except Exception as exc:
        backend_logger.exception(
            "scheduled publish revalidation failed : task_id = %s | error_type = %s",
            task_id, type(exc).__name__,
        )
        fail_scheduled_publish_task(task_id, f"触发前校验未通过：{exc}")
        return _load_scheduled_task_payload(task_id)
    video, content = _scheduled_publish_content(task["video_id"], task.get("owner_user_id"))
    for target in targets:
        started_at = _now_iso()
        account_file = ""
        account_name = target["accountName"]
        with _db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE scheduled_publish_targets SET status = 'running', message = '发布中', started_at = %s, updated_at = %s WHERE id = %s", (started_at, started_at, target["id"]))
        try:
            with _db_connect() as conn:
                conn.row_factory = True
                account = conn.execute("SELECT * FROM user_info WHERE id = %s AND type = %s AND owner_user_id = %s", (target["accountId"], target["platformType"], task.get("owner_user_id"))).fetchone()
            account_file = account["filePath"] if account else ""
            account_name = account["userName"] if account else account_name
            if not account or int(account["status"] or 0) != 1:
                raise RuntimeError(f"{target['platformName']}账号不存在或状态异常")
            settings = target["settings"]
            publish_target = {
                "platformType": target["platformType"], "platformName": target["platformName"],
                "accountFile": account["filePath"], "accountId": account["id"], "accountName": account["userName"],
                "ownerUserId": account["owner_user_id"],
                "tags": content["tags"], **settings,
            }
            publish_target["_resolvedTags"] = True
            data = {**content, "fileList": [task["file_path"]], "targets": [publish_target], "enableTimer": False, **settings}
            publish_task = _build_publish_tasks(data, [publish_target], [task["file_path"]], publish_task_id=task_id)[0]
            result = _execute_publish_target(publish_task)
        except Exception as exc:
            result = {"status": "failed", "message": str(exc), "durationMs": 0}
            try:
                _mark_published_materials(
                    [task["file_path"]], platform_type=target["platformType"], title=content["title"],
                    account_count=1, account_file=account_file, publish_task_id=task_id,
                    status="failed", message=str(exc), account_name=account_name,
                    account_id=target["accountId"],
                    owner_user_id=task.get("owner_user_id"),
                )
            except Exception as record_exc:
                backend_logger.exception(
                    "scheduled publish failure record update failed : task_id = %s | platform_type = %s | error_type = %s",
                    task_id, target["platformType"], type(record_exc).__name__,
                )
        finished_at = _now_iso()
        with _db_connect() as conn:
            conn.execute("UPDATE scheduled_publish_targets SET status = %s, message = %s, duration_ms = %s, finished_at = %s, updated_at = %s WHERE id = %s", (result["status"], clean_display_text(result.get("message")), int(result.get("durationMs") or 0), finished_at, finished_at, target["id"]))
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        aggregated = _aggregate_scheduled_task_status(cursor, task_id)
        if aggregated is None:
            status, success_count, failed_count, unknown_count, skipped_count = "failed", 0, 0, 0, 0
        else:
            status, success_count, failed_count, unknown_count, skipped_count = aggregated
        message = f"执行完成：成功 {success_count} 个平台，失败 {failed_count} 个平台，待核验 {unknown_count} 个平台，跳过 {skipped_count} 个平台"
        now = _now_iso()
        cursor.execute("UPDATE scheduled_publish_tasks SET status = %s, message = %s, finished_at = %s, updated_at = %s WHERE id = %s", (status, message, now, now, task_id))
        cursor.execute("SELECT * FROM scheduled_publish_tasks WHERE id = %s", (task_id,))
        return _scheduled_task_payload(cursor, cursor.fetchone())
