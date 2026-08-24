"""后端命名空间初始化:依赖导入、Flask 应用、CORS 与跨源写保护等。"""


import asyncio
import atexit
import base64
import datetime
import html
import json
import os
import random
import re
import signal
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
import math
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from queue import Empty, Queue
from flask_cors import CORS
from flask import Flask, request, jsonify, Response, render_template, send_from_directory, stream_with_context
from flask.json.provider import DefaultJSONProvider
from app.utils.format_util import _to_beijing_iso
from app.auth.middleware import register_auth_middleware
from werkzeug.utils import secure_filename
from app.utils.text_util import clean_display_text, ensure_utf8_stdio
from app.utils.ffmpeg_util import _resolve_ffmpeg_command, video_encode_args
from app.publishing import (
    BILIBILI_DEFAULT_TID,
    PUBLISH_TAG_LIMITS,
    bilibili_categories,
    merge_publish_tags,
    normalize_bilibili_tid,
    normalize_publish_targets,
    platform_name,
    platform_type_from_name,
)
from app.config import (
    ACTIVE_JOB_STATUSES,
    AGENT_BLOCK_LEVEL,
    AGENT_CHAT_MAX_TOKENS,
    AGENT_OUTPUT_MAX_TOKENS,
    AGENT_CHAT_TEMPERATURE,
    AGENT_CONTEXT_COMPACT_AFTER_CHARS,
    AGENT_CONTEXT_COMPACT_AFTER_MESSAGES,
    AGENT_CONTEXT_COMPACTION_RECOVERY_RATIO,
    AGENT_CONTEXT_COMPACTION_TRIGGER_RATIO,
    AGENT_CONTEXT_COMPACTION_TRIGGER_TOKENS,
    AGENT_CONTEXT_COMPACTION_RECOVERY_TOKENS,
    AGENT_CONTEXT_MODEL_WINDOW_TOKENS,
    AGENT_CONTEXT_INPUT_MAX_TOKENS,
    AGENT_CONTEXT_OUTPUT_MAX_TOKENS,
    AGENT_CONTEXT_MAX_INPUT_TOKENS,
    AGENT_CONTEXT_RECENT_MESSAGES,
    AGENT_CONTEXT_RECENT_TURNS,
    AGENT_CONTEXT_SUMMARY_MAX_CHARS,
    AGENT_CONTEXT_OUTPUT_RESERVE_TOKENS,
    AGENT_CONTEXT_TOOL_RESULT_MAX_CHARS,
    AGENT_CONTEXT_TOOL_TOTAL_MAX_CHARS,
    AGENT_ENABLED,
    AGENT_FRAME_END_OFFSET_SECONDS,
    AGENT_FRAME_FIRST_SECOND,
    AGENT_FRAME_MAX_COUNT,
    AGENT_FRAME_SAMPLE_RATIOS,
    AGENT_FRAME_SCALE_WIDTH,
    AGENT_GUARD_MAX_TOKENS,
    AGENT_GUARD_TEMPERATURE,
    AGENT_LLM_API_KEY,
    AGENT_LLM_BASE_URL,
    AGENT_LLM_ENABLE_THINKING,
    AGENT_LLM_MODEL,
    AGENT_LLM_PROVIDER,
    AGENT_HIGH_RISK_KEYWORDS,
    AGENT_MAX_TOOL_ROWS,
    AGENT_MAX_TOOL_CALLS,
    AGENT_REACT_MAX_STEPS,
    AGENT_MEDIUM_RISK_KEYWORDS,
    AGENT_REQUIRE_PREPUBLISH_CHECK,
    AGENT_REQUIRE_VISION_CHECK,
    AGENT_VISION_FAIL_CLOSED,
    BASE_DIR,
    BURN_PROFILES,
    CORS_ORIGINS,
    DEFAULT_BURN_PROFILE,
    DEFAULT_SUBTITLE_LANGUAGE,
    DEFAULT_SUBTITLE_SIZE,
    DEFAULT_TRANSLATOR_LABEL,
    DEFAULT_WATERMARK_TEXT,
    FFMPEG_COMMAND,
    PORT,
    LLM_MAX_TRANSCRIPT_CHARS,
    LLM_TIMEOUT,
    MULTIMODAL_LLM_API_KEY,
    MULTIMODAL_LLM_BASE_URL,
    MULTIMODAL_LLM_MODEL,
    PROCESS_VERSION_EDITING,
    PROCESS_VERSION_TRANSLATION,
    PROCESS_VERSIONS,
    SAU_COMMAND,
    SUBTITLE_COMMAND_TEMPLATE,
    SUBTITLE_LLM_REVIEW_ENABLED,
    SUBTITLE_LANGUAGES,
    SUBTITLE_SIZE_PRESETS,
    TRANSLATION_BATCH_MAX_CHARS,
    TRANSLATION_FALLBACK_LINE_LIMIT,
    TRANSLATION_REQUEST_TIMEOUT,
    TEXT_LLM_API_KEY,
    TEXT_LLM_BASE_URL,
    TEXT_LLM_MODEL,
    get_llm_config_status,
    WORKFLOW_MAX_ANALYSIS_JOBS,
    WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS,
    WORKFLOW_MAX_DOWNLOAD_JOBS,
    WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS,
    WORKFLOW_MAX_PROCESSING_JOBS,
    WORKFLOW_MAX_PROCESSING_QUEUED_JOBS,
    WORKFLOW_MAX_PUBLISH_JOBS,
    WORKFLOW_MAX_PUBLISH_QUEUED_JOBS,
    WORKFLOW_MAX_SEARCH_JOBS,
    WORKFLOW_MAX_SEARCH_QUEUED_JOBS,
    USER_STORAGE_QUOTA_MB,
    USER_UPLOAD_MAX_MB,
    WORKFLOW_ERROR_BOOT_INTERRUPTED,
    WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS,
    WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS,
    WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
    WORKFLOW_ERROR_SHUTDOWN,
    CANDIDATE_ANALYSIS_MAX_JOBS,
    CANDIDATE_ANALYSIS_MAX_QUEUED_JOBS,
    CANDIDATE_ANALYSIS_MAX_ITEMS,
    CANDIDATE_ANALYSIS_MAX_DURATION_SECONDS,
    YOUTUBE_DEFAULT_QUERY,
    YOUTUBE_DEFAULT_GROUP_NAME,
    YOUTUBE_DOWNLOAD_DIR,
    YOUTUBE_LEGACY_DEFAULT_QUERY,
    VIDEO_LOCAL_CLEANUP_BATCH_SIZE,
    VIDEO_LOCAL_CLEANUP_INTERVAL_HOURS,
    VIDEO_LOCAL_CLEANUP_MODE,
    VIDEO_LOCAL_RETENTION_SUCCESS_DAYS,
    VIDEO_LOCAL_RETENTION_DAYS,
    YOUTUBE_PROCESSED_DIR,
    YOUTUBE_TRANSCRIPT_DIR,
    YTDLP_JS_RUNTIME,
    YTDLP_JS_RUNTIME_PATH,
    YTDLP_PROXY,
    YTDLP_REMOTE_COMPONENTS,
    YOUTUBE_COOKIE_FILE,
    YOUTUBE_COOKIES_FROM_BROWSER,
    YOUTUBE_COOKIES_BROWSER_PROFILE,
    HF_PROXY,
    YTDLP_DOWNLOAD_RETRIES,
    YTDLP_FRAGMENT_RETRIES,
    YTDLP_DOWNLOAD_ATTEMPTS,
    YTDLP_SOCKET_TIMEOUT_SECONDS,
)
from app.utils.runtime_logger import configure_backend_logger

