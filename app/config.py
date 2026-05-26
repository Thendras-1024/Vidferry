"""Application configuration values."""

from __future__ import annotations

import os
from pathlib import Path

from conf import BASE_DIR


APP_VERSION = "0.2.0"
HOST = os.getenv("VIDFERRY_HOST", "0.0.0.0")
PORT = int(os.getenv("VIDFERRY_PORT", "5409"))


def _load_local_env() -> None:
    env_path = Path(BASE_DIR / ".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_local_env()

try:
    from conf import (
        FFMPEG_COMMAND,
        SAU_COMMAND,
        SUBTITLE_COMMAND_TEMPLATE,
        YOUTUBE_DOWNLOAD_DIR,
        YOUTUBE_PROCESSED_DIR,
    )
except ImportError:
    FFMPEG_COMMAND = "ffmpeg"
    SAU_COMMAND = str(Path(BASE_DIR / ".venv" / "Scripts" / "sau.exe"))
    SUBTITLE_COMMAND_TEMPLATE = ""
    YOUTUBE_DOWNLOAD_DIR = Path(BASE_DIR / "videos" / "youtube")
    YOUTUBE_PROCESSED_DIR = Path(BASE_DIR / "videos" / "processed")

YOUTUBE_DOWNLOAD_DIR = Path(os.environ.get("YOUTUBE_DOWNLOAD_DIR", str(YOUTUBE_DOWNLOAD_DIR)))
YOUTUBE_PROCESSED_DIR = Path(os.environ.get("YOUTUBE_PROCESSED_DIR", str(YOUTUBE_PROCESSED_DIR)))
YOUTUBE_TRANSCRIPT_DIR = Path(os.environ.get("YOUTUBE_TRANSCRIPT_DIR", str(BASE_DIR / "videos" / "transcripts")))
YTDLP_JS_RUNTIME = os.environ.get("YTDLP_JS_RUNTIME", "").strip()
YTDLP_JS_RUNTIME_PATH = os.environ.get("YTDLP_JS_RUNTIME_PATH", "").strip()
YTDLP_REMOTE_COMPONENTS = [
    item.strip()
    for item in os.environ.get("YTDLP_REMOTE_COMPONENTS", "").split(",")
    if item.strip()
]

LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "90") or 90)
LLM_MAX_TRANSCRIPT_CHARS = int(os.environ.get("LLM_MAX_TRANSCRIPT_CHARS", "28000") or 28000)

SUBTITLE_LANGUAGES = {
    "zh-CN": {"label": "中文", "suffix": "zh"},
    "en": {"label": "英文", "suffix": "en"},
    "ja": {"label": "日文", "suffix": "ja"},
    "ko": {"label": "韩文", "suffix": "ko"},
    "es": {"label": "西班牙语", "suffix": "es"},
    "fr": {"label": "法语", "suffix": "fr"},
    "de": {"label": "德语", "suffix": "de"},
    "ru": {"label": "俄语", "suffix": "ru"},
}
DEFAULT_SUBTITLE_LANGUAGE = "zh-CN"
BURN_PROFILES = {
    "stable": {
        "preset": "fast",
        "crf": "23",
        "max_fps": 30.0,
        "max_long_side": 1920,
        "max_short_side": 1080,
        "maxrate": "5000k",
        "bufsize": "10000k",
    },
    "fast": {
        "preset": "veryfast",
        "crf": "24",
        "max_fps": 30.0,
        "max_long_side": 1920,
        "max_short_side": 1080,
        "maxrate": "4500k",
        "bufsize": "9000k",
    },
}
DEFAULT_BURN_PROFILE = "stable"
SUBTITLE_SIZE_PRESETS = {
    "standard": {"label": "标准", "scale": 1.0},
    "large": {"label": "大号", "scale": 1.16},
    "douyin": {"label": "抖音醒目", "scale": 1.48},
}
DEFAULT_SUBTITLE_SIZE = "douyin"
DEFAULT_TRANSLATOR_LABEL = "AI中文字幕"
PROCESS_VERSION_TRANSLATION = "translation_v1"
PROCESS_VERSION_EDITING = "editing_v1"
PROCESS_VERSIONS = {PROCESS_VERSION_TRANSLATION, PROCESS_VERSION_EDITING}
ACTIVE_JOB_STATUSES = {"queued", "running"}
WORKFLOW_ERROR_LOCK_ACTIVE_JOB = "VF-LOCK-ACTIVE-JOB"
WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS = "VF-DELETE-DOWNLOAD-EXISTS"
WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS = "VF-DELETE-PROCESSED-EXISTS"
WORKFLOW_ERROR_BOOT_INTERRUPTED = "VF-WF-BOOT-INTERRUPTED"
WORKFLOW_ERROR_SHUTDOWN = "VF-WF-SHUTDOWN"

YOUTUBE_DEFAULT_QUERY = "foreigner China travel vlog first time in China"
YOUTUBE_FALLBACK_QUERIES = [
    "foreigner China travel vlog",
    "first time in China travel vlog foreigner",
    "American in China travel vlog",
    "British in China travel vlog",
]
