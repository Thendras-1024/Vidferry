import asyncio
import threading
from subprocess import CompletedProcess

import pytest

from app.backend.runtime import create_backend_module
from app.core.error_catalog import classify_workflow_exception
from uploader.tencent_uploader import main as tencent_main


class _FakeLocator:
    def __init__(self, owner, kind):
        self.owner = owner
        self.kind = kind

    async def count(self):
        if self.kind == "error":
            return int(self.owner.upload_failed)
        if self.kind == "delete":
            return int(self.owner.upload_failed)
        if self.kind == "cover":
            return int(self.owner.cover_generating)
        return 1

    async def get_attribute(self, name):
        assert name == "class"
        return "weui-desktop-btn_disabled" if self.owner.button_disabled else ""

    async def is_visible(self):
        return bool(self.owner.cover_generating)

    def nth(self, index):
        assert index == 0
        return self


class _FakePage:
    def __init__(self):
        self.upload_failed = True
        self.cover_generating = True
        self.button_disabled = True
        self.cover_checked = False

    def locator(self, selector):
        if selector == "div.status-msg.error":
            return _FakeLocator(self, "error")
        if "tag-inner" in selector:
            return _FakeLocator(self, "delete")
        raise AssertionError(f"unexpected selector : {selector}")

    def get_by_text(self, text, exact=False):
        assert text == "生成中"
        assert exact is True
        self.cover_checked = True
        return _FakeLocator(self, "cover")

    def get_by_role(self, role, name):
        assert role == "button"
        assert name == "发表"
        return _FakeLocator(self, "publish")


def test_tencent_login_wait_polls_when_url_does_not_change(monkeypatch):
    class Page:
        url = tencent_main.TENCENT_LOGIN_URL
        main_frame = object()

        def on(self, event, listener):
            assert event == "framenavigated"
            self.listener = listener

        def remove_listener(self, event, listener):
            assert event == "framenavigated"
            assert listener is self.listener

    page = Page()
    checks = []

    async def login_completed(_page):
        checks.append(1)
        return len(checks) == 2

    monkeypatch.setattr(tencent_main, "_is_tencent_login_completed", login_completed)

    result = asyncio.run(
        tencent_main._wait_for_tencent_login(
            page,
            "account.json",
            {},
            poll_interval=0.01,
            max_checks=5,
        )
    )

    assert result["success"] is True
    assert len(checks) == 2


def test_tencent_defaults_and_cookie_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tencent_main, "BASE_DIR", tmp_path)
    assert tencent_main.LOCAL_CHROME_HEADLESS is False
    assert tencent_main.TENCENT_UPLOAD_WAIT_TIMEOUT == 1800
    assert tencent_main.TENCENT_PUBLISH_CONFIRM_TIMEOUT == 300
    assert tencent_main._resolve_account_file("account.json") == str(
        (tmp_path / "cookiesFile" / "legacy" / "tencent_uploader" / "account.json").resolve()
    )
    assert "VF-PUBLISH-PERMISSION-DENIED" not in str(tencent_main.TencentPublishPermissionError())


def test_tencent_failure_reasons_have_distinct_workflow_categories():
    assert classify_workflow_exception(RuntimeError("VF-PUBLISH-COOKIE-INVALID: expired"))["error_type"] == "PUBLISH_COOKIE_INVALID"
    assert classify_workflow_exception(RuntimeError("VF-PUBLISH-UPLOAD-FAILED: failed"))["error_type"] == "PUBLISH_UPLOAD_FAILED"


def test_tencent_runner_confirms_publish_after_successful_exit(monkeypatch):
    backend = create_backend_module()
    marks = []
    task = {
        "publishTaskId": "task-1", "platformType": 2, "platformName": "视频号",
        "accountName": "account", "accountId": 1, "ownerUserId": 1,
        "accountFile": "account.json", "accountPath": "account.json",
        "fileList": ["video.mp4"], "absoluteFiles": ["video.mp4"],
        "title": "标题", "description": "", "tags": [], "publishDatetimes": [0],
    }
    monkeypatch.setattr(backend, "_mark_published_materials", lambda *_args, **kwargs: marks.append(kwargs) or ["video-1"])
    monkeypatch.setattr(backend, "_get_publish_account_lock", lambda *_args, **_kwargs: threading.Lock())
    monkeypatch.setattr(backend, "_publish_runner_command", lambda *_args, **_kwargs: ["runner"])
    monkeypatch.setattr(
        backend,
        "_run_isolated_publish_command",
        lambda *_args, **_kwargs: CompletedProcess(["runner"], 0, "", ""),
    )

    result = backend._execute_publish_target(task)

    assert result["status"] == "confirmed"
    assert [item["status"] for item in marks] == ["running", "confirmed"]
    assert marks[-1]["platform_work_id"] == ""


def test_publish_queue_matches_library_relative_storage_key(tmp_path, monkeypatch):
    backend = create_backend_module()
    library_root = tmp_path / "videoFile"
    material_path = library_root / "1" / "material.mp4"
    monkeypatch.setattr(backend, "_PUBLISH_LIBRARY_BASE_DIR", tmp_path)

    assert backend._publish_material_lookup_values(material_path) == [
        str(material_path),
        "1/material.mp4",
    ]


def test_upload_error_is_handled_before_cover_generation_timer(monkeypatch):
    page = _FakePage()
    uploader = object.__new__(tencent_main.TencentVideo)
    handled = []

    class UploadErrorProbe(RuntimeError):
        pass

    async def handle_upload_error(current_page):
        handled.append(current_page)
        raise UploadErrorProbe("upload branch reached")

    uploader.handle_upload_error = handle_upload_error
    monkeypatch.setattr(tencent_main, "jitter_seconds", lambda *_args, **_kwargs: 0)

    with pytest.raises(UploadErrorProbe, match="upload branch reached"):
        asyncio.run(uploader.wait_for_upload_complete(page))

    assert handled == [page]
    assert page.cover_checked is False
