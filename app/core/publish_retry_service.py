"""失败发布目标的服务端重发。"""


def prepare_failed_publish_retry(publish_task_id):
    """校验失败目标并登记重发任务，供后台发布队列执行。"""
    task_id = str(publish_task_id or "").strip()
    if not task_id or task_id.startswith("legacy:"):
        raise ValueError("发布任务不存在或不支持重发")

    init_database_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM published_youtube_materials WHERE publish_task_id = ? AND deleted_at IS NULL ORDER BY id", (task_id,))
        records = [_row_to_published_material(row) for row in cursor.fetchall()]
        if not records:
            raise LookupError("原发布任务不存在")
        if any(record.get("retrySource") for record in records):
            raise ValueError("重发执行记录不能再次作为原任务重发")
        unknown_records = [record for record in records if record.get("status") == "unknown"]
        if unknown_records:
            raise WorkflowConflictError(
                "存在待核验的平台发布结果，请先核验平台状态并释放本地占位后再重发。",
                "VF-PUBLISH-RETRY-UNKNOWN",
                "PUBLISH_RETRY_UNKNOWN",
                {
                    "recordIds": [record.get("id") for record in unknown_records],
                    "publishTaskId": task_id,
                },
            )
        if any(record.get("status") in {"pending", "running", "canceled"} for record in records):
            raise WorkflowConflictError("运行中、待确认或已取消的任务不能重发。", "VF-PUBLISH-RETRY-INACTIVE", "PUBLISH_RETRY_INACTIVE", {})
        failed_records = [record for record in records if record.get("status") in {"failed", "timeout"}]
        if not failed_records:
            raise ValueError("原发布任务没有可重发的失败平台")

        source = records[0]
        cursor.execute("SELECT * FROM file_records WHERE id = ?", (source.get("materialId"),))
        material_row = cursor.fetchone()
        if not material_row:
            raise ValueError("原任务的成片素材不存在，无法重发")
        material = _row_to_material(material_row)
        file_path = material.get("file_path") or material.get("storage_key") or source.get("filePath")
        file_list, materials = _validate_publish_processed_files([file_path])

        targets = []
        for record in failed_records:
            cursor.execute("SELECT * FROM user_info WHERE type = ? AND filePath = ?", (record["platformType"], record["accountFile"]))
            account = cursor.fetchone()
            if not account or int(account["status"] or 0) != 1:
                raise ValueError(f"{record['platform']} 原账号不存在或状态异常，无法重发")
            targets.append({
                "platformType": record["platformType"],
                "platformName": record["platform"],
                "accountFile": account["filePath"],
                "accountId": account["id"],
                "accountName": account["userName"],
                "retryOfRecordId": record["id"],
            })

    _assert_publish_targets_available(materials[0], targets)
    video = _get_youtube_video_record(source.get("videoId")) or {}
    draft = video.get("publishDraft") or {}
    data = {
        "title": _strip_publish_title_meta(source.get("publishTitle")) or draft.get("title") or source.get("title") or "YouTube 视频",
        "description": draft.get("description") or "",
        "tags": draft.get("tags") or [],
        "fileList": file_list,
        "targets": targets,
        "retryOfTaskId": task_id,
        "retrySource": "failed_target",
    }
    validate_prepublish_guard_or_raise(data, file_list, targets, materials, check_agent=False)
    retry_task_id = uuid.uuid4().hex
    tasks = _build_publish_tasks(data, targets, file_list, publish_task_id=retry_task_id)
    _mark_publish_tasks_pending(tasks)
    return {
        "publishTaskId": retry_task_id,
        "retryOfTaskId": task_id,
        "tasks": tasks,
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
            retry_of_task_id=task.get("retryOfTaskId") or "",
            retry_of_record_id=task.get("retryOfRecordId"),
            retry_source=task.get("retrySource") or "",
        )
