from contextlib import contextmanager
from datetime import datetime, timedelta

from app.backend.runtime import create_backend_module


def test_task_center_active_only_loads_active_jobs():
    backend = create_backend_module()
    calls = []
    backend._task_acknowledgements = lambda _user_id: {}
    backend._task_load = lambda job_id=None, active_only=False, **_kwargs: calls.append((job_id, active_only)) or []

    assert backend.list_task_center(1, active_only=True)["items"] == []
    assert calls == [(None, True)]


def test_waiting_publish_is_an_active_publish_task():
    backend = create_backend_module()
    job = {
        "id": "job-publish",
        "video_id": "video-1",
        "owner_user_id": 1,
        "status": "waiting_publish",
        "step": "publish",
        "operation": "process",
        "title": "publish title",
        "updated_at": "2026-08-11 23:04:00",
        "created_at": "2026-08-11 23:04:00",
        "publish_to_douyin": 1,
        "account": "creator",
    }
    backend._task_acknowledgements = lambda _user_id: {}
    backend._task_load = lambda **_kwargs: [(job, [], [])]

    result = backend.list_task_center(1, active_only=True)

    assert result["summary"]["activeCount"] == 1
    assert result["groups"]["active"][0]["status"] == "waiting_publish"
    assert result["groups"]["active"][0]["scope"] == "publish"


