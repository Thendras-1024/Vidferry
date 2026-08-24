from subprocess import CompletedProcess

from app.backend.runtime import create_backend_module


def _task():
    return {
        "publishTaskId": "task-1",
        "platformType": 2,
        "platformName": "视频号",
        "accountName": "account",
        "accountId": 1,
        "ownerUserId": 1,
        "accountFile": "account.json",
        "accountPath": "account.json",
        "fileList": ["video.mp4"],
        "absoluteFiles": ["video.mp4"],
        "title": "标题",
        "description": "",
        "tags": [],
        "publishDatetimes": [0],
    }


def _prepare(backend, monkeypatch, output):
    marks = []
    monkeypatch.setattr(backend, "_mark_published_materials", lambda *_args, **kwargs: marks.append(kwargs) or ["video-1"])
    monkeypatch.setattr(backend, "_get_publish_account_lock", lambda *_args, **_kwargs: __import__("threading").Lock())
    monkeypatch.setattr(backend, "_publish_runner_command", lambda *_args, **_kwargs: ["runner"])
    monkeypatch.setattr(backend, "_run_isolated_publish_command", lambda *_args, **_kwargs: CompletedProcess(["runner"], 0, output, ""))
    return marks


def test_tencent_successful_exit_confirms_publish(monkeypatch):
    backend = create_backend_module()
    marks = _prepare(backend, monkeypatch, "")

    result = backend._execute_publish_target(_task())

    assert result["status"] == "confirmed"
    assert [item["status"] for item in marks] == ["running", "confirmed"]


def test_cookie_invalid_is_failed_and_marks_only_the_task_account(monkeypatch):
    backend = create_backend_module()
    marks = _prepare(backend, monkeypatch, "")
    abnormal_calls = []
    monkeypatch.setattr(
        backend,
        "_run_isolated_publish_command",
        lambda *_args, **_kwargs: CompletedProcess(["runner"], 1, "", "VF-PUBLISH-COOKIE-INVALID: Cookie 已失效"),
    )
    monkeypatch.setattr(backend, "_mark_account_abnormal", lambda task, reason: abnormal_calls.append((task, reason)))

    result = backend._execute_publish_target(_task())

    assert result["status"] == "failed"
    assert "VF-PUBLISH-COOKIE-INVALID" in result["message"]
    assert [item["status"] for item in marks] == ["running", "failed"]
    assert abnormal_calls == [(_task(), result["message"])]


def test_publish_failure_classification_keeps_unknown_results_uncertain():
    backend = create_backend_module()

    assert backend._publish_failure_status("VF-PUBLISH-COOKIE-INVALID: Cookie 已失效") == "failed"
    assert backend._publish_failure_status("VF-PUBLISH-UPLOAD-NOT-STARTED: 上传未开始") == "failed"
    assert backend._publish_failure_status("VF-PUBLISH-UPLOAD-FAILED: 平台明确上传失败") == "failed"
    assert backend._publish_failure_status("VF-PUBLISH-PERMISSION-DENIED: 平台拒绝提交") == "failed"
    assert backend._publish_failure_status("VF-PUBLISH-RATE-LIMIT: 平台频控") == "failed"
    assert backend._publish_failure_status("发布视频文件不存在: video.mp4") == "failed"
    assert backend._publish_failure_status("VF-PUBLISH-CONFIRM-TIMEOUT: 发布确认超时") == "uncertain"
    assert backend._publish_failure_status("VF-PUBLISH-PAGE-RECOVERY-FAILED: 页面恢复失败") == "uncertain"
    assert backend._publish_failure_status("unexpected runner error") == "uncertain"


def test_unknown_publish_error_stays_uncertain(monkeypatch):
    backend = create_backend_module()
    marks = _prepare(backend, monkeypatch, "")
    monkeypatch.setattr(
        backend,
        "_run_isolated_publish_command",
        lambda *_args, **_kwargs: CompletedProcess(["runner"], 1, "", "unexpected runner error"),
    )

    result = backend._execute_publish_target(_task())

    assert result["status"] == "uncertain"
    assert [item["status"] for item in marks] == ["running", "uncertain"]


def test_publish_tasks_continue_after_a_definitive_failure(monkeypatch):
    backend = create_backend_module()
    executed_platforms = []

    def execute(task):
        executed_platforms.append(task["platformType"])
        return {"platformType": task["platformType"], "status": "failed" if task["platformType"] == 2 else "confirmed"}

    monkeypatch.setattr(backend, "_execute_publish_target", execute)

    results = backend._run_publish_tasks([{"platformType": 2}, {"platformType": 3}])

    assert executed_platforms == [2, 3]
    assert [item["status"] for item in results] == ["failed", "confirmed"]
