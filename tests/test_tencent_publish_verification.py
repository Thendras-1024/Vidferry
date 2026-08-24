import asyncio

import uploader.tencent_uploader.main as tencent_main


class _Button:
    async def count(self):
        return 1

    async def click(self):
        return None


class _Page:
    url = tencent_main.TENCENT_MANAGE_URL

    def locator(self, selector):
        assert "发表" in selector
        return _Button()

    async def wait_for_url(self, url, timeout):
        assert url == tencent_main.TENCENT_MANAGE_URL
        assert timeout == 5000


async def _no_delay(*_args, **_kwargs):
    return None


def test_submit_publish_confirms_after_list_navigation(monkeypatch):
    uploader = type("Uploader", (), {"is_draft": False})()
    monkeypatch.setattr(tencent_main, "human_delay", _no_delay)

    result = asyncio.run(tencent_main.TencentBaseUploader.submit_publish(uploader, _Page()))

    assert result is None
