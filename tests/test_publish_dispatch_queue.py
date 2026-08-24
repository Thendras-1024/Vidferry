from pathlib import Path
import threading

from app.backend.runtime import create_backend_module


def test_publish_dispatch_progress_counts_target_states():
    backend = create_backend_module()

    progress = backend._publish_dispatch_progress([
        {"status": "confirmed"},
        {"status": "running"},
        {"status": "queued"},
        {"status": "uncertain"},
        {"status": "failed"},
    ])

    assert progress == {
        "total": 5,
        "queued": 1,
        "running": 1,
        "confirmed": 1,
        "failed": 1,
        "uncertain": 1,
        "reused": 0,
        "waiting_existing": 0,
        "cancelled": 0,
        "completed": 3,
        "percentage": 60,
    }


from app.db.schema import _migration_paths


def test_publish_dispatch_payload_round_trips_paths():
    backend = create_backend_module()
    task = {"platformType": 3, "absoluteFiles": [Path("video.mp4")], "fileList": ["video.mp4"]}

    payload = backend._publish_dispatch_payload([task])
    restored = backend._publish_dispatch_tasks(payload)

    assert restored[0]["absoluteFiles"] == [Path("video.mp4")]
    assert restored[0]["platformType"] == 3


def test_publish_dispatch_status_preserves_unknown_and_partial():
    backend = create_backend_module()

    assert backend._publish_dispatch_status([{"status": "confirmed"}]) == "confirmed"
    assert backend._publish_dispatch_status([{"status": "confirmed"}, {"status": "failed"}]) == "partial"
    assert backend._publish_dispatch_status([{"status": "uncertain"}]) == "uncertain"
    assert backend._publish_dispatch_status([{"status": "uncertain"}, {"status": "running"}]) == "running"
    assert backend._publish_dispatch_status([{"status": "failed"}, {"status": "queued"}]) == "queued"


def test_publish_dispatch_status_keeps_reuse_and_waiting_existing_distinct():
    backend = create_backend_module()

    assert backend._publish_dispatch_status([{"status": "reused"}]) == "reused"
    assert backend._publish_dispatch_status([{"status": "waiting_existing"}]) == "waiting_existing"
    assert backend._publish_dispatch_status([{"status": "confirmed"}, {"status": "reused"}]) == "confirmed"
    assert backend._publish_dispatch_status([{"status": "failed"}, {"status": "reused"}]) == "partial"


def test_publish_dispatch_progress_does_not_complete_waiting_existing():
    backend = create_backend_module()

    progress = backend._publish_dispatch_progress([{"status": "queued"}, {"status": "waiting_existing"}])

    assert progress["waiting_existing"] == 1
    assert progress["completed"] == 0


def test_workflow_publish_does_not_reopen_an_already_skipped_dispatch(monkeypatch):
    backend = create_backend_module()
    updates = []
    job = {
        "id": "job-1", "videoId": "video-1", "title": "video", "processVersion": "translation_v1",
        "account": "creator", "bilibiliAccount": "", "xiaohongshuAccount": "", "kuaishouAccount": "", "tencentAccount": "",
    }

    monkeypatch.setattr(backend, "get_youtube_workflow_job", lambda _job_id: dict(job))
    monkeypatch.setattr(backend, "get_source_content_risk", lambda _materials: {})
    monkeypatch.setattr(backend, "_ensure_workflow_publish_schedule", lambda _job_id, publish_job: (publish_job, ""))
    monkeypatch.setattr(backend, "start_workflow_event", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(backend, "_check_named_publish_account", lambda *_args: {"ownerUserId": 1})
    monkeypatch.setattr(backend, "_workflow_publish_task", lambda *_args: {"platformType": 3})
    monkeypatch.setattr(backend, "enqueue_publish_tasks", lambda *_args, **_kwargs: {"publishTaskId": "workflow:job-1", "status": "reused"})
    monkeypatch.setattr(backend, "update_youtube_workflow_job", lambda *_args, **changes: updates.append(changes))

    backend._publish_workflow_outputs("job-1", job, "video.mp4", {"file_path": "video.mp4"})

    assert not any(change.get("status") == "waiting_publish" for change in updates)


def test_workflow_status_from_dispatch_does_not_treat_waiting_as_success():
    backend = create_backend_module()

    assert backend._workflow_status_from_dispatch("confirmed") == ("success", "done")
    assert backend._workflow_status_from_dispatch("reused") == ("reused", "done")
    assert backend._workflow_status_from_dispatch("partial") == ("partial", "publish")
    assert backend._workflow_status_from_dispatch("uncertain") == ("needs_verification", "publish")
    assert backend._workflow_status_from_dispatch("waiting_existing") == ("waiting_publish", "publish")


def test_publish_account_lock_is_scoped_to_owner_platform_and_account():
    backend = create_backend_module()
    backend._publish_account_locks.clear()

    first = backend._get_publish_account_lock(3, "one.json", account_id=7, owner_user_id=1)
    assert first is backend._get_publish_account_lock(3, "other.json", account_id=7, owner_user_id=1)
    assert first is not backend._get_publish_account_lock(3, "one.json", account_id=8, owner_user_id=1)
    assert first is not backend._get_publish_account_lock(3, "one.json", account_id=7, owner_user_id=2)


def test_background_queue_rotates_waiting_owners():
    backend = create_backend_module()
    resource = "comment"
    assert backend._workflow_executor_limits[resource][0] == 1
    started = threading.Event()
    release = threading.Event()
    order = []

    def first():
        order.append("owner-1-first")
        started.set()
        release.wait(5)

    def record(label):
        order.append(label)

    first_future = backend._submit_background_task(resource, first, owner_user_id=1)
    assert started.wait(2)
    owner_one_future = backend._submit_background_task(resource, record, "owner-1-second", owner_user_id=1)
    owner_two_future = backend._submit_background_task(resource, record, "owner-2-first", owner_user_id=2)
    release.set()

    first_future.result(timeout=5)
    owner_one_future.result(timeout=5)
    owner_two_future.result(timeout=5)
    assert order == ["owner-1-first", "owner-2-first", "owner-1-second"]


def test_publish_dispatch_migration_declares_durable_queue_tables():
    migration = Path("app/db/migrations/postgresql/V020__publish_dispatch_queue.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS publish_dispatch_jobs" in migration
    assert "CREATE TABLE IF NOT EXISTS publish_dispatch_targets" in migration
    assert "idx_publish_dispatch_jobs_state" in migration


def test_postgresql_migration_versions_are_unique():
    versions = [path.name.split("__", 1)[0] for path in _migration_paths()]

    assert len(versions) == len(set(versions))


def test_publish_state_migration_keeps_scheduled_and_queued_distinct():
    migration = Path("app/db/migrations/postgresql/V023__publish_state_machine.sql").read_text(encoding="utf-8")

    scheduled_section = migration.split("UPDATE scheduled_publish_tasks", 1)[1]
    assert "WHEN 'pending' THEN 'scheduled'" in scheduled_section
    assert "WHEN target.status = 'pending' THEN 'queued'" in migration
    assert "dispatch.source = 'scheduled'" in migration


def test_publish_reconciliation_migration_derives_parent_states_from_targets():
    migration = Path("app/db/migrations/postgresql/V024__reconcile_publish_state_machine.sql").read_text(encoding="utf-8")

    assert "target.status IN ('failed', 'cancelled')" in migration
    assert "dispatch.source = 'workflow'" in migration
    assert "record.status = 'confirmed'" in migration
