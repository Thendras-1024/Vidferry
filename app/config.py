"""应用配置值。"""

from __future__ import annotations

import os
import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from app.utils.text_util import ensure_utf8_stdio
from app.core.llm_provider import normalize_provider, probe_provider, provider_optional_fields
from conf import BASE_DIR, INTERNAL_CONFIG


ensure_utf8_stdio()

APP_VERSION = "0.2.0"
HOST = os.getenv("VIDFERRY_HOST", "127.0.0.1")
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
        if key not in os.environ or not os.environ.get(key, "").strip():
            os.environ[key] = value


_load_local_env()


def _internal_default(name, fallback):
    return INTERNAL_CONFIG.get(name, fallback)


def _env_text(name, default=""):
    return str(os.environ.get(name, _internal_default(name, default)) or "").strip()

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
    # 未提供 conf.py 时,默认用 PATH 中的 sau(需已激活对应 Python 环境,如 conda activate vidferry)。
    SAU_COMMAND = "sau"
    SUBTITLE_COMMAND_TEMPLATE = ""
    YOUTUBE_DOWNLOAD_DIR = Path(BASE_DIR / "videos" / "youtube")
    YOUTUBE_PROCESSED_DIR = Path(BASE_DIR / "videos" / "processed")

YOUTUBE_DOWNLOAD_DIR = Path(os.environ.get("YOUTUBE_DOWNLOAD_DIR", str(YOUTUBE_DOWNLOAD_DIR)))
YOUTUBE_PROCESSED_DIR = Path(os.environ.get("YOUTUBE_PROCESSED_DIR", str(YOUTUBE_PROCESSED_DIR)))
YOUTUBE_TRANSCRIPT_DIR = Path(os.environ.get("YOUTUBE_TRANSCRIPT_DIR", str(BASE_DIR / "videos" / "transcripts")))
YTDLP_JS_RUNTIME = _env_text("YTDLP_JS_RUNTIME")
YTDLP_JS_RUNTIME_PATH = _env_text("YTDLP_JS_RUNTIME_PATH")
YTDLP_PROXY = _env_text("YTDLP_PROXY")
HF_PROXY = _env_text("HF_PROXY")
# Leave YTDLP_PROXY empty to use yt-dlp's system proxy discovery.
if HF_PROXY:
    for _proxy_env_name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        os.environ[_proxy_env_name] = HF_PROXY
YTDLP_REMOTE_COMPONENTS = [
    item.strip()
    for item in _env_text("YTDLP_REMOTE_COMPONENTS", "ejs:github").split(",")
    if item.strip()
]

def _env_with_legacy(name, legacy_name, default=""):
    return _env_text(name) or _env_text(legacy_name, default)


