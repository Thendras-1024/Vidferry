from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


class BaseVideoUploader:
    SUPPORTED_VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
        ".webm",
        ".flv",
        ".wmv",
    }
    SUPPORTED_IMAGE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
    }
    MIN_SCHEDULE_LEAD_TIME = timedelta(hours=2)

    @staticmethod
    async def set_upload_files(file_input, files, platform_name: str, asset_name: str) -> None:
        """仅将已明确的浏览器上传控件超时转为稳定发布错误。"""
        try:
            await file_input.set_input_files(files)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
            raise RuntimeError(
                f"VF-PUBLISH-UPLOAD-INPUT-MISSING : {platform_name}{asset_name}上传控件在等待期间未出现或不可用。"
                "请确认账号仍停留在发布页面，或平台页面结构未变更后重试。"
            ) from exc

    @staticmethod
    async def choose_upload_files(page, upload_button, files, platform_name: str, asset_name: str) -> None:
        try:
            async with page.expect_file_chooser() as file_chooser_info:
                await upload_button.click()
            file_chooser = await file_chooser_info.value
            await file_chooser.set_files(files)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
            raise RuntimeError(
                f"VF-PUBLISH-UPLOAD-INPUT-MISSING : {platform_name}点击上传后未打开{asset_name}文件选择器。"
                "请确认账号仍停留在发布页面，或平台页面结构未变更后重试。"
            ) from exc

    @classmethod
    def validate_video_file(cls, file_path: str | Path) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"视频文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"视频路径不是文件: {path}")
        if path.suffix.lower() not in cls.SUPPORTED_VIDEO_EXTENSIONS:
            raise ValueError(
                f"不支持的视频格式: {path.suffix}，当前支持: {', '.join(sorted(cls.SUPPORTED_VIDEO_EXTENSIONS))}"
            )

        return path

    @classmethod
    def validate_image_file(cls, file_path: str | Path) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"图片文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"图片路径不是文件: {path}")
        if path.suffix.lower() not in cls.SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"不支持的图片格式: {path.suffix}，当前支持: {', '.join(sorted(cls.SUPPORTED_IMAGE_EXTENSIONS))}"
            )
        return path

    @classmethod
    def validate_publish_date(cls, publish_date: datetime | int | None) -> datetime | int:
        if publish_date in (None, 0):
            return 0

        if not isinstance(publish_date, datetime):
            raise TypeError("publish_date 必须是 datetime 类型或 0")

        now = datetime.now(tz=publish_date.tzinfo) if publish_date.tzinfo else datetime.now()
        if publish_date <= now:
            raise ValueError("定时发布时间必须晚于当前时间")

        min_publish_time = now + cls.MIN_SCHEDULE_LEAD_TIME
        if publish_date <= min_publish_time:
            raise ValueError("定时发布时间必须大于当前时间 2 小时")

        return publish_date
