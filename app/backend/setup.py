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
import sqlite3
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
from werkzeug.utils import secure_filename
from app.utils.text_util import clean_display_text, ensure_utf8_stdio
from app.publishing import (
    BILIBILI_DEFAULT_TID,
    bilibili_categories,
    normalize_bilibili_tid,
    normalize_publish_targets,
    platform_name,
    platform_type_from_name,
)
from app.config import (
    ACTIVE_JOB_STATUSES,
    AGENT_BLOCK_LEVEL,
    AGENT_CHAT_MAX_TOKENS,
    AGENT_CHAT_MODEL,
    AGENT_CHAT_TEMPERATURE,
    AGENT_CONTEXT_COMPACT_AFTER_CHARS,
    AGENT_CONTEXT_COMPACT_AFTER_MESSAGES,
    AGENT_CONTEXT_RECENT_MESSAGES,
    AGENT_CONTEXT_SUMMARY_MAX_CHARS,
    AGENT_ENABLED,
    AGENT_FRAME_END_OFFSET_SECONDS,
    AGENT_FRAME_FIRST_SECOND,
    AGENT_FRAME_MAX_COUNT,
    AGENT_FRAME_SAMPLE_RATIOS,
    AGENT_FRAME_SCALE_WIDTH,
    AGENT_GUARD_MAX_TOKENS,
    AGENT_GUARD_TEMPERATURE,
    AGENT_HIGH_RISK_KEYWORDS,
    AGENT_MAX_TOOL_ROWS,
    AGENT_MAX_TOOL_CALLS,
    AGENT_REACT_MAX_STEPS,
    AGENT_MEDIUM_RISK_KEYWORDS,
    AGENT_REQUIRE_PREPUBLISH_CHECK,
    AGENT_REQUIRE_VISION_CHECK,
    AGENT_VISION_FAIL_CLOSED,
    AGENT_VISION_MODEL,
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
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TRANSCRIPT_CHARS,
    LLM_MODEL,
    LLM_TIMEOUT,
    PROCESS_VERSION_EDITING,
    PROCESS_VERSION_TRANSLATION,
    PROCESS_VERSIONS,
    SAU_COMMAND,
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_ENABLE_WAL,
    SUBTITLE_COMMAND_TEMPLATE,
    SUBTITLE_LANGUAGES,
    SUBTITLE_SIZE_PRESETS,
    WORKFLOW_MAX_ANALYSIS_JOBS,
    WORKFLOW_MAX_DOWNLOAD_JOBS,
    WORKFLOW_MAX_PROCESSING_JOBS,
    WORKFLOW_MAX_SEARCH_JOBS,
    WORKFLOW_ERROR_BOOT_INTERRUPTED,
    WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS,
    WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS,
    WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
    WORKFLOW_ERROR_SHUTDOWN,
    YOUTUBE_DEFAULT_QUERY,
    YOUTUBE_DOWNLOAD_DIR,
    YOUTUBE_FALLBACK_QUERIES,
    YOUTUBE_PROCESSED_DIR,
    YOUTUBE_TRANSCRIPT_DIR,
    YTDLP_JS_RUNTIME,
    YTDLP_JS_RUNTIME_PATH,
    YTDLP_REMOTE_COMPONENTS,
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
app = Flask(__name__)


def _bootstrap_local_tool_path():
    scripts_dir = Path(BASE_DIR / ".venv" / "Scripts")
    if not scripts_dir.is_dir():
        return
    current_path = os.environ.get("PATH", "")
    paths = [item for item in current_path.split(os.pathsep) if item]
    scripts_text = str(scripts_dir)
    if not any(Path(item).resolve() == scripts_dir.resolve() for item in paths if Path(item).exists()):
        os.environ["PATH"] = scripts_text + os.pathsep + current_path


_bootstrap_local_tool_path()

# 默认仅允许本地前端访问，避免局域网/网页跨源调用本机敏感接口。
CORS(app, resources={r"/*": {"origins": CORS_ORIGINS}})


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
    return origin in allowed


@app.before_request
def reject_cross_origin_writes():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _request_origin_allowed():
        return jsonify({"code": 403, "msg": "跨来源请求被拒绝", "data": None}), 403

# 限制上传文件大小为160MB
app.config['MAX_CONTENT_LENGTH'] = 160 * 1024 * 1024


