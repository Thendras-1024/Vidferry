from __future__ import annotations

from pathlib import Path

from app.cli.models import XiaohongshuNoteUploadRequest, XiaohongshuVideoUploadRequest
from app.cli.utils import resolve_account_file


async def login_xiaohongshu_account(account_name: str, headless: bool = True) -> dict:
    from uploader.xiaohongshu_uploader.main import xiaohongshu_setup

    account_file = resolve_account_file("xiaohongshu", account_name)
    return await xiaohongshu_setup(str(account_file), handle=True, return_detail=True, headless=headless)


async def check_xiaohongshu_account(account_name: str) -> bool:
    from uploader.xiaohongshu_uploader.main import cookie_auth as xiaohongshu_cookie_auth

    account_file = resolve_account_file("xiaohongshu", account_name)
    if not account_file.exists():
        return False
    return await xiaohongshu_cookie_auth(str(account_file))


async def upload_xiaohongshu_video(request: XiaohongshuVideoUploadRequest) -> Path:
    from uploader.xiaohongshu_uploader.main import XiaoHongShuVideo, xiaohongshu_setup

    account_file = resolve_account_file("xiaohongshu", request.account_name)
    is_ready = await xiaohongshu_setup(str(account_file), handle=False)
    if not is_ready:
        raise RuntimeError(
            f"Xiaohongshu cookie is missing or expired: {account_file}. Run `sau xiaohongshu login --account {request.account_name}` first."
        )

    app = XiaoHongShuVideo(
        title=request.title,
        file_path=str(request.video_file),
        desc=request.description,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=str(account_file),
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
    )
    await app.main()
    return account_file


async def upload_xiaohongshu_note(request: XiaohongshuNoteUploadRequest) -> Path:
    from uploader.xiaohongshu_uploader.main import XiaoHongShuNote, xiaohongshu_setup

    account_file = resolve_account_file("xiaohongshu", request.account_name)
    is_ready = await xiaohongshu_setup(str(account_file), handle=False)
    if not is_ready:
        raise RuntimeError(
            f"Xiaohongshu cookie is missing or expired: {account_file}. Run `sau xiaohongshu login --account {request.account_name}` first."
        )

    app = XiaoHongShuNote(
        image_paths=[str(path) for path in request.image_files],
        title=request.title,
        desc=request.note,
        note=request.note,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=str(account_file),
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
    )
    await app.main()
    return account_file
