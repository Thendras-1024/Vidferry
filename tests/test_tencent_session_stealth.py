from pathlib import Path


def test_tencent_qr_login_and_video_upload_keep_separate_contexts():
    source = Path("uploader/tencent_uploader/main.py").read_text(encoding="utf-8")
    login_flow = source.split("async def tencent_cookie_gen", 1)[1].split("async def tencent_setup", 1)[0]
    video_upload = source.split("class TencentVideo", 1)[1].split("class TencentNote", 1)[0]

    assert "context = await browser.new_context()\n        context = await set_init_script(context)" not in login_flow
    assert "context = await browser.new_context(storage_state=self.account_file)" in video_upload