ensure_utf8_stdio()
backend_logger = configure_backend_logger(BASE_DIR)

try:
    from myUtils.auth import check_cookie
    from myUtils.login import get_tencent_cookie, douyin_cookie_gen, get_ks_cookie, xiaohongshu_cookie_gen
    from myUtils.postVideo import post_video_tencent, post_video_DouYin, post_video_ks, post_video_xhs
    from uploader.bilibili_uploader.runtime import ensure_biliup_binary
except ImportError as optional_import_error:
    print(f"平台登录/发布模块依赖未完整安装: {optional_import_error}")
    check_cookie = None
    get_tencent_cookie = None
    douyin_cookie_gen = None
    get_ks_cookie = None
    xiaohongshu_cookie_gen = None
    post_video_tencent = None
    post_video_DouYin = None
    post_video_ks = None
    post_video_xhs = None
    ensure_biliup_binary = None

active_queues = {}


class _VidferryJSONProvider(DefaultJSONProvider):
    def default(self, value):
        if isinstance(value, datetime.datetime):
            return _to_beijing_iso(value)
        if isinstance(value, (datetime.date, datetime.time)):
            return value.isoformat()
        return super().default(value)


app = Flask(__name__)
app.json = _VidferryJSONProvider(app)


# 默认仅允许本地前端访问，避免局域网/网页跨源调用本机敏感接口。
CORS(app, resources={r"/*": {"origins": CORS_ORIGINS}}, supports_credentials=True)


def _request_origin_allowed():
    allowed = set(CORS_ORIGINS)
    allowed.update({
        f"http://127.0.0.1:{PORT}",
        f"http://localhost:{PORT}",
    })
    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if not referer:
            return True
        parsed = urllib.parse.urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    # 本机优先、单机部署：允许本机回环地址上任意端口的前端跨源写
    # （dev 下前端与后端端口不同，如 5273 ↔ 5409）；局域网/公网来源仍需命中白名单。
    if urllib.parse.urlparse(origin).hostname in {"127.0.0.1", "localhost", "::1"}:
        return True
    return origin in allowed


@app.before_request
def reject_cross_origin_writes():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _request_origin_allowed():
        return jsonify({"code": 403, "msg": "跨来源请求被拒绝", "data": None}), 403


register_auth_middleware(app)

# 上传请求体硬限制，早于媒体解析和磁盘配额校验生效。
app.config['MAX_CONTENT_LENGTH'] = USER_UPLOAD_MAX_MB * 1024 * 1024


