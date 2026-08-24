"""失败发布目标的服务端重发。"""


def _select_failed_publish_records(failed_records, target_record_ids=None):
    """Return retry targets selected from the current task's failed records."""
    failed_records = list(failed_records or [])
    if target_record_ids is None:
        return failed_records
    if not isinstance(target_record_ids, list) or not target_record_ids:
        raise ValueError("请至少选择一个失败平台重新发布")
    if any(isinstance(record_id, bool) or not isinstance(record_id, int) for record_id in target_record_ids):
        raise ValueError("重发平台记录格式无效")
    if len(set(target_record_ids)) != len(target_record_ids):
        raise ValueError("重发平台不能重复选择")

    records_by_id = {int(record.get("id") or 0): record for record in failed_records}
    selected_records = []
    for record_id in target_record_ids:
        record = records_by_id.get(record_id)
        if not record:
            raise ValueError("所选平台不属于当前任务的可重发失败项")
        selected_records.append(record)
    return selected_records


def _retry_publish_account(cursor, record, owner_user_id):
    platform_type = int(record["platformType"] or 0)
    account_id = record.get("accountId")
    if account_id:
        cursor.execute(
            "SELECT * FROM user_info WHERE id = %s AND type = %s AND owner_user_id = %s",
            (int(account_id), platform_type, owner_user_id),
        )
        account = cursor.fetchone()
        if account:
            return account
    cursor.execute(
        "SELECT * FROM user_info WHERE type = %s AND filePath = %s AND owner_user_id = %s",
        (platform_type, record["accountFile"], owner_user_id),
    )
    return cursor.fetchone()


def prepare_failed_publish_retry(
    publish_task_id,
    target_record_ids=None,
    owner_user_id=None,
    risk_override=None,
):
    """校验失败目标并登记重发任务，供后台发布队列执行。"""
    task_id = str(publish_task_id or "").strip()
    if not task_id or task_id.startswith("legacy:"):
        raise ValueError("发布任务不存在或不支持重发")
    if risk_override is not None and not isinstance(risk_override, dict):
        raise ValueError("重发风险确认格式无效")

    owner_user_id = owner_user_id or _current_account_owner_id()
    init_database_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM published_youtube_materials WHERE publish_task_id = %s AND owner_user_id = %s AND deleted_at IS NULL ORDER BY id",
            (task_id, owner_user_id),
        )
        records = [_row_to_published_material(row) for row in cursor.fetchall()]
        if not records:
            raise LookupError("原发布任务不存在")
        if any(record.get("retrySource") for record in records):
            raise ValueError("重发执行记录不能再次作为原任务重发")
        uncertain_records = [record for record in records if record.get("status") == "uncertain"]
        if uncertain_records:
            raise WorkflowConflictError(
                "存在待核验的平台发布结果，请先核验平台状态并释放本地占位后再重发。",
                "VF-PUBLISH-RETRY-UNKNOWN",
                "PUBLISH_RETRY_UNKNOWN",
                {
                    "recordIds": [record.get("id") for record in uncertain_records],
                    "publishTaskId": task_id,
                },
            )
        if any(record.get("status") in {"queued", "running", "cancelled"} for record in records):
            raise WorkflowConflictError("运行中、待确认或已取消的任务不能重发。", "VF-PUBLISH-RETRY-INACTIVE", "PUBLISH_RETRY_INACTIVE", {})
        failed_records = [record for record in records if record.get("status") == "failed"]
        if not failed_records:
            raise ValueError("原发布任务没有可重发的失败平台")
        failed_records = _select_failed_publish_records(failed_records, target_record_ids)
        cursor.execute("SELECT platform_type, settings FROM publish_dispatch_targets WHERE job_id = %s", (task_id,))
        stored_tags_by_platform = {}
        for target_row in cursor.fetchall():
            try:
                settings = json.loads(target_row["settings"] or "{}")
            except (TypeError, ValueError):
                settings = {}
            if isinstance(settings.get("tags"), list):
                stored_tags_by_platform[int(target_row["platform_type"] or 0)] = list(settings["tags"])

        source = records[0]
        cursor.execute(
            "SELECT * FROM file_records WHERE id = %s AND owner_user_id = %s",
            (source.get("materialId"), owner_user_id),
        )
        material_row = cursor.fetchone()
        if not material_row:
            raise ValueError("原任务的成片素材不存在，无法重发")
        material = _row_to_material(material_row)
        file_path = material.get("file_path") or material.get("storage_key") or source.get("filePath")
        file_list, materials = _validate_publish_processed_files([file_path], owner_user_id)

        targets = []
        for record in failed_records:
            platform_type = int(record["platformType"] or 0)
            account = _retry_publish_account(cursor, record, owner_user_id)
            if not account or int(account["status"] or 0) != 1:
                raise ValueError(f"{record['platform']} 原账号不存在或状态异常，无法重发")
            target = {
                "platformType": platform_type,
                "platformName": record["platform"],
                "accountFile": account["filePath"],
                "accountId": account["id"],
                "accountName": account["userName"],
                "ownerUserId": account["owner_user_id"],
                "retryOfRecordId": record["id"],
            }
            if platform_type in stored_tags_by_platform:
                target["tags"] = stored_tags_by_platform[platform_type]
                target["_resolvedTags"] = True
            else:
                target["_tagsProvided"] = False
            targets.append(target)

    _assert_publish_targets_available(materials[0], targets)
    video = _get_youtube_video_record(source.get("videoId"), owner_user_id) or {}
    draft = video.get("publishDraft") or {}
    data = {
        "title": _strip_publish_title_meta(source.get("publishTitle")) or draft.get("title") or source.get("title") or "YouTube 视频",
        "description": draft.get("description") or "",
        "tags": draft.get("tags") or [],
        "fileList": file_list,
        "targets": targets,
        "retryOfTaskId": task_id,
        "retrySource": "failed_target",
        "riskOverride": risk_override or {},
    }
    validate_prepublish_guard_or_raise(data, file_list, targets, materials, check_agent=False)
    retry_task_id = uuid.uuid4().hex
    tasks = _build_publish_tasks(data, targets, file_list, publish_task_id=retry_task_id)
    queued = enqueue_publish_tasks(
        tasks,
        source="retry",
        source_ref_id=task_id,
        owner_user_id=owner_user_id,
        publish_task_id=retry_task_id,
    )
    return {
        "publishTaskId": retry_task_id,
        "retryOfTaskId": task_id,
        "status": queued["status"],
        "targets": queued["targets"],
    }


def run_failed_publish_retry(tasks):
    return _summarize_publish_results(_run_publish_tasks(tasks))


def fail_failed_publish_retry_submission(tasks, message):
    for task in tasks:
        _mark_published_materials(
            task["fileList"],
            platform_type=task["platformType"],
            title=f"{task['title']}; description={task['description']}" if task["description"] else task["title"],
            account_count=1,
            account_file=task["accountFile"],
            publish_task_id=task.get("publishTaskId") or "",
            status="failed",
            message=message,
            account_name=task.get("accountName") or "",
            account_id=task.get("accountId"),
            retry_of_task_id=task.get("retryOfTaskId") or "",
            retry_of_record_id=task.get("retryOfRecordId"),
            retry_source=task.get("retrySource") or "",
            owner_user_id=task.get("ownerUserId"),
        )
