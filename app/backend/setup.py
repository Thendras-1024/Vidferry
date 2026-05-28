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
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from queue import Queue
from flask_cors import CORS
from flask import Flask, request, jsonify, Response, render_template, send_from_directory
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
    BASE_DIR,
    BURN_PROFILES,
    DEFAULT_BURN_PROFILE,
    DEFAULT_SUBTITLE_LANGUAGE,
    DEFAULT_SUBTITLE_SIZE,
    DEFAULT_TRANSLATOR_LABEL,
    FFMPEG_COMMAND,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TRANSCRIPT_CHARS,
    LLM_MODEL,
    LLM_TIMEOUT,
    PROCESS_VERSION_EDITING,
    PROCESS_VERSION_TRANSLATION,
    PROCESS_VERSIONS,
    SAU_COMMAND,
    SUBTITLE_COMMAND_TEMPLATE,
    SUBTITLE_LANGUAGES,
    SUBTITLE_SIZE_PRESETS,
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

#允许所有来源跨域访问
CORS(app)

# 限制上传文件大小为160MB
app.config['MAX_CONTENT_LENGTH'] = 160 * 1024 * 1024


