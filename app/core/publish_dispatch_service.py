"""Durable local publish queue shared by every publish entry point."""

import json
import threading
import uuid
from pathlib import Path


class PublishQueueFullError(RuntimeError):
    error_code = "VF-PUBLISH-QUEUE-FULL"


_publish_dispatch_stop = threading.Event()
_publish_dispatch_wakeup = threading.Event()
_publish_dispatch_thread = None
_publish_dispatch_start_lock = threading.Lock()


def _publish_dispatch_payload(tasks):
    return {"tasks": [{
        **{key: value for key, value in task.items() if key not in {"absoluteFiles"}},
        "absoluteFiles": [str(path) for path in task.get("absoluteFiles") or []],
    } for task in tasks]}


def _publish_dispatch_tasks(payload):
    tasks = []
    for raw_task in (payload or {}).get("tasks") or []:
        task = dict(raw_task or {})
        task["absoluteFiles"] = [Path(path) for path in task.get("absoluteFiles") or []]
        tasks.append(task)
    return tasks


def _publish_dispatch_status(results):
    statuses = [str(item.get("status") or "failed") for item in results]
    if any(status == "unknown" for status in statuses):
        return "unknown"
    if statuses and all(status == "success" for status in statuses):
        return "success"
    if any(status == "success" for status in statuses):
        return "partial"
    return "failed"


def _publish_dispatch_progress(targets):
    counts = {"pending": 0, "running": 0, "success": 0, "failed": 0, "unknown": 0}
    for target in targets or []:
        status = str(target.get("status") or "pending")
        if status in {"timeout", "canceled"}:
            status = "failed"
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    completed = counts["success"] + counts["failed"] + counts["unknown"]
    return {
        "total": total,
        **counts,
        "completed": completed,
        "percentage": round(completed * 100 / total) if total else 0,
    }


def _publish_dispatch_message(results):
    if not results:
        return "No publish targets were executed."
    failed = [item.get("platformName") or "unknown" for item in results if item.get("status") != "success"]
    return "Publish completed." if not failed else "Publish completed with unresolved targets : " + ", ".join(failed)


def _publish_dispatch_row(cursor, row):
    if not row:
        return None
    item = dict(row)
    cursor.execute("SELECT * FROM publish_dispatch_targets WHERE job_id = ? ORDER BY platform_type, id", (item["id"],))
    targets = []
    for target_row in cursor.fetchall():
        target = dict(target_row)
        try:
            settings = json.loads(target.get("settings") or "{}")
        except (TypeError, ValueError):
            settings = {}
        targets.append({
            "platformType": int(target.get("platform_type") or 0),
            "accountId": target.get("account_id"),
            "status": target.get("status") or "pending",
            "message": clean_display_text(target.get("message")),
            "durationMs": int(target.get("duration_ms") or 0),
            "settings": settings,
            "startedAt": target.get("started_at") or "",
            "finishedAt": target.get("finished_at") or "",
        })
    return {
        "publishTaskId": item["id"],
        "source": item.get("source") or "",
        "sourceRefId": item.get("source_ref_id") or "",
        "videoId": item.get("video_id") or "",
        "materialId": item.get("material_id"),
        "status": item.get("status") or "pending",
        "message": clean_display_text(item.get("message")),
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "finishedAt": item.get("finished_at") or "",
        "updatedAt": item.get("updated_at") or "",
        "targets": targets,
    }


def get_publish_dispatch_job(job_id, owner_user_id=None):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        query = "SELECT * FROM publish_dispatch_jobs WHERE id = ?"
        values = [str(job_id or "")]
        if owner_user_id is not None:
            query += " AND owner_user_id = ?"
            values.append(int(owner_user_id))
        cursor.execute(query, values)
        return _publish_dispatch_row(cursor, cursor.fetchone())


def _publish_queue_limit():
    return int(WORKFLOW_MAX_PUBLISH_JOBS) + int(WORKFLOW_MAX_PUBLISH_QUEUED_JOBS)


