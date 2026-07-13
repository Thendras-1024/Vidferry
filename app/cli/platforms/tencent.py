"""视频号平台 CLI 动作:账号登录、Cookie 校验、视频发布。"""

from __future__ import annotations

from pathlib import Path

from app.cli.models import TencentVideoUploadRequest
from app.cli.utils import resolve_account_file


async def login_tencent_account(account_name: str, headless: bool = False) -> dict:
    from uploader.tencent_uploader.main import tencent_setup

    account_file = resolve_account_file("tencent", account_name)
    return await tencent_setup(str(account_file), handle=True, return_detail=True, headless=headless)


async def check_tencent_account(account_name: str) -> bool:
    from uploader.tencent_uploader.main import cookie_auth as tencent_cookie_auth

    account_file = resolve_account_file("tencent", account_name)
    if not account_file.exists():
        return False
    return await tencent_cookie_auth(str(account_file))


async def upload_tencent_video(request: TencentVideoUploadRequest) -> Path:
    from uploader.tencent_uploader.main import TencentVideo

    account_file = resolve_account_file("tencent", request.account_name)
    if not account_file.exists():
        raise RuntimeError(
            f"Tencent cookie file is missing: {account_file}. Run `sau tencent login --account {request.account_name}` first."
        )

    app = TencentVideo(
        title=request.title,
        file_path=str(request.video_file),
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=str(account_file),
        is_draft=request.is_draft,
        desc=request.description,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
    )
    await app.tencent_upload_video()
    return account_file
