"""FFmpeg 命令与视频元信息辅助函数。"""

import shutil
from pathlib import Path

from app.config import FFMPEG_COMMAND, VIDEO_ENCODER, VIDEO_NVENC_CQ, VIDEO_NVENC_PRESET


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


def video_encode_args(burn_config):
    from app.core.runtime_config import ensure_video_encoder_ready
    ensure_video_encoder_ready()
    if VIDEO_ENCODER == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc", "-preset", VIDEO_NVENC_PRESET,
            "-rc", "vbr", "-cq", str(VIDEO_NVENC_CQ), "-b:v", "0",
        ]
    if VIDEO_ENCODER == "libx264":
        return ["-c:v", "libx264", "-preset", burn_config["preset"], "-crf", burn_config["crf"]]
    raise RuntimeError("VIDEO_ENCODER 仅支持 libx264 或 h264_nvenc。")