def enqueue_publish_tasks(tasks, *, source, source_ref_id="", owner_user_id=None, publish_task_id=""):
    task_list = list(tasks or [])
    if not task_list:
        raise ValueError("No publish targets were provided.")
    job_id = str(publish_task_id or uuid.uuid4().hex)
    for task in task_list:
        task["publishTaskId"] = job_id
    first_task = task_list[0]
    file_path = (first_task.get("fileList") or [""])[0]
    init_database_tables()
    now = _now_iso()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        cursor.execute("LOCK TABLE publish_dispatch_jobs IN SHARE ROW EXCLUSIVE MODE")
        queue_conditions = ["status IN ('pending', 'running')"]
        queue_values = []
        if owner_user_id is not None:
            queue_conditions.append("owner_user_id = ?")
            queue_values.append(int(owner_user_id))
        cursor.execute(
            "SELECT COUNT(*) AS total FROM publish_dispatch_jobs WHERE " + " AND ".join(queue_conditions),
            queue_values,
        )
        if int(cursor.fetchone()["total"] or 0) >= _publish_queue_limit():
            raise PublishQueueFullError("Publish queue is full. Try again after an active publish finishes.")
        cursor.execute("SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?", (file_path, file_path))
        material_row = cursor.fetchone()
        if not material_row:
            raise ValueError("Publish material is no longer available.")
        material = _row_to_material(material_row)
        video_id = material.get("source_video_id") or _material_source_video_id(material)
        if not video_id:
            raise ValueError("Publish material is not linked to a source video.")
        cursor.execute(
            "INSERT INTO publish_dispatch_jobs (id, source, source_ref_id, owner_user_id, video_id, material_id, payload, status, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (job_id, source, str(source_ref_id or ""), owner_user_id, video_id, material.get("id"), json.dumps(_publish_dispatch_payload(task_list), ensure_ascii=False, default=str), "Queued for publish.", now, now),
        )
        reserve_publish_tasks_pending(task_list, cursor=cursor)
        for task in task_list:
            settings = {
                "accountName": task.get("accountName") or "",
                "tags": task.get("tags") or [],
                "bilibiliTid": task.get("bilibiliTid"),
                "isDraft": bool(task.get("isDraft")),
            }
            cursor.execute(
                "INSERT INTO publish_dispatch_targets (job_id, platform_type, account_id, settings, status, message, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (job_id, int(task.get("platformType") or 0), task.get("accountId"), json.dumps(settings, ensure_ascii=False), "Queued for publish.", now),
            )
        conn.commit()
        cursor.execute("SELECT * FROM publish_dispatch_jobs WHERE id = ?", (job_id,))
        result = _publish_dispatch_row(cursor, cursor.fetchone())
    backend_logger.info("publish queued : publish_task_id = %s | source = %s", job_id, source)
    _publish_dispatch_wakeup.set()
    return result


def _claim_publish_dispatch_job():
    now = _now_iso()
    claimed_job_id = ""
    workflow_update = None
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        cursor.execute("SELECT COUNT(*) AS total FROM publish_dispatch_jobs WHERE status = 'running'")
        if int(cursor.fetchone()["total"] or 0) >= int(WORKFLOW_MAX_PUBLISH_JOBS):
            return ""
        cursor.execute("SELECT * FROM publish_dispatch_jobs WHERE status = 'pending' ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED")
        row = cursor.fetchone()
        if not row:
            return ""
        cursor.execute("UPDATE publish_dispatch_jobs SET status = 'running', message = ?, started_at = ?, updated_at = ? WHERE id = ? AND status = 'pending'", ("Publish is running.", now, now, row["id"]))
        if cursor.rowcount != 1:
            return ""
        if row.get("source") == "workflow":
            cursor.execute("SELECT COUNT(*) AS total FROM publish_dispatch_targets WHERE job_id = ?", (row["id"],))
            total = int(cursor.fetchone()["total"] or 0)
            workflow_update = (row["source_ref_id"], row.get("video_id") or "", total)
        claimed_job_id = row["id"]
    if workflow_update:
        workflow_job_id, video_id, total = workflow_update
        update_youtube_workflow_job(
            workflow_job_id,
            status="running",
            step="publish",
            message=f"正在发布 {total} 个平台",
            progress=97,
            speed="",
            eta="",
        )
        backend_logger.info(
            "publish workflow queue claimed : videoId = %s | jobId = %s | publishTaskId = %s | status = running",
            video_id,
            workflow_job_id,
            claimed_job_id,
        )
    return claimed_job_id


