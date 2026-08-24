import asyncio

import pytest

from app.core.error_catalog import classify_workflow_exception
from uploader.tencent_uploader import main as tencent_main
from uploader.tencent_uploader.main import (
    TENCENT_UPLOAD_URL,
    TencentPublishPermissionError,
    _is_tencent_login_completed,
    _wait_for_tencent_login,
)


class _Locator:
    def __init__(self, visible):
        self.visible = visible

    @property
    def first(self):
        return self

    async def count(self):
        return int(self.visible)

    async def is_visible(self):
        return self.visible


class _Page:
    url = TENCENT_UPLOAD_URL

    def locator(self, selector):
        return _Locator(selector == 'div.no-permission-title')


def test_permission_dialog_is_not_treated_as_valid_login():
    with pytest.raises(TencentPublishPermissionError, match="管理员或运营者"):
        asyncio.run(_is_tencent_login_completed(_Page()))


def test_permission_error_uses_the_publish_error_catalog_entry():
    error = classify_workflow_exception(TencentPublishPermissionError())

    assert error["error_code"] == "VF-PUBLISH-PERMISSION-DENIED"
    assert error["error_type"] == "PUBLISH_PERMISSION_DENIED"


def test_tencent_login_waits_for_main_frame_navigation(monkeypatch, tmp_path):
    class Page:
        def __init__(self):
            self.url = TENCENT_UPLOAD_URL
            self.main_frame = object()
            self.handler = None

        def on(self, event, handler):
            assert event == "framenavigated"
            self.handler = handler

        def remove_listener(self, event, handler):
            assert event == "framenavigated"
            assert handler is self.handler

        def locator(self, _selector):
            return _Locator(False)

    page = Page()
    login_state = {"completed": False}

    async def is_login_completed(_page):
        return login_state["completed"]

    monkeypatch.setattr(tencent_main, "_is_tencent_login_completed", is_login_completed)

    async def navigate_after_scan():
        await asyncio.sleep(0)
        login_state["completed"] = True
        page.url = "https://channels.weixin.qq.com/platform"
        page.handler(page.main_frame)

    async def run():
        asyncio.create_task(navigate_after_scan())
        return await _wait_for_tencent_login(
            page,
            "account.json",
            {"image_path": str(tmp_path / "qrcode.png")},
            poll_interval=3,
            max_checks=1,
        )

    result = asyncio.run(run())

    assert result["success"] is True
    assert result["current_url"] == "https://channels.weixin.qq.com/platform"


def test_tencent_login_times_out_without_main_frame_navigation(monkeypatch, tmp_path):
    class Page:
        url = TENCENT_UPLOAD_URL
        main_frame = object()

        def on(self, _event, _handler):
            pass

        def remove_listener(self, _event, _handler):
            pass

        def locator(self, _selector):
            return _Locator(False)

    page = Page()
    login_state = {"checks": 0}

    async def is_login_completed(_page):
        login_state["checks"] += 1
        return False

    monkeypatch.setattr(tencent_main, "_is_tencent_login_completed", is_login_completed)

    result = asyncio.run(
        _wait_for_tencent_login(
            page,
            "account.json",
            {"image_path": str(tmp_path / "qrcode.png")},
            poll_interval=0.01,
            max_checks=1,
        )
    )

    assert result["success"] is False
    assert login_state["checks"] >= 1
