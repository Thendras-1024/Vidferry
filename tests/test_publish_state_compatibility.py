from app.core.publish_state import aggregate_publish_status, publish_progress, workflow_status_from_dispatch


def test_publish_state_remains_compatible_with_dispatch_results():
    targets = [{"status": "confirmed"}, {"status": "uncertain"}]

    assert aggregate_publish_status(targets) == "uncertain"
    assert publish_progress(targets) == {
        "total": 2,
        "queued": 0,
        "running": 0,
        "confirmed": 1,
        "failed": 0,
        "uncertain": 1,
        "cancelled": 0,
        "reused": 0,
        "waiting_existing": 0,
        "completed": 2,
        "percentage": 100,
    }
    assert workflow_status_from_dispatch("uncertain") == ("needs_verification", "publish")