def _publish_dispatch_target_started(job_id, platform_type):
    now = _now_iso()
    with _db_connect() as conn:
        conn.execute(
            "UPDATE publish_dispatch_targets SET status = 'running', message = ?, started_at = ?, updated_at = ? WHERE job_id = ? AND platform_type = ? AND status = 'pending'",
            ("正在发布", now, now, job_id, int(platform_type)),
        )


def _publish_dispatch_target_finished(job_id, result):
    now = _now_iso()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE publish_dispatch_targets SET status = ?, message = ?, duration_ms = ?, finished_at = ?, updated_at = ? WHERE job_id = ? AND platform_type = ?",
            (result.get("status") or "failed", result.get("message") or "", int(result.get("durationMs") or 0), now, now, job_id, int(result.get("platformType") or 0)),
        )
        cursor.execute("SELECT status FROM publish_dispatch_targets WHERE job_id = ?", (job_id,))
        progress = _publish_dispatch_progress([dict(row) for row in cursor.fetchall()])
        cursor.execute("SELECT source, source_ref_id FROM publish_dispatch_jobs WHERE id = ?", (job_id,))
        job = cursor.fetchone()
    if job and job["source"] == "workflow":
        update_youtube_workflow_job(
            job["source_ref_id"],
            status="running",
            step="publish",
            message=f"发布中 {progress['completed']} / {progress['total']}",
            progress=round(97 + (progress["completed"] / progress["total"] * 3), 1) if progress["total"] else 97,
            speed="",
            eta="",
        )


def _finish_dispatch_source(job, results, status, message):
    source = job.get("source") or ""
    source_ref_id = job.get("source_ref_id") or ""
    if source == "scheduled":
        finish_scheduled_publish_dispatch(source_ref_id, results, status, message)
    elif source == "workflow":
        workflow_status = "success" if status == "success" else "failed"
        update_youtube_workflow_job(
            source_ref_id,
            status=workflow_status,
            step="done" if workflow_status == "success" else "publish",
            message=message,
            progress=100,
            speed="",
            eta="",
        )
        finish_open_workflow_events(source_ref_id, workflow_status, message)
        if workflow_status == "success":
            update_youtube_video_artifacts(job.get("video_id") or "", publish_status=1)


