import asyncio

import uploader.tencent_uploader.main as tencent_main


class _Button:
    async def get_attribute(self, _name):
        return "weui-desktop-btn"


class _Locator:
    async def count(self):
        return 0


class _Page:
    def get_by_role(self, _role, name):
        assert name == "发表"
        return _Button()

    def locator(self, _selector):
        return _Locator()


class _Uploader(tencent_main.TencentVideo):
    def __init__(self):
        pass


def test_publish_wait_defaults_match_current_uploader():
    assert tencent_main.TENCENT_UPLOAD_WAIT_TIMEOUT == 1800
    assert tencent_main.TENCENT_PUBLISH_CONFIRM_TIMEOUT == 300


def test_upload_complete_when_publish_button_is_enabled():
    asyncio.run(_Uploader().wait_for_upload_complete(_Page()))
