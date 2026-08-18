import asyncio

import pytest

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


def test_tencent_diagnostics_redact_query_and_request_details():
    assert tencent_main._safe_tencent_url(
        "https://channels.weixin.qq.com/platform/post/list?token=secret"
    ) == "https://channels.weixin.qq.com/platform/post/list"

    diagnostics = tencent_main.TencentPublishDiagnostics()

    class Request:
        method = "POST"
        url = "https://channels.weixin.qq.com/api/post?cookie=secret"
        failure = "net::ERR_FAILED"

    diagnostics._on_request_failed(Request())
    assert diagnostics.failed_requests == [{
        "method": "POST",
        "url": "https://channels.weixin.qq.com/api/post",
        "failure": "net::ERR_FAILED",
    }]


def test_tencent_result_marker_and_work_id_extraction():
    payload = {"data": {"object_id": "work-123", "url": "https://channels.weixin.qq.com/work/123"}}
    assert tencent_main._tencent_work_candidates(payload) == {
        "work-123": "https://channels.weixin.qq.com/work/123"
    }
    marker = tencent_main.format_tencent_publish_result({
        "platformWorkId": "work-123",
        "platformWorkUrl": "https://channels.weixin.qq.com/work/123",
    })
    assert marker.startswith(tencent_main.TENCENT_PUBLISH_RESULT_MARKER)
    assert '"platformWorkId": "work-123"' in marker


def test_tencent_defaults_to_headed_browser():
    assert tencent_main.LOCAL_CHROME_HEADLESS is False
    assert tencent_main.TENCENT_COVER_GENERATION_STALL_TIMEOUT == 90
    assert tencent_main.TENCENT_UPLOAD_WAIT_TIMEOUT >= 2700
    assert "VF-PUBLISH-PERMISSION-DENIED" in str(tencent_main.TencentPublishPermissionError())


def test_tencent_failure_reasons_have_distinct_workflow_categories():
    assert classify_workflow_exception(RuntimeError("VF-PUBLISH-COOKIE-INVALID: expired"))["error_type"] == "PUBLISH_COOKIE_INVALID"
    assert classify_workflow_exception(RuntimeError("VF-PUBLISH-UPLOAD-FAILED: failed"))["error_type"] == "PUBLISH_UPLOAD_FAILED"
    assert classify_workflow_exception(RuntimeError("VF-PUBLISH-PAGE-RECOVERY-FAILED: cover"))["error_type"] == "PUBLISH_PAGE_RECOVERY_FAILED"


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
