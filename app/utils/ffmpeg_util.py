"""FFmpeg 命令与视频元信息辅助函数。"""

import shutil
from pathlib import Path

from app.config import FFMPEG_COMMAND


def _resolve_ffmpeg_command():
    configured = str(FFMPEG_COMMAND or "").strip()
    if configured and (shutil.which(configured) or Path(configured).exists()):
        return configured
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "未找到 FFmpeg。请安装 ffmpeg，或安装 imageio-ffmpeg，或在 conf.py/.env 配置 FFMPEG_COMMAND。"
        ) from exc
