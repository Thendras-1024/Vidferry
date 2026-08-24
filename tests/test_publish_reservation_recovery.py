from app.backend.runtime import create_backend_module


def test_publish_reservation_state_is_safe_for_active_and_terminal_parents():
    backend = create_backend_module()

    assert backend._resolve_publish_reservation_status("queued", "dispatch", "running") == "running"
    assert backend._resolve_publish_reservation_status("running", "dispatch", "failed") == "failed"
    assert backend._resolve_publish_reservation_status("queued", "dispatch", "confirmed") == "confirmed"
    assert backend._resolve_publish_reservation_status("running", "missing", "") == "uncertain"
    assert backend._resolve_publish_reservation_status("queued", "missing", "") == "failed"
    assert backend._resolve_publish_reservation_status("uncertain", "dispatch", "failed") == "uncertain"


def test_failed_record_is_archived_for_every_new_publish_attempt():
    backend = create_backend_module()

    assert backend._should_archive_failed_publish_record("failed", retry_context=False)
    assert backend._should_archive_failed_publish_record("timeout", retry_context=False)
    assert backend._should_archive_failed_publish_record("failed", retry_context=True)
    assert not backend._should_archive_failed_publish_record("running", retry_context=False)


def test_publish_dispatch_status_can_be_recomputed_after_unknown_release():
    backend = create_backend_module()

    assert backend._publish_dispatch_status([{"status": "failed"}]) == "failed"
    assert backend._publish_dispatch_status([{"status": "confirmed"}, {"status": "failed"}]) == "partial"
    assert backend._publish_dispatch_status([{"status": "uncertain"}, {"status": "failed"}]) == "uncertain"


def test_duplicate_decisions_keep_confirmed_active_and_uncertain_distinct():
    backend = create_backend_module()

    assert backend._publish_duplicate_decision("confirmed")[0] == "reused"
    assert backend._publish_duplicate_decision("uncertain")[0] == "uncertain"
    assert backend._publish_duplicate_decision("running")[0] == "waiting_existing"
    assert backend._publish_duplicate_skip_message("confirmed") == "此前已确认发布，本次复用已有结果"
    assert backend._publish_duplicate_skip_message("uncertain") == "上一轮发布结果待核验，本次未重新提交"
    assert backend._publish_duplicate_skip_message("running") == "已有发布任务进行中，未重复提交"