def test_task_center_keeps_only_the_latest_task_for_each_video():
    backend = create_backend_module()
    now = datetime.now()
    latest_updated = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    latest_created = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    older_updated = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    older_created = (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    latest_job = {
        "id": "job-latest", "video_id": "video-1", "owner_user_id": 1,
        "status": "success", "step": "done", "operation": "process",
        "title": "latest title", "updated_at": latest_updated, "created_at": latest_created,
    }
    older_job = {
        "id": "job-older", "video_id": "video-1", "owner_user_id": 1,
        "status": "failed", "step": "failed", "operation": "process",
        "title": "older title", "updated_at": older_updated, "created_at": older_created,
    }
    other_video_job = {
        "id": "job-other", "video_id": "video-2", "owner_user_id": 1,
        "status": "failed", "step": "failed", "operation": "process",
        "title": "other title", "updated_at": latest_updated, "created_at": latest_created,
    }
    events = [{"stage": "publish", "status": "success", "label": "发布", "message": "", "startedAt": "", "endedAt": "", "durationSeconds": 0}]
    rows = [(latest_job, events, []), (other_video_job, events, []), (older_job, events, [])]
    backend._task_acknowledgements = lambda _user_id: {}
    backend._task_load = lambda **_kwargs: rows

    result = backend.list_task_center(1)

    assert [item["jobId"] for item in result["items"]] == ["job-latest", "job-other"]


def test_all_task_center_keeps_each_historical_attempt():
    backend = create_backend_module()
    jobs = [
        {"id": "job-latest", "video_id": "video-1", "owner_user_id": 1, "status": "success", "step": "done", "operation": "process", "title": "latest title"},
        {"id": "job-older", "video_id": "video-1", "owner_user_id": 1, "status": "failed", "step": "failed", "operation": "process", "title": "older title"},
    ]
    events = [{"stage": "publish", "status": "success", "label": "发布", "message": "", "startedAt": "", "endedAt": "", "durationSeconds": 0}]
    backend._task_acknowledgements = lambda _user_id: {}
    backend._task_load = lambda **_kwargs: ([(job, events, []) for job in jobs], 2, {})

    result = backend.list_all_task_center(1)

    assert [item["jobId"] for item in result["items"]] == ["job-latest", "job-older"]


def test_publish_dispatch_terminal_status_replaces_stale_workflow_stage():
    backend = create_backend_module()
    job = {
        "id": "job-publish", "video_id": "video-1", "owner_user_id": 1,
        "status": "waiting_publish", "step": "publish", "operation": "process",
        "title": "publish title", "updated_at": "2026-08-18 12:00:00", "created_at": "2026-08-18 11:00:00",
        "publishProgress": {"status": "confirmed", "completed": 4, "total": 4, "message": "四个平台已完成"},
    }
    events = [{"stage": "publish", "status": "running", "label": "发布", "message": "发布中", "startedAt": "", "endedAt": "", "durationSeconds": 0}]

    result = backend._task_item(job, events, [])

    assert result["status"] == "success"
    assert result["currentStage"] == "发布完成 4 / 4"
    assert result["finishedAt"] == "2026-08-18T12:00:00+08:00"


def test_task_center_success_retention_is_four_hours_and_problem_tasks_are_acknowledgeable():
    backend = create_backend_module()
    events = [{"stage": "publish", "status": "success", "label": "发布", "message": "", "startedAt": "", "endedAt": "", "durationSeconds": 0}]
    success = backend._task_item({
        "id": "job-success", "video_id": "video-success", "owner_user_id": 1,
        "status": "success", "step": "done", "operation": "process",
        "title": "success", "updated_at": "2026-08-18 12:00:00", "created_at": "2026-08-18 11:00:00",
    }, events, [])

    assert success["expiresAt"] == "2026-08-18T16:00:00+08:00"
    for status in ("partial", "needs_verification", "failed", "abnormal", "cancelled"):
        item = backend._task_item({
            "id": f"job-{status}", "video_id": f"video-{status}", "owner_user_id": 1,
            "status": status, "step": "publish", "operation": "process", "title": status,
            "updated_at": "2026-08-18 12:00:00", "created_at": "2026-08-18 11:00:00",
        }, events, [])
        assert item["canAcknowledge"] is True


def test_task_center_keeps_same_video_id_data_scoped_to_each_owner(monkeypatch):
    backend = create_backend_module()
    jobs = [
        {"id": "job-1", "owner_user_id": 1, "video_id": "same-video"},
        {"id": "job-2", "owner_user_id": 2, "video_id": "same-video"},
    ]

    class Cursor:
        def execute(self, sql, params=()):
            if "FROM youtube_workflow_jobs" in sql:
                self.rows = jobs
            elif "FROM youtube_workflow_events WHERE job_id" in sql:
                self.rows = []
            elif "SELECT owner_user_id, video_id, metadata" in sql:
                assert params == [1, "same-video", 2, "same-video"]
                self.rows = [
                    {"owner_user_id": 1, "video_id": "same-video", "metadata": '{"sourceTitleZh":"用户一标题"}'},
                    {"owner_user_id": 2, "video_id": "same-video", "metadata": '{"sourceTitleZh":"用户二标题"}'},
                ]
            elif "FROM published_youtube_materials" in sql:
                assert params == [1, "same-video", 2, "same-video"]
                self.rows = [
                    {"owner_user_id": 1, "video_id": "same-video", "status": "confirmed", "publish_task_id": "workflow:job-1"},
                    {"owner_user_id": 2, "video_id": "same-video", "status": "confirmed", "publish_task_id": "workflow:job-2"},
                ]
            elif "FROM publish_dispatch_jobs" in sql:
                self.rows = []
            elif "FROM auth_users" in sql:
                self.rows = [
                    {"id": 1, "display_name": "用户一", "username": "one"},
                    {"id": 2, "display_name": "用户二", "username": "two"},
                ]
            else:
                raise AssertionError(sql)
            return self

        def fetchall(self):
            return self.rows

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connect(*_args, **_kwargs):
        yield Connection()

    monkeypatch.setattr(backend, "_db_connect", connect)
    rows = backend._task_load()

    assert [job["_task_chinese_title"] for job, _events, _materials in rows] == ["用户一标题", "用户二标题"]
    assert [[item["publish_task_id"] for item in materials] for _job, _events, materials in rows] == [
        ["workflow:job-1"], ["workflow:job-2"],
    ]


def test_source_title_translation_cache_uses_owner_user_id(monkeypatch):
    backend = create_backend_module()
    calls = []

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        row_factory = False

        def execute(self, sql, params):
            calls.append((sql, params))
            rows = [{"metadata": '{"sourceTitleZh":"用户二缓存"}'}] if params == ("same-video", 2) else []
            return Result(rows)

    @contextmanager
    def connect(*_args, **_kwargs):
        yield Connection()

    monkeypatch.setattr(backend, "_db_connect", connect)

    assert backend._source_title_translation_from_events("same-video", 1) == ""
    assert backend._source_title_translation_from_events("same-video", 2) == "用户二缓存"
    assert [params for _sql, params in calls] == [("same-video", 1), ("same-video", 2)]


def test_publish_graph_uses_live_dispatch_target_status():
    backend = create_backend_module()
    job = {
        "status": "running",
        "publish_to_douyin": 1,
        "account": "creator",
        "publishProgress": {
            "targets": [{
                "platform_type": 3,
                "status": "running",
                "message": "publishing",
                "started_at": "2026-08-11 23:04:00",
            }],
        },
    }
    events = [{
        "stage": "publish",
        "status": "running",
        "message": "publishing",
        "startedAt": "2026-08-11 23:04:00",
        "endedAt": "",
        "durationSeconds": 0,
    }]
    stale_materials = [{"platform_type": 3, "status": "pending", "message": "queued"}]

    graph = backend._task_publish_graph(job, events, stale_materials)

    target = next(node for node in graph["nodes"] if node["id"] == "publish-3")
    assert target["status"] == "running"
    assert target["message"] == "publishing"


def test_task_center_uses_video_channel_name_for_platform_two():
    backend = create_backend_module()

    targets = backend._task_targets({"publish_to_tencent": 1, "tencent_account": "channel-account"}, [])

    assert targets == [{"type": 2, "label": "视频号", "account": "channel-account", "records": []}]


def test_publish_workflow_submission_reuses_existing_active_job(monkeypatch):
    backend = create_backend_module()
    active_job = {"id": "job-existing", "videoId": "video-1", "status": "waiting_publish", "processVersion": "translation_v1"}
    submitted = []
    monkeypatch.setattr(backend, "_current_account_owner_id", lambda: 7)
    monkeypatch.setattr(backend, "_check_named_publish_account", lambda *_args: None)
    monkeypatch.setattr(
        backend,
        "create_youtube_workflow_job",
        lambda _payload: (_ for _ in ()).throw(backend.WorkflowConflictError(
            "active", "VF-WORKFLOW-LOCK", "ACTIVE_JOB_LOCK", {"job": active_job},
        )),
    )
    monkeypatch.setattr(backend, "_submit_workflow_job", lambda *_args: submitted.append(True))

    with backend.app.test_request_context(
        "/youtube/workflow/jobs",
        method="POST",
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "videoId": "video-1", "publishToDouyin": True, "account": "creator"},
    ):
        response = backend.create_youtube_workflow()

    body = response[0].get_json()
    assert response[1] == 202
    assert body["data"]["id"] == "job-existing"
    assert body["data"]["reused"] is True
    assert submitted == []