# New names take precedence. Legacy names keep existing deployments working during migration.
TEXT_LLM_API_KEY = _env_with_legacy("TEXT_LLM_API_KEY", "LLM_API_KEY")
TEXT_LLM_BASE_URL = _env_with_legacy("TEXT_LLM_BASE_URL", "LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
TEXT_LLM_MODEL = _env_text("TEXT_LLM_MODEL") or _env_text("LLM_MODEL") or _env_text("AGENT_CHAT_MODEL", "gpt-4o-mini")
TEXT_LLM_PROVIDER = _env_text("TEXT_LLM_PROVIDER", "auto")
MULTIMODAL_LLM_API_KEY = _env_with_legacy("MULTIMODAL_LLM_API_KEY", "LLM_API_KEY")
MULTIMODAL_LLM_BASE_URL = _env_with_legacy("MULTIMODAL_LLM_BASE_URL", "LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MULTIMODAL_LLM_MODEL = _env_with_legacy("MULTIMODAL_LLM_MODEL", "AGENT_VISION_MODEL")
MULTIMODAL_LLM_PROVIDER = _env_text("MULTIMODAL_LLM_PROVIDER", "auto")
# 兼容旧测试与外部脚本；新代码应使用 TEXT_LLM_* / MULTIMODAL_LLM_*。
LLM_API_KEY = TEXT_LLM_API_KEY
LLM_BASE_URL = TEXT_LLM_BASE_URL
LLM_MODEL = TEXT_LLM_MODEL
LLM_TIMEOUT = int(_env_text("LLM_TIMEOUT", 180) or 180)
LLM_MAX_TRANSCRIPT_CHARS = int(_env_text("LLM_MAX_TRANSCRIPT_CHARS", 28000) or 28000)

def _env_bool(name, default=False):
    value = _env_text(name, "1" if default else "0").lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_int(name, default, minimum=None, maximum=None):
    try:
        default = _internal_default(name, default)
        value = int(_env_text(name, default) or default)
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


SUBTITLE_LLM_REVIEW_ENABLED = _env_bool("SUBTITLE_LLM_REVIEW_ENABLED", True)
# 修订批次字符上限与并发数：与翻译阶段 TRANSLATION_BATCH_MAX_CHARS 解耦，
# 独立调小可降低单批 JSON 出错率；并发用于抵消批数增多带来的耗时。
SUBTITLE_REVIEW_BATCH_MAX_CHARS = _env_int("SUBTITLE_REVIEW_BATCH_MAX_CHARS", 800, minimum=200, maximum=4000)
SUBTITLE_REVIEW_CONCURRENCY = _env_int("SUBTITLE_REVIEW_CONCURRENCY", 4, minimum=1, maximum=16)
SUBTITLE_REVIEW_MAX_TOKENS = _env_int("SUBTITLE_REVIEW_MAX_TOKENS", 4000, minimum=512, maximum=8000)
VIDEO_ENCODER = os.environ.get("VIDEO_ENCODER", "libx264").strip().lower() or "libx264"
VIDEO_NVENC_PRESET = os.environ.get("VIDEO_NVENC_PRESET", "p5").strip().lower() or "p5"
VIDEO_NVENC_CQ = _env_int("VIDEO_NVENC_CQ", 23, minimum=0, maximum=51)


def _env_float(name, default, minimum=None, maximum=None):
    try:
        default = _internal_default(name, default)
        value = float(_env_text(name, default) or default)
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


TRANSLATION_BATCH_MAX_CHARS = _env_int("TRANSLATION_BATCH_MAX_CHARS", 1200)
TRANSLATION_REQUEST_TIMEOUT = _env_float("TRANSLATION_REQUEST_TIMEOUT", 10)
TRANSLATION_FALLBACK_LINE_LIMIT = _env_int("TRANSLATION_FALLBACK_LINE_LIMIT", 5)


def _env_csv(name, default):
    raw = _env_text(name, default)
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _env_keyword_map(name, default):
    pairs = {}
    for item in _env_csv(name, default):
        if ":" in item:
            keyword, category = item.split(":", 1)
        else:
            keyword, category = item, "内容风险"
        keyword = keyword.strip()
        category = category.strip() or "内容风险"
        if keyword:
            pairs[keyword] = category
    return pairs


def _env_float_list(name, default, minimum=None, maximum=None):
    values = []
    for item in _env_csv(name, default):
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        values.append(value)
    return values


AGENT_ENABLED = _env_bool("AGENT_ENABLED", True)
AGENT_REQUIRE_PREPUBLISH_CHECK = _env_bool("AGENT_REQUIRE_PREPUBLISH_CHECK", True)
AGENT_BLOCK_LEVEL = _env_text("AGENT_BLOCK_LEVEL", "high").lower() or "high"
AGENT_MAX_TOOL_ROWS = max(1, min(_env_int("AGENT_MAX_TOOL_ROWS", 20), 50))
AGENT_MAX_TOOL_CALLS = _env_int("AGENT_MAX_TOOL_CALLS", 5, 1, 12)
AGENT_REACT_MAX_STEPS = _env_int("AGENT_REACT_MAX_STEPS", 6, 1, 20)
AGENT_CHAT_TEMPERATURE = _env_float("AGENT_CHAT_TEMPERATURE", 0.2, 0, 2)
AGENT_CHAT_MAX_TOKENS = _env_int("AGENT_CHAT_MAX_TOKENS", 5000, 128, 8000)
AGENT_CONTEXT_RECENT_MESSAGES = _env_int("AGENT_CONTEXT_RECENT_MESSAGES", 8, 2, 20)
AGENT_CONTEXT_COMPACT_AFTER_MESSAGES = _env_int("AGENT_CONTEXT_COMPACT_AFTER_MESSAGES", 12, 4, 100)
AGENT_CONTEXT_COMPACT_AFTER_CHARS = _env_int("AGENT_CONTEXT_COMPACT_AFTER_CHARS", 16000, 4000, 200000)
AGENT_CONTEXT_SUMMARY_MAX_CHARS = _env_int("AGENT_CONTEXT_SUMMARY_MAX_CHARS", 4000, 500, 20000)
AGENT_GUARD_TEMPERATURE = _env_float("AGENT_GUARD_TEMPERATURE", 0, 0, 2)
AGENT_GUARD_MAX_TOKENS = _env_int("AGENT_GUARD_MAX_TOKENS", 900, 128, 8000)
AGENT_REQUIRE_VISION_CHECK = _env_bool("AGENT_REQUIRE_VISION_CHECK", True)
AGENT_VISION_FAIL_CLOSED = _env_bool("AGENT_VISION_FAIL_CLOSED", True)
AGENT_FRAME_MAX_COUNT = _env_int("AGENT_FRAME_MAX_COUNT", 8, 1, 16)
AGENT_FRAME_SCALE_WIDTH = _env_int("AGENT_FRAME_SCALE_WIDTH", 640, 160, 1920)
AGENT_FRAME_FIRST_SECOND = _env_float("AGENT_FRAME_FIRST_SECOND", 60, 0.1, None)
AGENT_FRAME_END_OFFSET_SECONDS = _env_float("AGENT_FRAME_END_OFFSET_SECONDS", 2, 0, None)
AGENT_FRAME_SAMPLE_RATIOS = _env_float_list("AGENT_FRAME_SAMPLE_RATIOS", "0.25,0.5,0.75", 0, 1) or [0.25, 0.5, 0.75]
AGENT_HIGH_RISK_KEYWORDS = _env_keyword_map(
    "AGENT_HIGH_RISK_KEYWORDS",
    "",
)
AGENT_MEDIUM_RISK_KEYWORDS = _env_keyword_map(
    "AGENT_MEDIUM_RISK_KEYWORDS",
    "",
)
AUTH_IDLE_TIMEOUT_MINUTES = _env_int("VIDFERRY_AUTH_IDLE_MINUTES", 480, 15, 1440)
AUTH_ABSOLUTE_TIMEOUT_HOURS = _env_int("VIDFERRY_AUTH_ABSOLUTE_HOURS", 24, 1, 168)
AUTH_REMEMBER_TIMEOUT_HOURS = _env_int("VIDFERRY_AUTH_REMEMBER_HOURS", 168, 24, 168)
AUTH_MAX_LOGIN_FAILURES = _env_int("VIDFERRY_AUTH_MAX_FAILURES", 5, 3, 20)
AUTH_LOCK_MINUTES = _env_int("VIDFERRY_AUTH_LOCK_MINUTES", 15, 1, 1440)
AUTH_COOKIE_SECURE = _env_bool("VIDFERRY_AUTH_COOKIE_SECURE", False)
AUTH_COOKIE_NAME = "__Host-vidferry_session" if AUTH_COOKIE_SECURE else "vidferry_session"
AUTH_CSRF_SECRET = _env_text("VIDFERRY_AUTH_SECRET") or secrets.token_urlsafe(48)
AUTH_ALLOW_COOKIE_EXPORT = _env_bool("VIDFERRY_AUTH_ALLOW_COOKIE_EXPORT", False)
DATABASE_URL = _env_text("DATABASE_URL")
DATABASE_POOL_MIN_SIZE = _env_int("DATABASE_POOL_MIN_SIZE", 1, 1, 20)
DATABASE_POOL_MAX_SIZE = _env_int("DATABASE_POOL_MAX_SIZE", 8, 1, 50)
DATABASE_POOL_MAX_SIZE = max(DATABASE_POOL_MIN_SIZE, DATABASE_POOL_MAX_SIZE)
DATABASE_POOL_TIMEOUT_SECONDS = _env_int("DATABASE_POOL_TIMEOUT_SECONDS", 30, 1, 120)
FEISHU_BUTLER_CONSOLE_URL = _env_text("FEISHU_BUTLER_CONSOLE_URL", "http://127.0.0.1:55173").rstrip("/")
FEISHU_ROBOT_ENABLED = _env_bool("FEISHU_ROBOT_ENABLED", False)
FEISHU_AGENT_OWNER_USER_ID = _env_int("FEISHU_AGENT_OWNER_USER_ID", 0, 0, 2147483647)
WORKFLOW_MAX_DOWNLOAD_JOBS = max(1, _env_int("WORKFLOW_MAX_DOWNLOAD_JOBS", 2))
WORKFLOW_MAX_PROCESSING_JOBS = max(1, _env_int("WORKFLOW_MAX_PROCESSING_JOBS", 1))
WORKFLOW_MAX_PUBLISH_JOBS = max(1, _env_int("WORKFLOW_MAX_PUBLISH_JOBS", 2))
WORKFLOW_MAX_ANALYSIS_JOBS = max(1, _env_int("WORKFLOW_MAX_ANALYSIS_JOBS", 2))
WORKFLOW_MAX_COMMENT_JOBS = max(1, _env_int("WORKFLOW_MAX_COMMENT_JOBS", 1))
WORKFLOW_MAX_SEARCH_JOBS = max(1, _env_int("WORKFLOW_MAX_SEARCH_JOBS", 2))
WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS = _env_int("WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS", 4, 0, 64)
WORKFLOW_MAX_PROCESSING_QUEUED_JOBS = _env_int("WORKFLOW_MAX_PROCESSING_QUEUED_JOBS", 2, 0, 64)
WORKFLOW_MAX_PUBLISH_QUEUED_JOBS = _env_int("WORKFLOW_MAX_PUBLISH_QUEUED_JOBS", 4, 0, 64)
WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS = _env_int("WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS", 4, 0, 64)
WORKFLOW_MAX_COMMENT_QUEUED_JOBS = _env_int("WORKFLOW_MAX_COMMENT_QUEUED_JOBS", 2, 0, 64)
WORKFLOW_MAX_SEARCH_QUEUED_JOBS = _env_int("WORKFLOW_MAX_SEARCH_QUEUED_JOBS", 4, 0, 64)
_LLM_CONFIG_STATUS_CACHE = None


def _build_llm_config_status(ready, missing=None, message=""):
    return {
        "ready": bool(ready),
        "checked": True,
        "missing": missing or [],
        "message": message,
    }


def _format_llm_probe_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body[:200] if body else exc.reason
        return f"HTTP {exc.code}: {detail}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason or exc)[:200]
    return str(exc)[:200]


LLM_DISABLE_THINKING = _env_bool("LLM_DISABLE_THINKING", True)


def llm_disable_thinking_params(base_url, provider="auto"):
    return provider_optional_fields(normalize_provider(provider, base_url), LLM_DISABLE_THINKING, structured=False)


def _get_model_config_status(api_key, base_url, model, provider="auto", *, multimodal=False):
    prefix = "MULTIMODAL_LLM" if multimodal else "TEXT_LLM"
    label = "多模态模型" if multimodal else "文本模型"
    missing = []
    if not api_key:
        missing.append(f"{prefix}_API_KEY")
    if not base_url:
        missing.append(f"{prefix}_BASE_URL")
    if not model:
        missing.append(f"{prefix}_MODEL")
    if missing:
        return _build_llm_config_status(
            False,
            missing,
            f"{label}不可用：缺少 {', '.join(missing)}。请在 .env 或环境变量中配置后重启后端。",
        )

    profile = probe_provider(
        model, api_key, base_url, provider, min(LLM_TIMEOUT, 10),
        multimodal=multimodal, disable_thinking=LLM_DISABLE_THINKING,
    )
    if profile["ready"]:
        return {**profile, **_build_llm_config_status(True, [], "")}
    return {
        **profile,
        **_build_llm_config_status(False, [], f"{label}配置存在但模型接口不可用：{profile['message']}。请检查 {prefix}_PROVIDER、{prefix}_BASE_URL、{prefix}_MODEL、{prefix}_API_KEY 后重启后端。"),
    }


def get_llm_config_status():
    global _LLM_CONFIG_STATUS_CACHE
    if _LLM_CONFIG_STATUS_CACHE is not None:
        return _LLM_CONFIG_STATUS_CACHE

    text_status = _get_model_config_status(
        TEXT_LLM_API_KEY, TEXT_LLM_BASE_URL, TEXT_LLM_MODEL, TEXT_LLM_PROVIDER,
    )
    multimodal_status = _get_model_config_status(
        MULTIMODAL_LLM_API_KEY, MULTIMODAL_LLM_BASE_URL, MULTIMODAL_LLM_MODEL, MULTIMODAL_LLM_PROVIDER,
        multimodal=True,
    )
    _LLM_CONFIG_STATUS_CACHE = {
        "text": text_status,
        "multimodal": multimodal_status,
        "ready": text_status["ready"] and multimodal_status["ready"],
        "missing": text_status.get("missing", []),
        "message": text_status.get("message", ""),
    }
    return _LLM_CONFIG_STATUS_CACHE


def llm_provider_profile(model, api_key, base_url, provider="auto"):
    """业务调用使用已探测的 profile；未匹配配置时按 Provider 默认字段请求。"""
    if model == TEXT_LLM_MODEL and api_key == TEXT_LLM_API_KEY and base_url == TEXT_LLM_BASE_URL:
        return (get_llm_config_status() or {}).get("text") or {}
    if model == MULTIMODAL_LLM_MODEL and api_key == MULTIMODAL_LLM_API_KEY and base_url == MULTIMODAL_LLM_BASE_URL:
        return (get_llm_config_status() or {}).get("multimodal") or {}
    return {"provider": normalize_provider(provider, base_url), "removedOptionalFields": []}
CORS_ORIGINS = [
    item.strip()
    for item in os.environ.get(
        "VIDFERRY_CORS_ORIGINS",
        "http://127.0.0.1:55173,http://localhost:55173",
    ).split(",")
    if item.strip()
]

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
    "2k": {
        "preset": "fast",
        "crf": "21",
        "max_fps": 30.0,
        "max_long_side": 2560,
        "max_short_side": 1440,
        "maxrate": "12000k",
        "bufsize": "24000k",
        "h264_level": "5.0",
    },
}
DEFAULT_BURN_PROFILE = "stable"
SUBTITLE_SIZE_PRESETS = {
    "standard": {"label": "标准", "scale": 1.0},
    "large": {"label": "大号（抖音推荐）", "scale": 1.06},
    "douyin": {"label": "超大号", "scale": 1.48},
}
DEFAULT_SUBTITLE_SIZE = "large"
DEFAULT_TRANSLATOR_LABEL = "Vidferry"
DEFAULT_WATERMARK_TEXT = "Vidferry"
PROCESS_VERSION_TRANSLATION = "translation_v1"
PROCESS_VERSION_EDITING = "editing_v1"
PROCESS_VERSIONS = {PROCESS_VERSION_TRANSLATION, PROCESS_VERSION_EDITING}
ACTIVE_JOB_STATUSES = {"queued", "running"}
WORKFLOW_ERROR_LOCK_ACTIVE_JOB = "VF-LOCK-ACTIVE-JOB"
WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS = "VF-DELETE-DOWNLOAD-EXISTS"
WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS = "VF-DELETE-PROCESSED-EXISTS"
WORKFLOW_ERROR_BOOT_INTERRUPTED = "VF-WF-BOOT-INTERRUPTED"
WORKFLOW_ERROR_SHUTDOWN = "VF-WF-SHUTDOWN"

YOUTUBE_DEFAULT_QUERY = "China technology innovation"
YOUTUBE_LEGACY_DEFAULT_QUERY = "foreigner China travel vlog first time in China"
YOUTUBE_DEFAULT_GROUP_NAME = "未分类"
