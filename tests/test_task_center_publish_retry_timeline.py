import datetime

from app.backend.runtime import create_backend_module


def _retry_progress(*statuses):
    attempts = [{
        "publishTaskId": "workflow:job-1",
        "isRetry": False,
        "targets": [{"platform_type": 2, "status": "failed", "message": "首次发布失败"}],
    }]
    for sequence, status in enumerate(statuses, start=1):
        attempts.append({
            "publishTaskId": f"retry-{sequence}",
            "isRetry": True,
            "sequence": sequence,
            "createdAt": f"2026-08-24T10:0{sequence}:00",
            "finishedAt": f"2026-08-24T10:0{sequence}:10",
            "targets": [{
                "platform_type": 2,
                "status": status,
                "message": f"第 {sequence} 次重试 {status}",
                "started_at": f"2026-08-24T10:0{sequence}:00",
                "finished_at": f"2026-08-24T10:0{sequence}:10",
            }],
        })
    return {
        "status": statuses[-1] if statuses else "failed",
        "targets": attempts[-1]["targets"],
        "attempts": attempts,
        "retried": bool(statuses),
        "finishedAt": attempts[-1].get("finishedAt", ""),
        "message": "视频号已通过重试发布" if statuses and statuses[-1] == "confirmed" else "视频号发布失败",
        "total": 1,
        "confirmed": int(bool(statuses) and statuses[-1] == "confirmed"),
        "reused": 0,
        "completed": 1,
    }


def _publish_job(progress):
    return {
        "id": "job-1",
        "status": "partial",
        "step": "publish",
        "title": "retry timeline",
        "video_id": "video-1",
        "owner_user_id": 1,
        "created_at": datetime.datetime(2026, 8, 24, 10, 0),
        "updated_at": datetime.datetime(2026, 8, 24, 10, 2),
        "publish_to_tencent": True,
        "tencent_account": "tencent.json",
        "publishProgress": progress,
    }


def test_task_flow_keeps_failed_publish_and_appends_retry_attempts():
    backend = create_backend_module("test_task_center_publish_retry_timeline")
    job = _publish_job(_retry_progress("failed", "confirmed"))
    events = [{
        "stage": "publish", "label": "发布", "status": "partial", "message": "部分平台发布失败",
        "startedAt": "2026-08-24T10:00:00", "endedAt": "2026-08-24T10:02:00", "durationSeconds": 120,
    }]
    materials = [{"platform_type": 2, "status": "failed", "publish_task_id": "workflow:job-1"}]

    graph = backend._task_publish_graph(job, events, materials)

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["publish-2"]["status"] == "failed"
    assert nodes["publish-2-retry-1"]["status"] == "failed"
    assert nodes["publish-2-retry-2"]["status"] == "confirmed"
    assert [edge["label"] for edge in graph["edges"] if edge.get("label")] == ["重试发布", "重试发布"]

    item = backend._task_item(job, events, materials)

    assert item["status"] == "success"
    assert item["statusLabel"] == "重试后完成"
    assert item["errorReason"] == ""


def test_retrying_publish_stays_active_until_the_latest_attempt_finishes():
    backend = create_backend_module("test_task_center_retry_timeline_active")

    progress = backend._task_publish_progress_from_attempts([
        {
            "publishTaskId": "workflow:job-1",
            "isRetry": False,
            "status": "partial",
            "targets": [
                {"platform_type": 3, "status": "confirmed"},
                {"platform_type": 2, "status": "failed"},
            ],
        },
        {
            "publishTaskId": "retry-1",
            "isRetry": True,
            "sequence": 1,
            "status": "running",
            "targets": [{"platform_type": 2, "status": "running"}],
        },
    ])

    assert progress["status"] == "running"
    assert progress["retried"] is True
    assert {target["platform_type"]: target["status"] for target in progress["targets"]} == {3: "confirmed", 2: "running"}