def run_publish_dispatch_job(job_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM publish_dispatch_jobs WHERE id = ? AND status = 'running'", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        job = dict(row)
    try:
        payload = json.loads(job.get("payload") or "{}")
        tasks = _publish_dispatch_tasks(payload)
        results = _run_publish_tasks(
            tasks,
            before_task=lambda task, _index, _total: _publish_dispatch_target_started(job_id, task.get("platformType")),
            after_task=lambda _task, result, _index, _total: _publish_dispatch_target_finished(job_id, result),
        )
        status = _publish_dispatch_status(results)
        message = _publish_dispatch_message(results)
    except Exception as exc:
        backend_logger.exception("publish dispatch failed : publish_task_id = %s | error_type = %s", job_id, type(exc).__name__)
        results = []
        status = "failed"
        message = str(exc)
    now = _now_iso()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE publish_dispatch_jobs SET status = ?, message = ?, finished_at = ?, updated_at = ? WHERE id = ?", (status, message, now, now, job_id))
        for result in results:
            cursor.execute(
                "UPDATE publish_dispatch_targets SET status = ?, message = ?, duration_ms = ?, finished_at = ?, updated_at = ? WHERE job_id = ? AND platform_type = ?",
                (result.get("status") or "failed", result.get("message") or "", int(result.get("durationMs") or 0), now, now, job_id, int(result.get("platformType") or 0)),
            )
    _finish_dispatch_source(job, results, status, message)
    _publish_dispatch_wakeup.set()
    return get_publish_dispatch_job(job_id)


def _publish_dispatch_loop():
    while not _publish_dispatch_stop.is_set():
        submitted = False
        while not _publish_dispatch_stop.is_set():
            job_id = _claim_publish_dispatch_job()
            if not job_id:
                break
            try:
                _submit_background_task("publish", run_publish_dispatch_job, job_id)
                submitted = True
            except Exception as exc:
                now = _now_iso()
                with _db_connect() as conn:
                    conn.execute("UPDATE publish_dispatch_jobs SET status = 'pending', message = ?, started_at = NULL, updated_at = ? WHERE id = ? AND status = 'running'", (f"Queue submit failed : {exc}", now, job_id))
                    conn.execute("UPDATE publish_dispatch_targets SET status = 'pending', message = ?, started_at = NULL, updated_at = ? WHERE job_id = ? AND status = 'running'", ("Queued for publish.", now, job_id))
                queued_job = get_publish_dispatch_job(job_id)
                if queued_job and queued_job.get("source") == "workflow":
                    update_youtube_workflow_job(
                        queued_job.get("sourceRefId"),
                        status="waiting_publish",
                        step="publish",
                        message="发布任务已重新排队",
                        progress=97,
                        speed="",
                        eta="",
                    )
                break
        if not submitted:
            _publish_dispatch_wakeup.wait(1)
            _publish_dispatch_wakeup.clear()


def recover_interrupted_publish_dispatch_jobs():
    now = _now_iso()
    message = "Backend interrupted the publish process. Verify the platform before retrying."
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM publish_dispatch_jobs WHERE status = 'running'")
        recovered_jobs = [dict(row) for row in cursor.fetchall()]
        job_ids = [row["id"] for row in recovered_jobs]
        if recovered_jobs:
            cursor.execute("UPDATE publish_dispatch_jobs SET status = 'unknown', message = ?, finished_at = ?, updated_at = ? WHERE status = 'running'", (message, now, now))
            cursor.execute("UPDATE publish_dispatch_targets SET status = 'unknown', message = ?, finished_at = ?, updated_at = ? WHERE status = 'running'", (message, now, now))
            marks = ",".join("?" for _ in job_ids)
            cursor.execute(
                f"UPDATE published_youtube_materials SET status = 'unknown', message = ?, updated_at = ? WHERE publish_task_id IN ({marks})",
                (message, now, *job_ids),
            )
        _reconcile_publish_material_records(cursor)
    for job in recovered_jobs:
        _finish_dispatch_source(job, [], "unknown", message)
        backend_logger.warning(
            "publish dispatch recovered : videoId = %s | jobId = %s | publishTaskId = %s | status = unknown | reason = backend_interrupted",
            job.get("video_id") or "",
            job.get("source_ref_id") or "",
            job.get("id") or "",
        )
    return job_ids


def start_publish_dispatcher():
    global _publish_dispatch_thread
    with _publish_dispatch_start_lock:
        if _publish_dispatch_thread and _publish_dispatch_thread.is_alive():
            return
        recover_interrupted_publish_dispatch_jobs()
        _publish_dispatch_stop.clear()
        _publish_dispatch_thread = threading.Thread(target=_publish_dispatch_loop, name="vidferry-publish-dispatch", daemon=True)
        _publish_dispatch_thread.start()
        _publish_dispatch_wakeup.set()


def stop_publish_dispatcher():
    _publish_dispatch_stop.set()
    _publish_dispatch_wakeup.set()
    terminate_inflight_publish_processes()
    if _publish_dispatch_thread and _publish_dispatch_thread.is_alive():
        _publish_dispatch_thread.join(timeout=2)