def test_workflow_publish_enqueues_targets_without_direct_platform_execution():
    backend = create_backend_module()
    updates = []
    queued = []
    job = {
        "id": "job-1", "videoId": "video-1", "title": "测试视频",
        "account": "douyin-account", "bilibiliAccount": "bili-account",
        "xiaohongshuAccount": "", "kuaishouAccount": "", "tencentAccount": "",
        "processVersion": "compat", "translationEnabled": True, "ownerUserId": 1,
    }
    backend.get_youtube_workflow_job = lambda _job_id: dict(job)
    backend._get_youtube_video_record = lambda _video_id, _owner_id: {"publishDraft": {}}
    backend.get_source_content_risk = lambda _materials: {}
    backend._published_platform_types_for_video = lambda _video_id: set()
    backend.start_workflow_event = lambda *_args, **_kwargs: 9
    backend.finish_workflow_event = lambda *_args, **_kwargs: None
    backend.update_youtube_video_artifacts = lambda *_args, **_kwargs: None
    backend.update_youtube_workflow_job = lambda *_args, **kwargs: updates.append(kwargs)

    backend._check_named_publish_account = lambda platform_type, account_name, _owner_id: {
        "id": platform_type, "filePath": f"{account_name}.json", "ownerUserId": 1,
    }
    backend.enqueue_publish_tasks = lambda tasks, **kwargs: queued.append((tasks, kwargs)) or {"publishTaskId": kwargs["publish_task_id"]}

    backend._publish_workflow_outputs("job-1", job, "video.mp4", {"file_path": "video.mp4"})

    assert [task["platformType"] for task in queued[0][0]] == [3, 5]
    assert queued[0][1]["source"] == "workflow"
    assert updates[-1]["status"] == "waiting_publish"
