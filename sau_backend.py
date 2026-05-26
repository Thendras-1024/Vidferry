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
import threading
import time
import uuid
import wave
import math
import urllib.parse
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from queue import Queue
from flask_cors import CORS
from flask import Flask, request, jsonify, Response, render_template, send_from_directory
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


class NoSpeechDetectedError(RuntimeError):
    pass


@app.before_request
def ensure_database_tables():
    init_youtube_workflow_table()

def _parse_upload_date(value):
    if not value:
        return ""
    text = str(value)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _format_iso_date(value):
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else value


def _format_count(value):
    if value is None or value == "":
        return ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,}"


def _format_subscribers_w(value):
    if value is None or value == "":
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith("w"):
        return text

    normalized = text.lower()
    normalized = normalized.replace(",", "").replace("subscribers", "").replace("subscriber", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return text

    number = float(match.group(1))
    number_unit_pattern = rf"{re.escape(match.group(1))}\s*([kmw])\b"
    unit_match = re.search(number_unit_pattern, normalized)
    unit = unit_match.group(1) if unit_match else ""

    if "万" in normalized or unit == "w":
        count = number * 10000
    elif "million" in normalized or unit == "m":
        count = number * 1000000
    elif "thousand" in normalized or unit == "k":
        count = number * 1000
    else:
        count = number

    wan = count / 10000
    precision = 2 if 0 < wan < 0.1 else 1
    formatted = f"{wan:.{precision}f}".rstrip("0").rstrip(".")
    return f"{formatted}w"


def _db_path():
    return Path(BASE_DIR / "db" / "database.db")


def _json_response(code=200, msg="success", data=None, status=200):
    return jsonify({"code": code, "msg": msg, "data": data}), status


def _clean_unique_list(values):
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


class WorkflowConflictError(ValueError):
    def __init__(self, message, error_code, error_type="WORKFLOW_CONFLICT", data=None):
        super().__init__(message)
        self.error_code = error_code
        self.error_type = error_type
        self.data = data or {}


def _error_response(status, message, error_code, error_type="", data=None):
    payload = {
        "errorCode": error_code,
        "errorType": error_type or error_code,
        **(data or {}),
    }
    return _json_response(status, message, payload, status)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _parse_json_object(raw_value):
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {"raw": str(raw_value)}


def _clean_topic_list(value):
    if not isinstance(value, list):
        return []
    topics = []
    for item in value:
        topic = str(item or "").strip().lstrip("#")
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def _build_default_publish_draft(analysis_result):
    result = analysis_result if isinstance(analysis_result, dict) else {}
    title_options = [
        str(title or "").strip()
        for title in (result.get("title_options") if isinstance(result.get("title_options"), list) else [])
        if str(title or "").strip()
    ]
    selected_title = random.choice(title_options) if title_options else ""
    return {
        "title": selected_title,
        "description": str(result.get("publish_copy") or "").strip(),
        "tags": _clean_topic_list(result.get("tags")),
        "source": "llm_default",
        "updatedAt": _now_iso(),
    }


def _parse_publish_draft(raw_value, analysis_result=None):
    draft = _parse_json_object(raw_value)
    if not draft:
        return {}
    return {
        "title": str(draft.get("title") or "").strip(),
        "description": str(draft.get("description") or "").strip(),
        "tags": _clean_topic_list(draft.get("tags")),
        "source": str(draft.get("source") or "").strip(),
        "updatedAt": str(draft.get("updatedAt") or "").strip(),
    }


def init_database_tables():
    Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type INTEGER NOT NULL,
            filePath TEXT NOT NULL,
            userName TEXT NOT NULL,
            status INTEGER DEFAULT 0
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT,
            filename TEXT NOT NULL,
            original_filename TEXT,
            filesize REAL,
            upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT,
            storage_key TEXT,
            storage_backend TEXT DEFAULT 'local',
            source_type TEXT DEFAULT 'manual_upload',
            source_video_id TEXT,
            status TEXT DEFAULT 'ready',
            duration TEXT,
            duration_seconds REAL DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        )
        ''')
        cursor.execute("PRAGMA table_info(file_records)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        material_columns = {
            "asset_id": "TEXT",
            "original_filename": "TEXT",
            "storage_key": "TEXT",
            "storage_backend": "TEXT DEFAULT 'local'",
            "source_type": "TEXT DEFAULT 'manual_upload'",
            "source_video_id": "TEXT",
            "status": "TEXT DEFAULT 'ready'",
            "duration": "TEXT",
            "duration_seconds": "REAL DEFAULT 0",
            "metadata": "TEXT DEFAULT '{}'",
        }
        for column, definition in material_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE file_records ADD COLUMN {column} {definition}")
        cursor.execute("UPDATE file_records SET asset_id = lower(hex(randomblob(16))) WHERE asset_id IS NULL OR asset_id = ''")
        cursor.execute("UPDATE file_records SET original_filename = filename WHERE original_filename IS NULL OR original_filename = ''")
        cursor.execute("UPDATE file_records SET storage_key = file_path WHERE storage_key IS NULL OR storage_key = ''")
        cursor.execute("UPDATE file_records SET storage_backend = 'local' WHERE storage_backend IS NULL OR storage_backend = ''")
        cursor.execute("UPDATE file_records SET source_type = 'manual_upload' WHERE source_type IS NULL OR source_type = ''")
        cursor.execute("UPDATE file_records SET status = 'ready' WHERE status IS NULL OR status = ''")
        cursor.execute("UPDATE file_records SET metadata = '{}' WHERE metadata IS NULL OR metadata = ''")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_records_asset_id ON file_records(asset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_video_id ON file_records(source_video_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_type ON file_records(source_type)")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_workflow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            video_id TEXT,
            stage TEXT NOT NULL,
            stage_label TEXT,
            status TEXT DEFAULT 'running',
            message TEXT,
            input_file_path TEXT,
            output_file_path TEXT,
            input_size_mb REAL DEFAULT 0,
            output_size_mb REAL DEFAULT 0,
            started_at DATETIME,
            ended_at DATETIME,
            duration_seconds REAL DEFAULT 0,
            cloud_model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cloud_latency_ms REAL DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_workflow_events)")
        existing_event_columns = {row[1] for row in cursor.fetchall()}
        event_columns = {
            "video_id": "TEXT",
            "stage_label": "TEXT",
            "status": "TEXT DEFAULT 'running'",
            "message": "TEXT",
            "input_file_path": "TEXT",
            "output_file_path": "TEXT",
            "input_size_mb": "REAL DEFAULT 0",
            "output_size_mb": "REAL DEFAULT 0",
            "started_at": "DATETIME",
            "ended_at": "DATETIME",
            "duration_seconds": "REAL DEFAULT 0",
            "cloud_model": "TEXT",
            "prompt_tokens": "INTEGER DEFAULT 0",
            "completion_tokens": "INTEGER DEFAULT 0",
            "total_tokens": "INTEGER DEFAULT 0",
            "cloud_latency_ms": "REAL DEFAULT 0",
            "metadata": "TEXT DEFAULT '{}'",
            "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
        }
        for column, definition in event_columns.items():
            if column not in existing_event_columns:
                cursor.execute(f"ALTER TABLE youtube_workflow_events ADD COLUMN {column} {definition}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_job_id ON youtube_workflow_events(job_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_video_id ON youtube_workflow_events(video_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_stage ON youtube_workflow_events(stage)")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS published_youtube_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            source_url TEXT,
            title TEXT,
            platform TEXT,
            account_count INTEGER DEFAULT 0,
            material_id INTEGER,
            filename TEXT,
            file_path TEXT,
            filesize REAL DEFAULT 0,
            thumbnail TEXT,
            channel TEXT,
            subscribers TEXT,
            source_published_at TEXT,
            publish_title TEXT,
            metadata TEXT DEFAULT '{}',
            published_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(published_youtube_materials)")
        existing_published_columns = {row[1] for row in cursor.fetchall()}
        published_columns = {
            "video_id": "TEXT",
            "source_url": "TEXT",
            "title": "TEXT",
            "platform": "TEXT",
            "account_count": "INTEGER DEFAULT 0",
            "material_id": "INTEGER",
            "filename": "TEXT",
            "file_path": "TEXT",
            "filesize": "REAL DEFAULT 0",
            "thumbnail": "TEXT",
            "channel": "TEXT",
            "subscribers": "TEXT",
            "source_published_at": "TEXT",
            "publish_title": "TEXT",
            "metadata": "TEXT DEFAULT '{}'",
            "published_at": "DATETIME",
            "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
        }
        for column, definition in published_columns.items():
            if column not in existing_published_columns:
                cursor.execute(f"ALTER TABLE published_youtube_materials ADD COLUMN {column} {definition}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_video_id ON published_youtube_materials(video_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_source_url ON published_youtube_materials(source_url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_published_at ON published_youtube_materials(published_at)")
        conn.commit()


def init_youtube_video_table():
    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            title TEXT,
            channel TEXT,
            subscribers TEXT,
            published_at TEXT,
            url TEXT NOT NULL,
            thumbnail TEXT,
            duration TEXT,
            query TEXT,
            download_status INTEGER DEFAULT 0,
            publish_status INTEGER DEFAULT 0,
            translate_status INTEGER DEFAULT 0,
            downloaded_file_path TEXT,
            processed_file_path TEXT,
            transcript_status INTEGER DEFAULT 0,
            transcript_file_path TEXT,
            transcript_language TEXT,
            analysis_status INTEGER DEFAULT 0,
            analysis_result TEXT,
            publish_draft TEXT,
            analysis_updated_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_videos)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        video_columns = {
            "translate_status": "INTEGER DEFAULT 0",
            "processed_file_path": "TEXT",
            "transcript_status": "INTEGER DEFAULT 0",
            "transcript_file_path": "TEXT",
            "transcript_language": "TEXT",
            "analysis_status": "INTEGER DEFAULT 0",
            "analysis_result": "TEXT",
            "publish_draft": "TEXT",
            "analysis_updated_at": "DATETIME",
        }
        for column, definition in video_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE youtube_videos ADD COLUMN {column} {definition}")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_download_status ON youtube_videos(download_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_publish_status ON youtube_videos(publish_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_translate_status ON youtube_videos(translate_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_analysis_status ON youtube_videos(analysis_status)')
        conn.commit()


def init_youtube_workflow_table():
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_workflow_jobs (
            id TEXT PRIMARY KEY,
            video_id TEXT,
            url TEXT NOT NULL,
            account TEXT,
            channel TEXT,
            subscribers TEXT,
            published_at TEXT,
            bilibili_account TEXT,
            bilibili_tid INTEGER DEFAULT 249,
            publish_to_douyin INTEGER DEFAULT 1,
            publish_to_bilibili INTEGER DEFAULT 0,
            process_version TEXT DEFAULT 'translation_v1',
            subtitle_language TEXT DEFAULT 'zh-CN',
            burn_profile TEXT DEFAULT 'stable',
            subtitle_size TEXT DEFAULT 'douyin',
            translator_label TEXT DEFAULT 'AI中文字幕',
            title TEXT,
            description TEXT,
            tags TEXT,
            schedule TEXT,
            status TEXT NOT NULL,
            step TEXT,
            message TEXT,
            source_file_path TEXT,
            processed_file_path TEXT,
            publish_command TEXT,
            progress REAL DEFAULT 0,
            speed TEXT,
            eta TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_workflow_jobs)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "progress" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN progress REAL DEFAULT 0")
        if "speed" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN speed TEXT")
        if "eta" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN eta TEXT")
        if "channel" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN channel TEXT")
        if "subscribers" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subscribers TEXT")
        if "published_at" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN published_at TEXT")
        if "bilibili_account" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN bilibili_account TEXT")
        if "bilibili_tid" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN bilibili_tid INTEGER DEFAULT 249")
        if "publish_to_douyin" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN publish_to_douyin INTEGER DEFAULT 1")
        if "publish_to_bilibili" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN publish_to_bilibili INTEGER DEFAULT 0")
        if "process_version" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN process_version TEXT DEFAULT 'translation_v1'")
        if "subtitle_language" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subtitle_language TEXT DEFAULT 'zh-CN'")
        if "burn_profile" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN burn_profile TEXT DEFAULT 'stable'")
        if "subtitle_size" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subtitle_size TEXT DEFAULT 'douyin'")
        if "translator_label" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN translator_label TEXT DEFAULT 'AI中文字幕'")
        workflow_error_columns = {
            "error_code": "TEXT",
            "error_type": "TEXT",
            "error_reason": "TEXT",
            "error_detail": "TEXT",
            "interrupted_at": "DATETIME",
        }
        for column, definition in workflow_error_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE youtube_workflow_jobs ADD COLUMN {column} {definition}")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_id ON youtube_workflow_jobs(video_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status ON youtube_workflow_jobs(status)')
        conn.commit()


def _row_to_youtube_video(row):
    item = dict(row)
    analysis_result = _parse_json_object(item.get("analysis_result"))
    publish_draft = _parse_publish_draft(item.get("publish_draft"), analysis_result)
    return {
        "dbId": item.get("id"),
        "id": item.get("video_id"),
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "subscribers": _format_subscribers_w(item.get("subscribers")),
        "publishedAt": item.get("published_at") or "",
        "url": item.get("url") or "",
        "thumbnail": item.get("thumbnail") or "",
        "duration": item.get("duration") or "",
        "query": item.get("query") or "",
        "downloadStatus": int(item.get("download_status") or 0),
        "publishStatus": int(item.get("publish_status") or 0),
        "translateStatus": int(item.get("translate_status") or 0),
        "downloadedFilePath": item.get("downloaded_file_path") or "",
        "processedFilePath": item.get("processed_file_path") or "",
        "transcriptStatus": int(item.get("transcript_status") or 0),
        "transcriptFilePath": item.get("transcript_file_path") or "",
        "transcriptLanguage": item.get("transcript_language") or "",
        "analysisStatus": int(item.get("analysis_status") or 0),
        "hasAnalysis": int(item.get("analysis_status") or 0) == 1,
        "analysisResult": analysis_result,
        "publishDraft": publish_draft,
        "analysisUpdatedAt": item.get("analysis_updated_at") or "",
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def save_new_youtube_videos(videos, query):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        normalized_videos = []
        seen_ids = set()
        for video in videos:
            video_id = video.get("id")
            url = video.get("url")
            if not video_id or not url:
                continue
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            normalized_videos.append(video)

        if not normalized_videos:
            return {"items": [], "created": 0, "duplicate": 0, "requested": len(videos)}

        ids = [video.get("id") for video in normalized_videos]
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"SELECT video_id FROM youtube_videos WHERE video_id IN ({placeholders})", ids)
        existing_ids = {row["video_id"] for row in cursor.fetchall()}
        published_ids, published_urls = _published_youtube_identity_sets(cursor)
        published_duplicate_count = sum(
            1
            for video in normalized_videos
            if video.get("id") in published_ids
            or _canonical_youtube_url(video.get("url") or "", video.get("id") or "") in published_urls
        )
        new_videos = [
            video
            for video in normalized_videos
            if video.get("id") not in existing_ids
            and video.get("id") not in published_ids
            and _canonical_youtube_url(video.get("url") or "", video.get("id") or "") not in published_urls
        ]

        for video in new_videos:
            video_id = video.get("id")
            url = video.get("url")
            cursor.execute('''
            INSERT INTO youtube_videos (
                video_id, title, channel, subscribers, published_at, url, thumbnail, duration, query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                video_id,
                video.get("title") or "",
                video.get("channel") or "",
                _format_subscribers_w(video.get("subscribers")),
                video.get("publishedAt") or "",
                url,
                video.get("thumbnail") or "",
                video.get("duration") or "",
                query,
            ))
        conn.commit()

        if not new_videos:
            return {
                "items": [],
                "created": 0,
                "duplicate": len(normalized_videos),
                "publishedDuplicate": published_duplicate_count,
                "requested": len(videos),
            }

        new_ids = [video.get("id") for video in new_videos]
        placeholders = ",".join("?" for _ in new_ids)
        cursor.execute(f'''
        SELECT * FROM youtube_videos
        WHERE video_id IN ({placeholders})
        ORDER BY CASE video_id {' '.join(f'WHEN ? THEN {index}' for index, _ in enumerate(new_ids))} END
        ''', new_ids + new_ids)
        return {
            "items": [_row_to_youtube_video(row) for row in cursor.fetchall()],
            "created": len(new_videos),
            "duplicate": len(normalized_videos) - len(new_videos),
            "publishedDuplicate": published_duplicate_count,
            "requested": len(videos),
        }


def upsert_youtube_videos(videos, query):
    result = save_new_youtube_videos(videos, query)
    return result["items"]


def list_youtube_videos():
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM youtube_videos
        ORDER BY created_at DESC, id DESC
        ''')
        videos = [_row_to_youtube_video(row) for row in cursor.fetchall()]
        for video in videos:
            video["processedVersions"] = _list_processed_versions_for_video(cursor, video.get("id"))
        return videos


def normalize_existing_youtube_subscribers():
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        for table in ("youtube_videos", "youtube_workflow_jobs"):
            cursor.execute(f"SELECT id, subscribers FROM {table} WHERE subscribers IS NOT NULL AND subscribers != ''")
            rows = cursor.fetchall()
            for row_id, subscribers in rows:
                normalized = _format_subscribers_w(subscribers)
                if normalized and normalized != subscribers:
                    cursor.execute(
                        f"UPDATE {table} SET subscribers = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (normalized, row_id),
                    )
        conn.commit()


def update_youtube_video_status(video_id, download_status=None, publish_status=None, translate_status=None):
    init_youtube_video_table()
    fields = []
    values = []
    if download_status is not None:
        fields.append("download_status = ?")
        values.append(int(download_status))
    if publish_status is not None:
        fields.append("publish_status = ?")
        values.append(int(publish_status))
    if translate_status is not None:
        fields.append("translate_status = ?")
        values.append(int(translate_status))
    if not fields:
        raise ValueError("没有可更新的状态字段")
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(video_id)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = ?
        ''', values)
        if cursor.rowcount == 0:
            raise LookupError("视频记录不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def delete_youtube_video_record(video_id):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        video_record = dict(video)
        _assert_no_active_youtube_job(cursor, video_id)
        published_ids, _ = _published_youtube_identity_sets(cursor)
        has_publish_status = int(video_record.get("publish_status") or 0) == 1
        if has_publish_status and video_id not in published_ids:
            legacy_material = (
                _find_latest_youtube_material(cursor, video_id, "youtube_processed")
                or _find_latest_youtube_material(cursor, video_id, "youtube_download")
                or {}
            )
            _archive_published_material(
                cursor,
                _row_to_material(legacy_material) if legacy_material else {},
                _row_to_youtube_video(video),
                "历史发布",
                _now_iso(),
                publish_title=video_record.get("title") or "",
                account_count=0,
            )
            published_ids.add(video_id)
        is_published_archived = video_id in published_ids or has_publish_status

        processed_material = _find_latest_youtube_material(cursor, video_id, "youtube_processed")
        processed_path = Path(video_record["processed_file_path"]) if video_record["processed_file_path"] else None
        if not is_published_archived and (processed_material or (processed_path and processed_path.exists())):
            raise WorkflowConflictError(
                "该视频已存在处理后视频，请先删除对应处理后视频，再删除视频线索。",
                WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS,
                "PROCESSED_VIDEO_EXISTS",
            )

        download_material = _find_latest_youtube_material(cursor, video_id, "youtube_download")
        downloaded_file_path = video_record.get("downloaded_file_path") or ""
        download_status = int(video_record.get("download_status") or 0)
        if not is_published_archived and (download_material or downloaded_file_path or download_status == 1):
            raise WorkflowConflictError(
                "该视频已存在下载视频，请先删除对应下载视频，再删除视频线索。",
                WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS,
                "DOWNLOADED_VIDEO_EXISTS",
                {
                    "videoId": video_id,
                    "downloadStatus": download_status,
                    "downloadedFilePath": downloaded_file_path,
                    "materialId": (download_material or {}).get("id"),
                },
            )

        cursor.execute("DELETE FROM youtube_videos WHERE video_id = ?", (video_id,))
        deleted = cursor.rowcount
        conn.commit()
    if not deleted:
        raise LookupError("视频线索不存在")
    return {"videoId": video_id}


def delete_youtube_video_records(video_ids):
    results = []
    for video_id in video_ids:
        try:
            results.append({
                "videoId": video_id,
                "success": True,
                "data": delete_youtube_video_record(video_id),
            })
        except WorkflowConflictError as exc:
            results.append({
                "videoId": video_id,
                "success": False,
                "message": str(exc),
                "errorCode": exc.error_code,
                "errorType": exc.error_type,
            })
        except Exception as exc:
            results.append({
                "videoId": video_id,
                "success": False,
                "message": str(exc),
            })
    return {
        "total": len(video_ids),
        "success": sum(1 for item in results if item.get("success")),
        "failed": sum(1 for item in results if not item.get("success")),
        "items": results,
    }


def reset_youtube_video_processing(video_id, delete_processed=True, process_version=""):
    init_youtube_workflow_table()
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    process_version = _normalize_process_version(process_version) if process_version else ""

    deleted_materials = []
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        video = cursor.fetchone()
        if not video:
            raise LookupError("视频线索不存在")
        _assert_no_active_youtube_job(cursor, video_id)

        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = ? AND source_type = 'youtube_processed'
        ORDER BY upload_time DESC, id DESC
        ''', (video_id,))
        material_rows = cursor.fetchall()

        if delete_processed:
            for row in material_rows:
                record = _row_to_material(row)
                if process_version and record.get("processVersion") != process_version:
                    continue
                file_path = _material_file_path(record)
                if file_path and file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as exc:
                        print(f"删除处理后素材文件失败: {file_path} {exc}")
                deleted_materials.append({
                    "id": record.get("id"),
                    "filename": record.get("filename"),
                    "filePath": str(file_path) if file_path else "",
                    "processVersion": record.get("processVersion") or "",
                })
            if process_version:
                for record in deleted_materials:
                    cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
            else:
                cursor.execute(
                    "DELETE FROM file_records WHERE source_video_id = ? AND source_type = 'youtube_processed'",
                    (video_id,),
                )

        sync_result = _sync_youtube_processed_state(cursor, video_id)
        if deleted_materials and not sync_result.get("analysisCleared"):
            sync_result.update(_clear_youtube_analysis_state(cursor, video_id))
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        updated_video = _row_to_youtube_video(cursor.fetchone())

    return {
        "video": updated_video,
        "deletedMaterials": deleted_materials,
        "deletedMaterialCount": len(deleted_materials),
        "processVersion": process_version,
        "sync": sync_result,
    }


def _row_to_workflow_job(row):
    item = dict(row)
    return {
        "id": item.get("id"),
        "videoId": item.get("video_id") or "",
        "url": item.get("url") or "",
        "account": item.get("account") or "",
        "channel": item.get("channel") or "",
        "subscribers": _format_subscribers_w(item.get("subscribers")),
        "publishedAt": item.get("published_at") or "",
        "bilibiliAccount": item.get("bilibili_account") or "",
        "bilibiliTid": int(item.get("bilibili_tid") or 249),
        "publishToDouyin": int(item.get("publish_to_douyin") if item.get("publish_to_douyin") is not None else 1),
        "publishToBilibili": int(item.get("publish_to_bilibili") or 0),
        "processVersion": _normalize_process_version(item.get("process_version")),
        "subtitleLanguage": _normalize_subtitle_language(item.get("subtitle_language")),
        "burnProfile": _normalize_burn_profile(item.get("burn_profile")),
        "subtitleSize": _normalize_subtitle_size(item.get("subtitle_size")),
        "translatorLabel": _normalize_translator_label(item.get("translator_label")),
        "title": item.get("title") or "",
        "description": item.get("description") or "",
        "tags": json.loads(item.get("tags") or "[]"),
        "schedule": item.get("schedule") or "",
        "status": item.get("status") or "",
        "step": item.get("step") or "",
        "message": item.get("message") or "",
        "sourceFilePath": item.get("source_file_path") or "",
        "processedFilePath": item.get("processed_file_path") or "",
        "publishCommand": item.get("publish_command") or "",
        "progress": round(float(item.get("progress") or 0), 1),
        "speed": item.get("speed") or "",
        "eta": item.get("eta") or "",
        "errorCode": item.get("error_code") or "",
        "errorType": item.get("error_type") or "",
        "errorReason": item.get("error_reason") or "",
        "errorDetail": item.get("error_detail") or "",
        "interruptedAt": item.get("interrupted_at") or "",
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def _normalize_subtitle_language(value):
    language = str(value or DEFAULT_SUBTITLE_LANGUAGE).strip()
    return language if language in SUBTITLE_LANGUAGES else DEFAULT_SUBTITLE_LANGUAGE


def _subtitle_language_meta(value):
    language = _normalize_subtitle_language(value)
    return language, SUBTITLE_LANGUAGES[language]


def _infer_subtitle_language_from_filename(filename):
    stem = Path(str(filename or "")).stem.lower()
    suffix_map = {
        "zh": "zh-CN",
        "en": "en",
        "ja": "ja",
        "ko": "ko",
        "es": "es",
        "fr": "fr",
        "de": "de",
        "ru": "ru",
    }
    for suffix, language in suffix_map.items():
        if stem.endswith(f"_{suffix}"):
            return language
    return ""


def _youtube_thumbnail_url(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return ""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _normalize_burn_profile(value):
    profile = str(value or DEFAULT_BURN_PROFILE).strip()
    return profile if profile in BURN_PROFILES else DEFAULT_BURN_PROFILE


def _burn_profile_config(value):
    profile = _normalize_burn_profile(value)
    return profile, BURN_PROFILES[profile]


def _normalize_subtitle_size(value):
    size = str(value or DEFAULT_SUBTITLE_SIZE).strip()
    return size if size in SUBTITLE_SIZE_PRESETS else DEFAULT_SUBTITLE_SIZE


def _subtitle_size_config(value):
    size = _normalize_subtitle_size(value)
    return size, SUBTITLE_SIZE_PRESETS[size]


def _normalize_translator_label(value):
    label = str(value or "").strip()
    return label[:32] if label else DEFAULT_TRANSLATOR_LABEL


def _normalize_process_version(value):
    process_version = str(value or PROCESS_VERSION_TRANSLATION).strip()
    return process_version if process_version in PROCESS_VERSIONS else PROCESS_VERSION_TRANSLATION


def create_youtube_workflow_job(payload):
    init_youtube_workflow_table()
    job_id = str(uuid.uuid4())
    subtitle_language = _normalize_subtitle_language(payload.get("subtitleLanguage"))
    burn_profile = _normalize_burn_profile(payload.get("burnProfile"))
    subtitle_size = _normalize_subtitle_size(payload.get("subtitleSize"))
    translator_label = _normalize_translator_label(payload.get("translatorLabel"))
    process_version = _normalize_process_version(payload.get("processVersion"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_jobs (
            id, video_id, url, account, channel, subscribers, published_at,
            bilibili_account, bilibili_tid, publish_to_douyin, publish_to_bilibili,
            process_version, subtitle_language, burn_profile, subtitle_size, translator_label,
            title, description, tags, schedule, status, step, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id,
            payload.get("videoId") or "",
            payload["url"],
            payload.get("account") or "",
            payload.get("channel") or "",
            _format_subscribers_w(payload.get("subscribers")),
            payload.get("publishedAt") or "",
            payload.get("bilibiliAccount") or "",
            int(payload.get("bilibiliTid") or 249),
            int(1 if payload.get("publishToDouyin", True) else 0),
            int(1 if payload.get("publishToBilibili") else 0),
            process_version,
            subtitle_language,
            burn_profile,
            subtitle_size,
            translator_label,
            payload.get("title") or "",
            payload.get("description") or "",
            json.dumps(tags, ensure_ascii=False),
            payload.get("schedule") or "",
            "queued",
            "queued",
            "任务已创建，等待后台执行",
        ))
        conn.commit()
    return get_youtube_workflow_job(job_id)


def get_youtube_workflow_job(job_id):
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        return _row_to_workflow_job(row)


def list_youtube_workflow_jobs(limit=50):
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        ORDER BY created_at DESC
        LIMIT ?
        ''', (limit,))
        return [_row_to_workflow_job(row) for row in cursor.fetchall()]


def _active_job_for_video(cursor, video_id):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ? AND status IN ('queued', 'running')
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _latest_workflow_job_for_material(cursor, video_id, process_version=""):
    if not video_id:
        return None

    normalized_version = _normalize_process_version(process_version) if process_version else ""
    if normalized_version:
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE video_id = ?
          AND process_version = ?
          AND status IN ('queued', 'running')
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        ''', (video_id, normalized_version))
        row = cursor.fetchone()
        if row:
            return _row_to_workflow_job(row)

    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
      AND status IN ('queued', 'running')
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    if row:
        return _row_to_workflow_job(row)

    if normalized_version:
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE video_id = ?
          AND process_version = ?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        ''', (video_id, normalized_version))
        row = cursor.fetchone()
        if row:
            return _row_to_workflow_job(row)

    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _attach_material_workflow_state(cursor, material):
    video_id = material.get("source_video_id") or material.get("metadata", {}).get("videoId") or ""
    if not video_id:
        return material

    process_version = material.get("processVersion") or material.get("metadata", {}).get("processVersion") or ""
    job = _latest_workflow_job_for_material(cursor, video_id, process_version)
    if not job:
        return material

    material["workflowStatus"] = job.get("status") or ""
    material["workflowStep"] = job.get("step") or ""
    material["workflowMessage"] = job.get("message") or ""
    material["workflowProgress"] = job.get("progress") or 0
    material["workflowProcessVersion"] = job.get("processVersion") or ""
    material["workflowSubtitleLanguage"] = job.get("subtitleLanguage") or ""
    material["workflowUpdatedAt"] = job.get("updatedAt") or ""
    material["workflowJobId"] = job.get("id") or ""
    material["workflowSameProcessVersion"] = bool(
        process_version and job.get("processVersion") == process_version
    )
    return material


def _active_analysis_job_for_video(cursor, video_id):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM youtube_workflow_jobs
    WHERE video_id = ?
      AND status IN ('queued', 'running')
      AND step = 'analysis'
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
    ''', (video_id,))
    row = cursor.fetchone()
    return _row_to_workflow_job(row) if row else None


def _assert_no_active_youtube_job(cursor, video_id):
    active_job = _active_job_for_video(cursor, video_id)
    if not active_job:
        return
    raise WorkflowConflictError(
        "该视频存在运行中任务，请等待任务结束后再操作。",
        WORKFLOW_ERROR_LOCK_ACTIVE_JOB,
        "ACTIVE_JOB_LOCK",
        {"job": active_job},
    )


def update_youtube_workflow_job(job_id, **changes):
    if not changes:
        return get_youtube_workflow_job(job_id)
    fields = []
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_workflow_jobs
        SET {", ".join(fields)}
        WHERE id = ?
        ''', values)
        conn.commit()
    return get_youtube_workflow_job(job_id)


def mark_interrupted_workflow_jobs(error_code, error_type, reason, detail="", only_existing_active=True):
    init_youtube_workflow_table()
    now = _now_iso()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM youtube_workflow_jobs
        WHERE status IN ('queued', 'running')
        ''')
        rows = cursor.fetchall()
        if not rows:
            return []
        cursor.execute('''
        UPDATE youtube_workflow_jobs
        SET status = 'abnormal',
            step = 'abnormal',
            message = ?,
            error_code = ?,
            error_type = ?,
            error_reason = ?,
            error_detail = ?,
            interrupted_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('queued', 'running')
        ''', (reason, error_code, error_type, reason, detail, now))
        conn.commit()
        return [get_youtube_workflow_job(row["id"]) for row in rows]


def recover_interrupted_workflow_jobs():
    return mark_interrupted_workflow_jobs(
        WORKFLOW_ERROR_BOOT_INTERRUPTED,
        "BACKEND_RESTART_RECOVERY",
        "后端服务曾异常退出，任务未正常结束",
        "服务启动时发现数据库中仍有 queued/running 任务，已标记为异常。",
    )


def mark_shutdown_interrupted_jobs():
    return mark_interrupted_workflow_jobs(
        WORKFLOW_ERROR_SHUTDOWN,
        "BACKEND_SHUTDOWN",
        "后端服务正在关闭，任务被中断",
        "后端进程收到退出信号，已尽量将运行中任务标记为异常。",
    )


WORKFLOW_STAGE_LABELS = {
    "download": "下载原视频",
    "subtitle": "转写处理与烧录",
    "analysis": "剪辑方案分析",
    "publish": "发布",
    "workflow": "完整工作流",
    "cloud_summary": "云端总结",
}


def _file_size_mb(path):
    if not path:
        return 0
    try:
        candidate = Path(path)
        if candidate.is_file():
            return round(candidate.stat().st_size / (1024 * 1024), 2)
    except Exception:
        return 0
    return 0


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def start_workflow_event(job, stage, message="", input_file_path="", metadata=None):
    init_database_tables()
    now = _now_iso()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_events (
            job_id, video_id, stage, stage_label, status, message,
            input_file_path, input_size_mb, started_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.get("id") or "",
            job.get("videoId") or "",
            stage,
            WORKFLOW_STAGE_LABELS.get(stage, stage),
            "running",
            message,
            str(input_file_path or ""),
            _file_size_mb(input_file_path),
            now,
            json.dumps(metadata or {}, ensure_ascii=False),
        ))
        conn.commit()
        return cursor.lastrowid


def finish_workflow_event(event_id, status="success", message="", output_file_path="", cloud_usage=None, metadata=None):
    if not event_id:
        return None
    init_database_tables()
    now = _now_iso()
    cloud_usage = cloud_usage or {}
    prompt_tokens = int(cloud_usage.get("promptTokens") or cloud_usage.get("prompt_tokens") or 0)
    completion_tokens = int(cloud_usage.get("completionTokens") or cloud_usage.get("completion_tokens") or 0)
    total_tokens = int(
        cloud_usage.get("totalTokens")
        or cloud_usage.get("total_tokens")
        or cloud_usage.get("tokens")
        or (prompt_tokens + completion_tokens)
        or 0
    )
    metadata = metadata or {}
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_workflow_events WHERE id = ?", (event_id,))
        event = cursor.fetchone()
        started_at = _parse_dt(event["started_at"]) if event else None
        duration = 0
        if started_at:
            ended_at = _parse_dt(now) or datetime.datetime.now()
            duration = max(0, (ended_at.replace(tzinfo=None) - started_at.replace(tzinfo=None)).total_seconds())
        cursor.execute('''
        UPDATE youtube_workflow_events
        SET status = ?,
            message = ?,
            output_file_path = ?,
            output_size_mb = ?,
            ended_at = ?,
            duration_seconds = ?,
            cloud_model = ?,
            prompt_tokens = ?,
            completion_tokens = ?,
            total_tokens = ?,
            cloud_latency_ms = ?,
            metadata = ?
        WHERE id = ?
        ''', (
            status,
            message,
            str(output_file_path or ""),
            _file_size_mb(output_file_path),
            now,
            round(duration, 2),
            cloud_usage.get("model") or "",
            prompt_tokens,
            completion_tokens,
            total_tokens,
            float(cloud_usage.get("latencyMs") or 0),
            json.dumps(metadata, ensure_ascii=False),
            event_id,
        ))
        conn.commit()
        cursor.execute("SELECT * FROM youtube_workflow_events WHERE id = ?", (event_id,))
        return _row_to_workflow_event(cursor.fetchone())


def _row_to_workflow_event(row):
    item = dict(row)
    try:
        metadata = json.loads(item.get("metadata") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": item.get("id"),
        "jobId": item.get("job_id") or "",
        "videoId": item.get("video_id") or "",
        "stage": item.get("stage") or "",
        "stageLabel": item.get("stage_label") or item.get("stage") or "",
        "status": item.get("status") or "",
        "message": item.get("message") or "",
        "inputFilePath": item.get("input_file_path") or "",
        "outputFilePath": item.get("output_file_path") or "",
        "inputSizeMb": float(item.get("input_size_mb") or 0),
        "outputSizeMb": float(item.get("output_size_mb") or 0),
        "startedAt": item.get("started_at") or "",
        "endedAt": item.get("ended_at") or "",
        "durationSeconds": round(float(item.get("duration_seconds") or 0), 2),
        "cloudModel": item.get("cloud_model") or "",
        "promptTokens": int(item.get("prompt_tokens") or 0),
        "completionTokens": int(item.get("completion_tokens") or 0),
        "totalTokens": int(item.get("total_tokens") or 0),
        "cloudLatencyMs": float(item.get("cloud_latency_ms") or 0),
        "metadata": metadata,
        "createdAt": item.get("created_at") or "",
    }


def list_workflow_events(limit=200):
    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT e.*, j.title, j.process_version, j.subtitle_language, j.burn_profile
        FROM youtube_workflow_events e
        LEFT JOIN youtube_workflow_jobs j ON j.id = e.job_id
        ORDER BY e.started_at DESC, e.id DESC
        LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        events = []
        for row in rows:
            event = _row_to_workflow_event(row)
            event["title"] = row["title"] or ""
            event["processVersion"] = row["process_version"] or "translation_v1"
            event["subtitleLanguage"] = _normalize_subtitle_language(row["subtitle_language"])
            event["burnProfile"] = _normalize_burn_profile(row["burn_profile"])
            events.append(event)
        return events


def get_workflow_statistics(limit=200):
    events = list_workflow_events(limit)
    jobs = list_youtube_workflow_jobs(limit)
    total_duration = sum(event["durationSeconds"] for event in events)
    prompt_tokens = sum(event["promptTokens"] for event in events)
    completion_tokens = sum(event["completionTokens"] for event in events)
    total_tokens = sum(event["totalTokens"] for event in events)
    cloud_events = [event for event in events if event["cloudLatencyMs"] > 0 or event["totalTokens"] > 0]
    stage_map = {}
    for event in events:
        stage = event["stage"]
        bucket = stage_map.setdefault(stage, {
            "stage": stage,
            "stageLabel": event["stageLabel"],
            "count": 0,
            "success": 0,
            "failed": 0,
            "durationSeconds": 0,
            "avgDurationSeconds": 0,
            "inputSizeMb": 0,
            "outputSizeMb": 0,
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "avgCloudLatencyMs": 0,
        })
        bucket["count"] += 1
        if event["status"] == "success":
            bucket["success"] += 1
        if event["status"] == "failed":
            bucket["failed"] += 1
        bucket["durationSeconds"] += event["durationSeconds"]
        bucket["inputSizeMb"] += event["inputSizeMb"]
        bucket["outputSizeMb"] += event["outputSizeMb"]
        bucket["promptTokens"] += event["promptTokens"]
        bucket["completionTokens"] += event["completionTokens"]
        bucket["totalTokens"] += event["totalTokens"]
        bucket["avgCloudLatencyMs"] += event["cloudLatencyMs"]
    for bucket in stage_map.values():
        bucket["durationSeconds"] = round(bucket["durationSeconds"], 2)
        bucket["avgDurationSeconds"] = round(bucket["durationSeconds"] / bucket["count"], 2) if bucket["count"] else 0
        bucket["inputSizeMb"] = round(bucket["inputSizeMb"], 2)
        bucket["outputSizeMb"] = round(bucket["outputSizeMb"], 2)
        bucket["avgCloudLatencyMs"] = round(bucket["avgCloudLatencyMs"] / bucket["count"], 2) if bucket["count"] else 0

    return {
        "summary": {
            "eventCount": len(events),
            "jobCount": len(jobs),
            "totalDurationSeconds": round(total_duration, 2),
            "avgDurationSeconds": round(total_duration / len(events), 2) if events else 0,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": total_tokens,
            "cloudCallCount": len(cloud_events),
            "avgCloudLatencyMs": round(sum(event["cloudLatencyMs"] for event in cloud_events) / len(cloud_events), 2) if cloud_events else 0,
        },
        "stages": list(stage_map.values()),
        "events": events,
        "jobs": jobs,
    }


def update_youtube_video_artifacts(video_id, **changes):
    if not video_id or not changes:
        return None
    fields = []
    values = []
    for key, value in changes.items():
        fields.append(f"{key} = ?")
        values.append(value)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(video_id)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = ?
        ''', values)
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return _row_to_youtube_video(row) if row else None


def update_youtube_video_analysis_status(video_id, status, result=None):
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    init_youtube_video_table()
    fields = ["analysis_status = ?", "analysis_updated_at = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]
    values = [int(status)]
    if result is not None:
        fields.append("analysis_result = ?")
        values.append(json.dumps(result, ensure_ascii=False))
    values.append(video_id)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
        UPDATE youtube_videos
        SET {", ".join(fields)}
        WHERE video_id = ?
        ''', values)
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def save_youtube_video_analysis(video_id, result):
    if not video_id:
        raise ValueError("视频 ID 不能为空")
    init_youtube_video_table()
    default_draft = _build_default_publish_draft(result)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT publish_draft FROM youtube_videos WHERE video_id = ?
        ''', (video_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("视频线索不存在")

        current_draft = _parse_publish_draft(row["publish_draft"] if "publish_draft" in row.keys() else "", result)
        if current_draft:
            cursor.execute('''
            UPDATE youtube_videos
            SET analysis_status = 1,
                analysis_result = ?,
                analysis_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (json.dumps(result, ensure_ascii=False), video_id))
        else:
            cursor.execute('''
            UPDATE youtube_videos
            SET analysis_status = 1,
                analysis_result = ?,
                publish_draft = ?,
                analysis_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (
                json.dumps(result, ensure_ascii=False),
                json.dumps(default_draft, ensure_ascii=False),
                video_id,
            ))
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        return _row_to_youtube_video(cursor.fetchone())


def update_youtube_video_publish_draft(video_id, payload):
    current = get_youtube_video_analysis(video_id)
    current_draft = dict(current.get("draft") or {})
    title = payload.get("title", payload.get("selectedTitle", current_draft.get("title", "")))
    description = payload.get("description", payload.get("publish_copy", current_draft.get("description", "")))
    tags = payload.get("tags", current_draft.get("tags", []))
    draft = {
        "title": str(title or "").strip(),
        "description": str(description or "").strip(),
        "tags": _clean_topic_list(tags),
        "source": "user_saved",
        "updatedAt": _now_iso(),
    }
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE youtube_videos
        SET publish_draft = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (json.dumps(draft, ensure_ascii=False), video_id))
        if cursor.rowcount == 0:
            raise LookupError("视频线索不存在")
        conn.commit()
    return get_youtube_video_analysis(video_id)


def update_youtube_video_analysis_result(video_id, payload):
    return update_youtube_video_publish_draft(video_id, payload)


def ensure_youtube_publish_draft(video_id):
    analysis = get_youtube_video_analysis(video_id)
    if analysis.get("draft"):
        return analysis
    result = analysis.get("result") or {}
    if not result:
        return analysis
    draft = _build_default_publish_draft(result)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE youtube_videos
        SET publish_draft = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (json.dumps(draft, ensure_ascii=False), video_id))
        conn.commit()
    return get_youtube_video_analysis(video_id)


def get_youtube_video_analysis(video_id):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError("视频线索不存在")
        raw_result = row["analysis_result"] if "analysis_result" in row.keys() else ""
        result = _parse_json_object(raw_result)
        raw_draft = row["publish_draft"] if "publish_draft" in row.keys() else ""
        draft = _parse_publish_draft(raw_draft, result)
        return {
            "videoId": video_id,
            "status": int(row["analysis_status"] or 0),
            "updatedAt": row["analysis_updated_at"] or "",
            "result": result,
            "draft": draft,
            "error": result.get("error") or {},
        }


def _ensure_dir(path):
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _run_command(command, cwd=None, timeout=None):
    is_shell_command = isinstance(command, str)
    result = subprocess.run(
        command,
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=is_shell_command,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        display_command = command if is_shell_command else " ".join(command)
        raise RuntimeError(output or f"命令执行失败: {display_command}")
    return output


def _replace_file_with_backup(source_file, output_file):
    source_file = Path(source_file)
    output_file = Path(output_file)
    backup_file = None
    if output_file.exists():
        backup_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_file.exists():
            backup_file.unlink()
        output_file.replace(backup_file)
    try:
        shutil.copy2(source_file, output_file)
        if backup_file and backup_file.exists():
            backup_file.unlink()
    except Exception:
        if output_file.exists():
            output_file.unlink()
        if backup_file and backup_file.exists():
            backup_file.replace(output_file)
        raise
    return output_file


def _replace_output_file(tmp_output_file, output_file):
    tmp_output_file = Path(tmp_output_file)
    output_file = Path(output_file)
    backup_file = None
    if output_file.exists():
        backup_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_file.exists():
            backup_file.unlink()
        output_file.replace(backup_file)
    try:
        tmp_output_file.replace(output_file)
        if backup_file and backup_file.exists():
            backup_file.unlink()
    except Exception:
        if output_file.exists():
            output_file.unlink()
        if backup_file and backup_file.exists():
            backup_file.replace(output_file)
        raise
    return output_file


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


def _resolve_ytdlp_js_runtimes():
    runtime = str(YTDLP_JS_RUNTIME or "").strip().lower()
    runtime_path = str(YTDLP_JS_RUNTIME_PATH or "").strip()
    if runtime:
        config = {}
        if runtime_path:
            config["path"] = runtime_path
        return {runtime: config}

    deno_path = shutil.which("deno")
    if deno_path:
        return {"deno": {"path": deno_path}}

    node_path = shutil.which("node")
    if node_path:
        return {"node": {"path": node_path}}

    return {}


def _base_ytdlp_opts(include_ffmpeg=False):
    opts = {
        "js_runtimes": _resolve_ytdlp_js_runtimes(),
    }
    if YTDLP_REMOTE_COMPONENTS:
        opts["remote_components"] = list(YTDLP_REMOTE_COMPONENTS)
    if include_ffmpeg:
        opts["ffmpeg_location"] = _resolve_ffmpeg_command()
    return opts


def _render_command_template(template, **values):
    if not template:
        return ""
    return template.format(**values)


def _find_newest_video_file(directory, since_timestamp):
    allowed = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv"}
    candidates = [
        path for path in Path(directory).glob("**/*")
        if path.is_file() and path.suffix.lower() in allowed and path.stat().st_mtime >= since_timestamp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _format_bytes_per_second(value):
    if not value:
        return ""
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
        number /= 1024
    return ""


def _format_eta(seconds):
    if seconds is None:
        return ""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _make_download_progress_hook(job_id):
    last_update = {"time": 0.0}

    def hook(status):
        now = time.time()
        if status.get("status") == "downloading" and now - last_update["time"] < 0.5:
            return
        last_update["time"] = now

        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        downloaded = status.get("downloaded_bytes") or 0
        progress = 0.0
        if total:
            progress = max(0.0, min(99.0, downloaded / total * 100))

        if status.get("status") == "finished":
            progress = 100.0

        message = "正在使用 yt-dlp 下载视频"
        if status.get("status") == "finished":
            message = "视频下载完成，正在写入素材库"

        update_youtube_workflow_job(
            job_id,
            progress=progress,
            speed=_format_bytes_per_second(status.get("speed")),
            eta=_format_eta(status.get("eta")),
            message=message,
        )

    return hook


def _format_ass_timestamp(seconds):
    seconds = max(0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds >= 100:
        secs += 1
        centiseconds = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _escape_ass_text(text):
    return str(text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _extract_audio_for_whisper(source_file, work_dir):
    ffmpeg = _resolve_ffmpeg_command()
    audio_file = Path(work_dir) / f"{Path(source_file).stem}_16k.wav"
    _run_command([
        ffmpeg,
        "-y",
        "-i", str(source_file),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_file),
    ], cwd=BASE_DIR)
    return audio_file


def _get_media_duration_seconds(media_file):
    try:
        with wave.open(str(media_file), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate or 1)
    except Exception:
        return 0


def _get_video_info(media_file):
    ffmpeg = _resolve_ffmpeg_command()
    command = [ffmpeg, "-hide_banner", "-i", str(media_file)]
    result = subprocess.run(command, cwd=str(BASE_DIR), capture_output=True, text=True)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)

    duration = 0.0
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    width = 1080
    height = 1920
    video_match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})\b", output)
    if video_match:
        width = int(video_match.group(1))
        height = int(video_match.group(2))

    fps = 30.0
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", output)
    if fps_match:
        try:
            fps = float(fps_match.group(1))
        except ValueError:
            fps = 30.0
    if fps <= 0 or fps > 120:
        fps = 30.0

    return {"width": width, "height": height, "duration": duration, "fps": fps}


def _transcribe_audio(audio_file):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("未安装 faster-whisper，请先安装依赖后再执行字幕处理。") from exc

    model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(str(audio_file), beam_size=5, vad_filter=True)
    result = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            result.append({"start": float(segment.start), "end": float(segment.end), "text": text})
    if not result:
        raise NoSpeechDetectedError("未检测到可识别人声，已跳过字幕处理。")
    return result, getattr(info, "language", "")


def _transcript_path(video_id, source_file):
    key = re.sub(r"[^A-Za-z0-9_-]+", "_", video_id or Path(source_file).stem)
    return _ensure_dir(YOUTUBE_TRANSCRIPT_DIR) / f"{key}.json"


def _load_transcript_file(path):
    transcript_path = Path(path or "")
    if not transcript_path.is_file():
        return None
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if not segments:
        return None
    return {
        "segments": segments,
        "language": data.get("language") or "",
        "path": transcript_path,
    }


def _get_or_create_transcript(job, source_file, work_dir, progress_base=10, progress_done=34):
    video_id = job.get("videoId") or ""
    job_id = job.get("id")
    record = _get_youtube_video_record(video_id)
    cached = _load_transcript_file((record or {}).get("transcriptFilePath") or "")
    if cached:
        _update_translate_progress(job_id, progress_done, f"已复用转写缓存，识别到 {len(cached['segments'])} 段字幕")
        return cached["segments"], cached["language"], cached["path"]

    transcript_file = _transcript_path(video_id or job_id, source_file)
    cached = _load_transcript_file(transcript_file)
    if cached:
        update_youtube_video_artifacts(
            video_id,
            transcript_status=1,
            transcript_file_path=str(cached["path"]),
            transcript_language=cached["language"],
        )
        _update_translate_progress(job_id, progress_done, f"已复用转写缓存，识别到 {len(cached['segments'])} 段字幕")
        return cached["segments"], cached["language"], cached["path"]

    _update_translate_progress(job_id, progress_base, "正在提取音频，准备语音识别")
    audio_file = _extract_audio_for_whisper(source_file, work_dir)
    _update_translate_progress(job_id, max(progress_base + 10, 20), "正在进行语音识别，长视频可能需要较久")
    segments, language = _transcribe_audio(audio_file)
    payload = {
        "videoId": video_id,
        "sourceFile": str(source_file),
        "language": language or "",
        "segments": segments,
        "createdAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    transcript_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if video_id:
        update_youtube_video_artifacts(
            video_id,
            transcript_status=1,
            transcript_file_path=str(transcript_file),
            transcript_language=language or "",
        )
    _update_translate_progress(job_id, progress_done, f"已识别 {len(segments)} 段字幕")
    return segments, language, transcript_file


def _translate_segments(segments, target_language=DEFAULT_SUBTITLE_LANGUAGE):
    target_language, language_meta = _subtitle_language_meta(target_language)
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise RuntimeError("未安装 deep-translator，请先安装依赖后再执行字幕翻译。") from exc

    translator = GoogleTranslator(source="auto", target=target_language)
    translated = [dict(segment) for segment in segments]
    batch = []
    batch_indices = []
    max_chars = 3600

    def flush_batch():
        if not batch:
            return
        try:
            translated_text = translator.translate("\n".join(batch))
            lines = [line.strip() for line in str(translated_text).splitlines()]
        except Exception:
            lines = []
        if len(lines) != len(batch):
            lines = []
            for text in batch:
                try:
                    lines.append(str(translator.translate(text)).strip())
                except Exception:
                    lines.append(text)
        for index, line in zip(batch_indices, lines):
            translated[index]["subtitle"] = line or translated[index]["text"]
        batch.clear()
        batch_indices.clear()

    for index, segment in enumerate(segments):
        text = segment["text"]
        if sum(len(item) for item in batch) + len(text) + len(batch) > max_chars:
            flush_batch()
        batch.append(text)
        batch_indices.append(index)
    flush_batch()
    return translated


def _author_overlay_lines(job):
    return [
        f"博主: {job.get('channel') or job.get('account') or '未知'}",
        f"粉丝: {job.get('subscribers') or '未获取'}",
        f"时间: {job.get('publishedAt') or '未获取'}",
        f"翻译: {_normalize_translator_label(job.get('translatorLabel'))}",
    ]


def _wrap_ass_text(text, max_chars):
    text = str(text or "").strip()
    if not text or len(text) <= max_chars:
        return text
    chunks = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars and char in " ，。！？、,.!?;；:":
            chunks.append(current.strip())
            current = ""
    if current:
        chunks.append(current.strip())
    if len(chunks) <= 1:
        chunks = [text[index:index + max_chars] for index in range(0, len(text), max_chars)]
    return "\n".join(chunks[:3])


def _build_ass_file(job, segments, ass_file, audio_duration, video_info=None):
    ass_file = Path(ass_file)
    video_info = video_info or {}
    width = max(320, int(video_info.get("width") or 1080))
    height = max(320, int(video_info.get("height") or 1920))
    short_side = min(width, height)
    is_vertical = height > width
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    _, size_config = _subtitle_size_config(job.get("subtitleSize"))
    font_scale = float(size_config.get("scale") or 1)
    subtitle_floor = 56 if is_vertical else 48
    english_floor = 40 if is_vertical else 34
    info_floor = 36 if is_vertical else 30
    subtitle_font_size = int(max(subtitle_floor, min(112, int(short_side * 0.092))) * font_scale)
    english_font_size = int(max(english_floor, min(82, int(short_side * 0.065))) * font_scale)
    info_font_size = int(max(info_floor, min(72, int(short_side * 0.060))) * min(font_scale, 1.14))
    horizontal_margin = max(22, int(width * (0.046 if is_vertical else 0.055)))
    subtitle_margin_v = max(92 if is_vertical else 78, int(height * (0.092 if is_vertical else 0.086)))
    english_margin_v = max(34, int(subtitle_margin_v - english_font_size * 1.38))
    info_margin_v = max(28, int(height * 0.028))
    subtitle_outline = max(4, int(short_side * 0.0065))
    info_outline = max(3, int(short_side * 0.0055))
    subtitle_shadow = max(1, int(short_side * 0.0022))
    max_subtitle_chars = max(8, int(width / max(subtitle_font_size * (0.92 if is_vertical else 0.86), 1)))
    max_english_chars = max(12, int(width / max(english_font_size * (0.62 if is_vertical else 0.55), 1)))
    always_show_english_line = True
    has_translated_line = target_language != "en"

    overlay_text = "\\N".join(_escape_ass_text(line) for line in _author_overlay_lines(job))
    dialogue_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Subtitle,Microsoft YaHei,{subtitle_font_size},&H0000E6FF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{subtitle_outline},{subtitle_shadow},2,{horizontal_margin},{horizontal_margin},{subtitle_margin_v},1",
        f"Style: English,Arial,{english_font_size},&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{subtitle_outline},{subtitle_shadow},2,{horizontal_margin},{horizontal_margin},{english_margin_v},1",
        f"Style: Info,Microsoft YaHei,{info_font_size},&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{info_outline},{subtitle_shadow},7,{horizontal_margin},{horizontal_margin},{info_margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{_format_ass_timestamp(0)},{_format_ass_timestamp(min(20, audio_duration or 20))},Info,,0,0,0,,{overlay_text}",
    ]
    for segment in segments:
        start = _format_ass_timestamp(segment["start"])
        end = _format_ass_timestamp(max(segment["end"], segment["start"] + 0.5))
        english_text = _escape_ass_text(_wrap_ass_text(segment.get("text") or "", max_english_chars))
        if always_show_english_line and english_text:
            dialogue_lines.append(f"Dialogue: 0,{start},{end},English,,0,0,0,,{english_text}")
        if has_translated_line:
            wrapped_text = _wrap_ass_text(segment.get("subtitle") or segment.get("text") or "", max_subtitle_chars)
            text = _escape_ass_text(wrapped_text)
            if text:
                dialogue_lines.append(f"Dialogue: 1,{start},{end},Subtitle,,0,0,0,,{text}")
    ass_file.write_text("\n".join(dialogue_lines), encoding="utf-8")
    return ass_file


def _ffmpeg_subtitle_path(path):
    value = Path(path).resolve().as_posix()
    return value.replace(":", "\\:").replace("'", "\\'")


def _compatible_video_dimensions(width, height, max_long_side=1920, max_short_side=1080):
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    if width >= height:
        max_width, max_height = int(max_long_side), int(max_short_side)
    else:
        max_width, max_height = int(max_short_side), int(max_long_side)

    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return None

    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height


def _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=0, job_id=""):
    ffmpeg = _resolve_ffmpeg_command()
    subtitle_filter = f"subtitles='{_ffmpeg_subtitle_path(ass_file)}'"
    output_file = Path(output_file)
    tmp_output_file = output_file.with_name(f"{output_file.stem}.tmp{output_file.suffix}")
    backup_output_file = None
    if tmp_output_file.exists():
        tmp_output_file.unlink()
    if output_file.exists():
        backup_output_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_output_file.exists():
            backup_output_file.unlink()
        output_file.replace(backup_output_file)

    job = get_youtube_workflow_job(job_id) or {}
    _, burn_config = _burn_profile_config(job.get("burnProfile"))
    video_info = _get_video_info(source_file)
    output_fps = float(video_info.get("fps") or 30.0)
    max_fps = float(burn_config.get("max_fps") or 60.0)
    if output_fps <= 0 or output_fps > max_fps:
        output_fps = max_fps

    video_filters = [subtitle_filter]
    target_dimensions = _compatible_video_dimensions(
        video_info.get("width"),
        video_info.get("height"),
        burn_config.get("max_long_side", 1920),
        burn_config.get("max_short_side", 1080),
    )
    if target_dimensions:
        target_width, target_height = target_dimensions
        video_filters.append(f"scale={target_width}:{target_height}:flags=lanczos")
        video_filters.append("setsar=1")
    video_filter = ",".join(video_filters)

    command = [
        ffmpeg,
        "-y",
        "-fflags", "+genpts",
        "-i", str(source_file),
        "-vf", video_filter,
        "-fps_mode", "cfr",
        "-r", f"{output_fps:.3f}".rstrip("0").rstrip("."),
        "-c:v", "libx264",
        "-preset", burn_config["preset"],
        "-crf", burn_config["crf"],
        "-maxrate", burn_config["maxrate"],
        "-bufsize", burn_config["bufsize"],
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", "aresample=async=1:first_pts=0",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(tmp_output_file),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines = []
    last_update = 0

    def read_stderr():
        if not process.stderr:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    if process.stdout:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("out_time_ms=") and duration:
                try:
                    out_seconds = int(line.split("=", 1)[1]) / 1000000
                except ValueError:
                    continue
                now = time.time()
                if now - last_update >= 1:
                    burn_progress = max(0.0, min(1.0, out_seconds / duration))
                    progress = 50 + burn_progress * 48
                    _update_translate_progress(
                        job_id,
                        round(progress, 1),
                        f"FFmpeg 正在烧录字幕 {min(100, burn_progress * 100):.1f}%",
                    )
                    last_update = now

    return_code = process.wait()
    stderr_thread.join(timeout=2)
    if return_code != 0:
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError("\n".join(stderr_lines[-30:]) or "FFmpeg 烧录失败")

    if not tmp_output_file.exists() or tmp_output_file.stat().st_size <= 0:
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成有效临时文件: {tmp_output_file}")

    tmp_output_file.replace(output_file)
    if backup_output_file and backup_output_file.exists():
        backup_output_file.unlink()
    if not output_file.exists() or output_file.stat().st_size <= 0:
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成最终 MP4: {output_file}")
    return output_file


def _download_youtube_video(job):
    download_dir = _ensure_dir(YOUTUBE_DOWNLOAD_DIR)
    video_key = re.sub(r"[^A-Za-z0-9_-]+", "_", job["videoId"] or job["id"])
    output_template = str(download_dir / f"{video_key}.%(ext)s")
    ffmpeg_command = _resolve_ffmpeg_command()
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，请先执行 `uv pip install -e .` 更新依赖。") from exc

    ydl_opts = {
        **_base_ytdlp_opts(),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "writethumbnail": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "quiet": True,
        "no_warnings": False,
        "ffmpeg_location": ffmpeg_command,
        "progress_hooks": [_make_download_progress_hook(job["id"])],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(job["url"], download=True)

    preferred = download_dir / f"{video_key}.mp4"
    if preferred.exists():
        return preferred
    video_file = _find_newest_video_file(download_dir, time.time() - 3600)
    if not video_file:
        raise RuntimeError(f"yt-dlp 已执行，但未在 {download_dir} 找到下载后的视频文件")
    return video_file


def _update_translate_progress(job_id, progress, message, step="subtitle"):
    if not job_id:
        return
    job = get_youtube_workflow_job(job_id) or {}
    if _normalize_process_version(job.get("processVersion")) == PROCESS_VERSION_EDITING and step == "subtitle":
        progress = 60 + (float(progress or 0) * 0.25)
    update_youtube_workflow_job(
        job_id,
        step=step,
        message=message,
        progress=progress,
        speed="",
        eta="",
    )


def _process_subtitles(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    process_version = _normalize_process_version(job.get("processVersion"))
    video_key = job.get("videoId") or job.get("id") or Path(source_file).stem
    output_file = processed_dir / f"{video_key}_{process_version}_{language_meta['suffix']}.mp4"
    job_id = job.get("id")

    if SUBTITLE_COMMAND_TEMPLATE:
        _update_translate_progress(job_id, 10, "正在执行自定义字幕处理命令")
        previous_output_file = None
        if output_file.exists():
            previous_output_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
            if previous_output_file.exists():
                previous_output_file.unlink()
            output_file.replace(previous_output_file)
        command = _render_command_template(
            SUBTITLE_COMMAND_TEMPLATE,
            input=str(source_file),
            output=str(output_file),
            video_id=job["videoId"] or job["id"],
        )
        try:
            _run_command(command, cwd=BASE_DIR)
            if not output_file.exists():
                raise RuntimeError(f"字幕处理命令已执行，但未生成文件: {output_file}")
            if previous_output_file and previous_output_file.exists():
                previous_output_file.unlink()
        except Exception:
            if output_file.exists():
                output_file.unlink()
            if previous_output_file and previous_output_file.exists():
                previous_output_file.replace(output_file)
            raise
        _update_translate_progress(job_id, 98, "自定义字幕处理完成，正在保存结果")
        return {"path": output_file, "skipped": False}

    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_work")
    _update_translate_progress(job_id, 6, "正在读取视频信息")
    video_info = _get_video_info(source_file)
    try:
        segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir)
    except NoSpeechDetectedError as exc:
        _replace_file_with_backup(source_file, output_file)
        _update_translate_progress(job_id, 98, str(exc))
        return {"path": output_file, "skipped": True}
    _update_translate_progress(job_id, 34, f"已识别 {len(segments)} 段字幕，正在处理为{language_meta['label']}")
    translated_segments = _translate_segments(segments, target_language)
    _update_translate_progress(job_id, 46, f"{language_meta['label']}字幕已生成，正在构建自适应字幕样式")
    duration = video_info.get("duration") or max((segment.get("end") or 0) for segment in segments)
    ass_file = _build_ass_file(job, translated_segments, work_dir / f"{Path(source_file).stem}.ass", duration, video_info)
    _update_translate_progress(job_id, 50, f"正在使用 FFmpeg 烧录{language_meta['label']}字幕")
    result = _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=duration, job_id=job_id)
    _update_translate_progress(job_id, 98, "视频已生成，正在写入素材库")
    return {"path": result, "skipped": False}


def _select_intro_highlight_segments(analysis_result, max_segments=3):
    raw_segments = (analysis_result or {}).get("highlight_segments") or []
    selected = []
    for segment in _normalize_highlight_segments(raw_segments):
        try:
            start = max(0.0, float(segment.get("start") or 0))
            end = max(start + 1, float(segment.get("end") or 0))
        except (TypeError, ValueError):
            continue
        if end - start < 2:
            continue
        selected.append({
            **segment,
            "start": round(start, 2),
            "end": round(end, 2),
        })
        if len(selected) >= max_segments:
            break
    return selected


def _ffmpeg_concat_file_path(path):
    return Path(path).resolve().as_posix().replace("'", "'\\''")


def _build_editing_intro_video(job, source_file, processed_file, analysis_result, work_dir):
    segments = _select_intro_highlight_segments(analysis_result, max_segments=3)
    if not segments:
        return {
            "path": Path(processed_file),
            "segments": [],
            "skipped": True,
            "reason": "未找到可用于开头混剪的高光片段",
        }

    job_id = job.get("id")
    ffmpeg = _resolve_ffmpeg_command()
    _, burn_config = _burn_profile_config(job.get("burnProfile"))
    processed_info = _get_video_info(processed_file)
    width = int(processed_info.get("width") or 0)
    height = int(processed_info.get("height") or 0)
    fps = float(processed_info.get("fps") or 30.0)
    if fps <= 0:
        fps = 30.0
    max_fps = float(burn_config.get("max_fps") or 60.0)
    if fps > max_fps:
        fps = max_fps

    work_dir = _ensure_dir(work_dir)
    output_file = Path(processed_file)
    clip_files = []
    normalized_main = work_dir / f"{output_file.stem}_main_normalized.mp4"
    final_tmp = work_dir / f"{output_file.stem}_editing_concat.mp4"
    concat_file = work_dir / f"{output_file.stem}_concat.txt"

    def encode_clip(input_file, output_clip, start=None, end=None):
        command = [ffmpeg, "-y"]
        if start is not None:
            command.extend(["-ss", f"{start:.3f}"])
        if end is not None and start is not None:
            command.extend(["-t", f"{max(0.5, end - start):.3f}"])
        command.extend(["-i", str(input_file)])
        video_filters = []
        if width and height:
            video_filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "setsar=1",
            ])
        command.extend([
            "-vf", ",".join(video_filters) if video_filters else "setsar=1",
            "-fps_mode", "cfr",
            "-r", f"{fps:.3f}".rstrip("0").rstrip("."),
            "-c:v", "libx264",
            "-preset", burn_config["preset"],
            "-crf", burn_config["crf"],
            "-maxrate", burn_config["maxrate"],
            "-bufsize", burn_config["bufsize"],
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-level:v", "4.1",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-movflags", "+faststart",
            str(output_clip),
        ])
        _run_command(command, cwd=BASE_DIR)

    _update_translate_progress(job_id, 86, "处理版本二：正在截取前三个高光片段", step="editing")
    for index, segment in enumerate(segments, start=1):
        clip_file = work_dir / f"{output_file.stem}_intro_{index}.mp4"
        encode_clip(source_file, clip_file, start=segment["start"], end=segment["end"])
        clip_files.append(clip_file)

    _update_translate_progress(job_id, 91, "处理版本二：正在拼接高光开头与正片", step="editing")
    encode_clip(processed_file, normalized_main)
    concat_lines = [f"file '{_ffmpeg_concat_file_path(path)}'" for path in [*clip_files, normalized_main]]
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")
    _run_command([
        ffmpeg,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_tmp),
    ], cwd=BASE_DIR)
    _replace_output_file(final_tmp, output_file)
    return {
        "path": output_file,
        "segments": segments,
        "skipped": False,
        "reason": "",
    }


def _format_segment_time(seconds):
    seconds = max(0, int(float(seconds or 0)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _format_transcript_for_model(segments):
    lines = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = _format_segment_time(segment.get("start"))
        end = _format_segment_time(segment.get("end"))
        lines.append(f"[{start}-{end}] {text}")
    return "\n".join(lines)


def _split_transcript_lines(text, max_chars):
    lines = text.splitlines()
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks or [text[:max_chars]]


def _extract_json_object(text):
    content = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.S)
    if fenced:
        content = fenced.group(1).strip()
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
    return json.loads(content)


def _call_llm_json(messages, max_tokens=1800):
    if not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY，无法生成处理版本二的剪辑方案。")
    if not LLM_BASE_URL or not LLM_MODEL:
        raise RuntimeError("LLM_BASE_URL 或 LLM_MODEL 未配置，无法生成剪辑方案。")

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    started_at = time.time()

    def request_completion(current_payload):
        request_body = json.dumps(current_payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{LLM_BASE_URL}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        data = request_completion(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "response_format" in payload:
            payload.pop("response_format", None)
            try:
                data = request_completion(payload)
            except urllib.error.HTTPError as retry_exc:
                retry_body = retry_exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"模型接口调用失败 HTTP {retry_exc.code}: {retry_body[:500]}") from retry_exc
        else:
            raise RuntimeError(f"模型接口调用失败 HTTP {exc.code}: {body[:500]}") from exc

    message = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    result = _extract_json_object(message)
    usage = data.get("usage") or {}
    total_tokens = int(usage.get("total_tokens") or 0)
    return result, {
        "provider": "openai-compatible",
        "model": LLM_MODEL,
        "latencyMs": round((time.time() - started_at) * 1000, 2),
        "tokens": total_tokens,
        "totalTokens": total_tokens,
        "promptTokens": int(usage.get("prompt_tokens") or 0),
        "completionTokens": int(usage.get("completion_tokens") or 0),
    }


def _editing_analysis_system_prompt():
    return (
        "你是 Vidferry 的短视频二创剪辑策划助手。"
        "你的任务是基于英文转写和视频元数据，找出适合中文平台二次创作的高光片段。"
        "优先选择外国人明显震惊、惊喜、反差、夸赞中国效率/安全/城市/交通/消费/服务的内容，"
        "尤其关注中外对比、认知反转和可做钩子的片段。"
        "高光片段必须短而明确，每个片段时长控制在 5-10 秒，禁止返回超过 10 秒的片段；"
        "如果原始亮点更长，需要拆分成多个 5-10 秒片段或选取最有冲击力的 5-10 秒。"
        "所有高光片段必须严格按照视频时间轴升序排列，即 start 从小到大输出。"
        "publish_copy 只写正文文案，禁止包含 #话题、标签列表、标题类型话题或 hashtags；"
        "所有话题必须只放在 tags 数组中，因为各平台会以独立字段上传话题。"
        "只输出严格 JSON，不要输出 Markdown。"
    )


def _editing_analysis_user_prompt(job, transcript_text, chunk_context=""):
    metadata = {
        "title": job.get("title") or "",
        "channel": job.get("channel") or "",
        "subscribers": job.get("subscribers") or "",
        "publishedAt": job.get("publishedAt") or "",
        "url": job.get("url") or "",
    }
    return (
        f"视频元数据：{json.dumps(metadata, ensure_ascii=False)}\n"
        f"{chunk_context}\n"
        "请生成处理版本二的剪辑方案。输出 JSON 字段必须包含："
        "summary 字符串；china_view_angle 字符串；title_options 字符串数组；"
        "publish_copy 字符串，必须是不带 #话题/标签的正文文案；tags 字符串数组，单独存放话题；"
        "highlight_segments 数组，每项包含 start 数字秒、end 数字秒、type 字符串、reason 字符串、suggested_caption 字符串；"
        "risk_notes 字符串数组；editing_focus 字符串。"
        "不要在 publish_copy 末尾追加 #中国旅行 #老外看中国 这类话题，也不要把话题写成正文的一部分；"
        "highlight_segments 控制在 5-8 个，优先外国人震惊点和中外对比点；"
        "每个片段 end - start 必须在 5 到 10 秒之间，没有明确时间也要根据转写时间估计；"
        "highlight_segments 必须按 start 从小到大排序，方便后续按时间顺序进行高光剪辑。\n"
        f"转写内容：\n{transcript_text}"
    )


def _summarize_transcript_chunks(job, transcript_text):
    max_chars = max(4000, LLM_MAX_TRANSCRIPT_CHARS)
    chunks = _split_transcript_lines(transcript_text, max_chars)
    if len(chunks) <= 1:
        return transcript_text, None

    summaries = []
    usage_total = {"tokens": 0, "totalTokens": 0, "promptTokens": 0, "completionTokens": 0, "latencyMs": 0}
    for index, chunk in enumerate(chunks, start=1):
        result, usage = _call_llm_json([
            {"role": "system", "content": _editing_analysis_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"这是第 {index}/{len(chunks)} 段转写。请只输出 JSON："
                    "chunk_summary 字符串；highlight_candidates 数组，每项包含 start、end、type、reason、suggested_caption。"
                    "重点找外国人震惊、认知反转、中外对比。\n"
                    f"{chunk}"
                ),
            },
        ], max_tokens=1200)
        summaries.append(result)
        usage_total["tokens"] += int(usage.get("tokens") or 0)
        usage_total["totalTokens"] += int(usage.get("totalTokens") or usage.get("tokens") or 0)
        usage_total["promptTokens"] += int(usage.get("promptTokens") or 0)
        usage_total["completionTokens"] += int(usage.get("completionTokens") or 0)
        usage_total["latencyMs"] += float(usage.get("latencyMs") or 0)
    return json.dumps(summaries, ensure_ascii=False), usage_total


def _normalize_highlight_segments(segments):
    if not isinstance(segments, list):
        return []

    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            start = max(0.0, float(segment.get("start") or 0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(segment.get("end") or 0)
        except (TypeError, ValueError):
            end = 0.0
        if end <= start:
            end = start + 5
        duration = end - start
        if duration < 5:
            end = start + 5
        elif duration > 10:
            end = start + 10
        normalized.append({
            **segment,
            "start": round(start, 2),
            "end": round(end, 2),
        })
    return sorted(normalized, key=lambda item: (item.get("start") or 0, item.get("end") or 0))


def _strip_topics_from_publish_copy(value):
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"[ \t]*(?:#[\w\u4e00-\u9fff-]+[ \t]*)+$", "", text).strip()
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and re.fullmatch(r"\s*(?:#[\w\u4e00-\u9fff-]+[\s,，、]*)+\s*", lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _generate_editing_plan(job, segments):
    transcript_text = _format_transcript_for_model(segments)
    if not transcript_text.strip():
        raise NoSpeechDetectedError("未识别到可用于剪辑分析的字幕文本。")

    compact_text, chunk_usage = _summarize_transcript_chunks(job, transcript_text)
    chunk_context = ""
    if chunk_usage:
        chunk_context = "下面是长视频分块后的摘要和候选片段，请基于它们汇总最终剪辑方案。"

    result, usage = _call_llm_json([
        {"role": "system", "content": _editing_analysis_system_prompt()},
        {"role": "user", "content": _editing_analysis_user_prompt(job, compact_text, chunk_context)},
    ], max_tokens=2200)
    if chunk_usage:
        base_tokens = int(usage.get("tokens") or 0)
        usage["tokens"] = base_tokens + int(chunk_usage.get("tokens") or 0)
        usage["totalTokens"] = base_tokens + int(chunk_usage.get("totalTokens") or chunk_usage.get("tokens") or 0)
        usage["promptTokens"] = int(usage.get("promptTokens") or 0) + int(chunk_usage.get("promptTokens") or 0)
        usage["completionTokens"] = int(usage.get("completionTokens") or 0) + int(chunk_usage.get("completionTokens") or 0)
        usage["latencyMs"] = round(float(usage.get("latencyMs") or 0) + float(chunk_usage.get("latencyMs") or 0), 2)

    result.setdefault("summary", "")
    result.setdefault("china_view_angle", "")
    result.setdefault("title_options", [])
    result.setdefault("publish_copy", "")
    result["publish_copy"] = _strip_topics_from_publish_copy(result.get("publish_copy"))
    result.setdefault("tags", [])
    result.setdefault("highlight_segments", [])
    result["highlight_segments"] = _normalize_highlight_segments(result.get("highlight_segments"))
    result.setdefault("risk_notes", [])
    result["editing_focus"] = result.get("editing_focus") or "foreigner_shock_and_country_comparison"
    result["process_version"] = PROCESS_VERSION_EDITING
    result["model"] = {
        "provider": usage.get("provider") or "openai-compatible",
        "name": usage.get("model") or LLM_MODEL,
    }
    return result, usage


def _process_editing_plan(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_editing_work")
    job_id = job.get("id")
    update_youtube_workflow_job(
        job_id,
        step="analysis",
        message="处理版本二：正在准备转写与高光片段分析",
        progress=12,
        speed="",
        eta="",
    )
    segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir, progress_base=18, progress_done=46)
    update_youtube_workflow_job(
        job_id,
        step="analysis",
        message="转写完成，正在生成剪辑方案",
        progress=58,
    )
    result, usage = _generate_editing_plan(job, segments)
    save_youtube_video_analysis(job.get("videoId"), {
        **result,
        "transcriptLanguage": language or "",
        "transcriptFilePath": str(transcript_file),
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    return result, usage


def _analysis_error_payload(exc, job=None):
    return {
        "summary": "",
        "china_view_angle": "",
        "title_options": [],
        "publish_copy": "",
        "tags": [],
        "highlight_segments": [],
        "risk_notes": ["内容分析失败，请检查模型配置或稍后重试。"],
        "error": {
            "code": "VF-ANALYSIS-FAILED",
            "type": exc.__class__.__name__,
            "reason": str(exc),
        },
        "process_version": (job or {}).get("processVersion") or PROCESS_VERSION_TRANSLATION,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _run_analysis_from_transcript_job(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_analysis_work")
    job_id = job.get("id")
    update_youtube_workflow_job(
        job_id,
        status="running",
        step="analysis",
        message="正在复用转写文本生成发布文案",
        source_file_path=str(source_file),
        progress=12,
        speed="",
        eta="",
    )
    update_youtube_video_analysis_status(job.get("videoId"), 2)
    segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir, progress_base=16, progress_done=42)
    update_youtube_workflow_job(
        job_id,
        message="转写文本准备完成，正在调用模型生成标题、文案和标签",
        progress=58,
    )
    result, usage = _generate_editing_plan(job, segments)
    result["process_version"] = job.get("processVersion") or PROCESS_VERSION_TRANSLATION
    save_youtube_video_analysis(job.get("videoId"), {
        **result,
        "transcriptLanguage": language or "",
        "transcriptFilePath": str(transcript_file),
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    update_youtube_workflow_job(
        job_id,
        status="success",
        step="done",
        message="发布文案与内容总结已生成",
        progress=100,
        speed="",
        eta="",
    )
    return result, usage


def maybe_start_youtube_analysis_job(base_job, source_file=None, force=False):
    video_id = (base_job or {}).get("videoId") or ""
    if not video_id:
        return None

    init_youtube_workflow_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT analysis_status FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        if not row:
            return None
        analysis_status = int(row["analysis_status"] or 0)
        if not force and analysis_status in {1, 2}:
            return None
        if not force and _active_analysis_job_for_video(cursor, video_id):
            return None

    payload = {
        **base_job,
        "account": "",
        "publishToDouyin": False,
        "publishToBilibili": False,
        "processVersion": base_job.get("processVersion") or PROCESS_VERSION_TRANSLATION,
        "description": base_job.get("description") or "",
        "tags": base_job.get("tags") or [],
        "schedule": "",
    }
    job = create_youtube_workflow_job(payload)
    update_youtube_video_analysis_status(video_id, 2)

    thread = threading.Thread(
        target=run_youtube_analysis_job,
        args=(job["id"], str(source_file or "")),
        daemon=True,
    )
    thread.start()
    return job


def _material_file_path(record):
    raw_path = record.get("storage_key") or record.get("file_path") or ""
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return Path(BASE_DIR / "videoFile" / raw_path)


def _material_metadata(record):
    metadata = record.get("metadata") or {}
    if isinstance(metadata, dict):
        return metadata
    try:
        return json.loads(metadata)
    except (TypeError, ValueError):
        return {}


def _material_source_video_id(record):
    metadata = _material_metadata(record)
    return (
        record.get("source_video_id")
        or metadata.get("videoId")
        or metadata.get("sourceVideoId")
        or ""
    )


def _material_process_version(record):
    metadata = _material_metadata(record)
    return metadata.get("processVersion") or ""


def _material_subtitle_language(record):
    metadata = _material_metadata(record)
    return metadata.get("subtitleLanguage") or ""


def _find_latest_youtube_material(cursor, video_id, source_type):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = ?
    ORDER BY upload_time DESC, id DESC
    ''', (source_type,))
    for row in cursor.fetchall():
        record = dict(row)
        if _material_source_video_id(record) == video_id:
            return record
    return None


def _find_latest_processed_material(cursor, video_id, process_version=""):
    if not video_id:
        return None
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    for row in cursor.fetchall():
        record = dict(row)
        if _material_source_video_id(record) != video_id:
            continue
        if process_version and _material_process_version(record) != process_version:
            continue
        return record
    return None


def _delete_replaced_processed_materials(cursor, video_id, process_version, keep_material_id):
    if not video_id or not process_version:
        return []

    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    deleted = []
    for row in cursor.fetchall():
        record = dict(row)
        if int(record.get("id") or 0) == int(keep_material_id or 0):
            continue
        if _material_source_video_id(record) != video_id:
            continue
        if _material_process_version(record) != process_version:
            continue

        deleted.append({
            "id": record.get("id"),
            "filename": record.get("filename"),
            "processVersion": process_version,
            "files": _delete_material_files(record),
        })
        cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
    return deleted


def _sync_youtube_processed_state(cursor, video_id):
    remaining = _find_latest_processed_material(cursor, video_id)
    remaining_path = str(_material_file_path(remaining)) if remaining else ""
    if remaining:
        cursor.execute('''
        UPDATE youtube_videos
        SET translate_status = CASE
                WHEN translate_status IN (1, 2) THEN translate_status
                ELSE 1
            END,
            processed_file_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
        ''', (remaining_path, video_id))
        return {
            "changed": cursor.rowcount > 0,
            "translateStatus": 1,
            "processedFilePath": remaining_path,
            "remainingMaterialId": remaining.get("id"),
            "remainingProcessVersion": _material_process_version(remaining),
        }

    cursor.execute('''
    UPDATE youtube_videos
    SET translate_status = 0,
        publish_status = 0,
        processed_file_path = '',
        analysis_status = 0,
        analysis_result = '',
        publish_draft = '',
        analysis_updated_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE video_id = ?
    ''', (video_id,))
    return {
        "changed": cursor.rowcount > 0,
        "translateStatus": 0,
        "publishStatus": 0,
        "processedFilePath": "",
        "analysisStatus": 0,
        "analysisCleared": True,
    }


def _clear_youtube_analysis_state(cursor, video_id):
    cursor.execute('''
    UPDATE youtube_videos
    SET analysis_status = 0,
        analysis_result = '',
        publish_draft = '',
        analysis_updated_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE video_id = ?
    ''', (video_id,))
    return {
        "analysisStatus": 0,
        "analysisCleared": cursor.rowcount > 0,
    }


def _delete_material_files(record):
    deleted_files = []
    file_path = _material_file_path(record)
    candidates = []
    if file_path:
        candidates.append(file_path)
        if record.get("source_type") == "youtube_download":
            candidates.extend(file_path.with_suffix(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))

    seen = set()
    for path in candidates:
        if not path:
            continue
        path_key = str(path)
        if path_key in seen:
            continue
        seen.add(path_key)
        if path.exists():
            try:
                path.unlink()
                deleted_files.append(path_key)
            except Exception as exc:
                print(f"⚠️ 删除素材文件失败: {path} {exc}")
    return deleted_files


def delete_material_record(cursor, file_id):
    cursor.execute("SELECT * FROM file_records WHERE id = ?", (file_id,))
    record = cursor.fetchone()
    if not record:
        raise LookupError("File not found")

    record = dict(record)
    source_video_id = _material_source_video_id(record)
    if source_video_id:
        _assert_no_active_youtube_job(cursor, source_video_id)

    deleted_files = _delete_material_files(record)
    cursor.execute("DELETE FROM file_records WHERE id = ?", (file_id,))
    sync_result = _sync_youtube_video_after_material_delete(cursor, record)
    return {
        "id": record["id"],
        "filename": record["filename"],
        "deletedFiles": deleted_files,
        "sync": sync_result,
    }


def delete_material_records(file_ids):
    init_database_tables()
    results = []
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_id in file_ids:
            try:
                result = delete_material_record(cursor, file_id)
                results.append({"id": file_id, "success": True, "data": result})
            except WorkflowConflictError as exc:
                results.append({
                    "id": file_id,
                    "success": False,
                    "message": str(exc),
                    "errorCode": exc.error_code,
                    "errorType": exc.error_type,
                })
            except Exception as exc:
                results.append({"id": file_id, "success": False, "message": str(exc)})
        conn.commit()
    return {
        "total": len(file_ids),
        "success": sum(1 for item in results if item.get("success")),
        "failed": sum(1 for item in results if not item.get("success")),
        "items": results,
    }


def _delete_youtube_download_materials_for_video(cursor, video_id, video_row=None):
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_download'
    ORDER BY upload_time DESC, id DESC
    ''')
    records = [
        dict(row)
        for row in cursor.fetchall()
        if _material_source_video_id(dict(row)) == video_id
    ]

    deleted = []
    for record in records:
        deleted.append({
            "id": record.get("id"),
            "filename": record.get("filename"),
            "files": _delete_material_files(record),
        })
        cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))

    downloaded_file_path = (video_row or {}).get("downloaded_file_path") or ""
    if downloaded_file_path and not any(str(_material_file_path(record)) == downloaded_file_path for record in records):
        extra_record = {
            "source_type": "youtube_download",
            "file_path": downloaded_file_path,
            "storage_key": downloaded_file_path,
        }
        deleted.append({
            "id": None,
            "filename": Path(downloaded_file_path).name,
            "files": _delete_material_files(extra_record),
        })

    return deleted


def _sync_youtube_video_after_material_delete(cursor, deleted_record):
    source_type = deleted_record.get("source_type") or ""
    video_id = _material_source_video_id(deleted_record)
    if not video_id or source_type not in {"youtube_processed", "youtube_download"}:
        return None

    sync_result = {
        "videoId": video_id,
        "sourceType": source_type,
        "changed": False,
    }
    remaining = _find_latest_youtube_material(cursor, video_id, source_type)
    remaining_path = str(_material_file_path(remaining)) if remaining else ""

    if source_type == "youtube_processed":
        sync_result.update(_sync_youtube_processed_state(cursor, video_id))
        if not sync_result.get("analysisCleared"):
            sync_result.update(_clear_youtube_analysis_state(cursor, video_id))
    elif source_type == "youtube_download":
        if remaining:
            cursor.execute('''
            UPDATE youtube_videos
            SET download_status = 1,
                downloaded_file_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (remaining_path, video_id))
            sync_result.update({
                "changed": cursor.rowcount > 0,
                "downloadStatus": 1,
                "downloadedFilePath": remaining_path,
            })
        else:
            cursor.execute('''
            UPDATE youtube_videos
            SET download_status = 0,
                downloaded_file_path = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
            ''', (video_id,))
            sync_result.update({
                "changed": cursor.rowcount > 0,
                "downloadStatus": 0,
                "downloadedFilePath": "",
            })

    cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
    row = cursor.fetchone()
    if row:
        sync_result["video"] = _row_to_youtube_video(row)
    return sync_result


def verify_youtube_file_consistency():
    init_database_tables()
    summary = {
        "checkedVideos": 0,
        "fixedDownloadStatus": 0,
        "fixedProcessStatus": 0,
        "removedMaterialRecords": 0,
        "issues": [],
    }
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM file_records")
        for row in cursor.fetchall():
            record = dict(row)
            source_type = record.get("source_type") or ""
            if source_type not in {"youtube_download", "youtube_processed"}:
                continue
            path = _material_file_path(record)
            if path and path.exists():
                continue
            cursor.execute("DELETE FROM file_records WHERE id = ?", (record.get("id"),))
            summary["removedMaterialRecords"] += 1
            summary["issues"].append({
                "type": "missing_material_file",
                "materialId": record.get("id"),
                "sourceType": source_type,
                "videoId": _material_source_video_id(record),
                "path": str(path) if path else "",
            })
            _sync_youtube_video_after_material_delete(cursor, record)

        cursor.execute("SELECT * FROM youtube_videos")
        for row in cursor.fetchall():
            video = dict(row)
            video_id = video.get("video_id") or ""
            summary["checkedVideos"] += 1

            downloaded_file = video.get("downloaded_file_path") or ""
            if int(video.get("download_status") or 0) == 1 and downloaded_file:
                if not Path(downloaded_file).is_file():
                    remaining = _find_latest_youtube_material(cursor, video_id, "youtube_download")
                    if remaining:
                        remaining_path = str(_material_file_path(remaining) or "")
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET downloaded_file_path = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (remaining_path, video_id))
                    else:
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET download_status = 0,
                            downloaded_file_path = '',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (video_id,))
                        summary["fixedDownloadStatus"] += 1
                    summary["issues"].append({
                        "type": "missing_downloaded_file",
                        "videoId": video_id,
                        "path": downloaded_file,
                    })

            processed_file = video.get("processed_file_path") or ""
            if int(video.get("translate_status") or 0) in {1, 2} and processed_file:
                if not Path(processed_file).is_file():
                    remaining = _find_latest_youtube_material(cursor, video_id, "youtube_processed")
                    if remaining:
                        remaining_path = str(_material_file_path(remaining) or "")
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET processed_file_path = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (remaining_path, video_id))
                    else:
                        cursor.execute('''
                        UPDATE youtube_videos
                        SET translate_status = 0,
                            publish_status = 0,
                            processed_file_path = '',
                            analysis_status = 0,
                            analysis_result = '',
                            publish_draft = '',
                            analysis_updated_at = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE video_id = ?
                        ''', (video_id,))
                        summary["fixedProcessStatus"] += 1
                    summary["issues"].append({
                        "type": "missing_processed_file",
                        "videoId": video_id,
                        "path": processed_file,
                    })

        conn.commit()
    return summary


def _format_duration_label(seconds):
    seconds = int(round(float(seconds or 0)))
    if seconds <= 0:
        return ""
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def _material_duration(record, source_video=None):
    metadata = record.get("metadata") or {}
    duration = record.get("duration") or metadata.get("duration") or (source_video or {}).get("duration") or ""
    duration_seconds = float(record.get("duration_seconds") or 0)
    if duration:
        return duration, duration_seconds

    file_path = _material_file_path(record)
    if not file_path or not file_path.is_file():
        return "", 0

    try:
        duration_seconds = _get_media_duration_seconds(file_path)
    except Exception:
        duration_seconds = 0
    return _format_duration_label(duration_seconds), duration_seconds


def _row_to_material(row):
    item = dict(row)
    metadata = _material_metadata(item)
    if not item.get("asset_id"):
        item["asset_id"] = ""
    item["uuid"] = item.get("asset_id") or ""
    item["storage_key"] = item.get("storage_key") or item.get("file_path") or ""
    item["storage_backend"] = item.get("storage_backend") or "local"
    item["source_type"] = item.get("source_type") or "manual_upload"
    item["source_video_id"] = item.get("source_video_id") or ""
    item["status"] = item.get("status") or "ready"
    item["metadata"] = metadata
    source_video = None
    if item["source_video_id"]:
        try:
            source_video = _get_youtube_video_record(item["source_video_id"])
        except Exception:
            source_video = None

    display_title = metadata.get("title") or (source_video or {}).get("title") or item.get("original_filename") or item.get("filename") or ""
    display_url = metadata.get("url") or (source_video or {}).get("url") or ""
    display_channel = metadata.get("channel") or (source_video or {}).get("channel") or ""
    display_subscribers = metadata.get("subscribers") or (source_video or {}).get("subscribers") or ""
    display_published_at = metadata.get("publishedAt") or (source_video or {}).get("publishedAt") or ""
    video_id = metadata.get("videoId") or item.get("source_video_id") or (source_video or {}).get("id") or ""
    display_thumbnail = metadata.get("thumbnail") or (source_video or {}).get("thumbnail") or _youtube_thumbnail_url(video_id)
    duration_label, duration_seconds = _material_duration(item, source_video)
    inferred_language = _infer_subtitle_language_from_filename(item.get("filename")) if item["source_type"] == "youtube_processed" else ""
    subtitle_language = metadata.get("subtitleLanguage") or inferred_language
    language_meta = None
    if subtitle_language:
        subtitle_language, language_meta = _subtitle_language_meta(subtitle_language)

    item["displayTitle"] = display_title
    item["displayUrl"] = display_url
    item["displayChannel"] = display_channel
    item["displaySubscribers"] = _format_subscribers_w(display_subscribers) if display_subscribers else ""
    item["displayPublishedAt"] = display_published_at
    item["displayThumbnail"] = display_thumbnail
    item["duration"] = duration_label
    item["durationSeconds"] = round(float(duration_seconds or 0), 2)
    item["processVersion"] = metadata.get("processVersion") or "translation_v1"
    item["processType"] = "字幕处理/信息烧录" if item["source_type"] == "youtube_processed" else "原视频下载"
    item["subtitleLanguage"] = subtitle_language or ""
    item["subtitleLanguageLabel"] = metadata.get("subtitleLanguageLabel") or (language_meta or {}).get("label") or ""
    item["analysisStatus"] = int((source_video or {}).get("analysisStatus") or 0)
    item["analysisResult"] = {}
    item["publishDraft"] = {}
    if item["source_type"] == "youtube_processed" and video_id:
        try:
            analysis = get_youtube_video_analysis(video_id)
            item["analysisResult"] = analysis.get("result") or {}
            item["publishDraft"] = analysis.get("draft") or {}
        except Exception:
            item["analysisResult"] = {}
            item["publishDraft"] = {}
    return item


def _row_to_published_material(row):
    item = dict(row)
    try:
        metadata = json.loads(item.get("metadata") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": item.get("id"),
        "videoId": item.get("video_id") or "",
        "sourceUrl": item.get("source_url") or "",
        "title": item.get("title") or "",
        "platform": item.get("platform") or "",
        "accountCount": int(item.get("account_count") or 0),
        "materialId": item.get("material_id"),
        "filename": item.get("filename") or "",
        "filePath": item.get("file_path") or "",
        "filesize": float(item.get("filesize") or 0),
        "thumbnail": item.get("thumbnail") or "",
        "channel": item.get("channel") or "",
        "subscribers": item.get("subscribers") or "",
        "sourcePublishedAt": item.get("source_published_at") or "",
        "publishTitle": item.get("publish_title") or "",
        "metadata": metadata,
        "publishedAt": item.get("published_at") or item.get("created_at") or "",
        "createdAt": item.get("created_at") or "",
    }


def list_published_youtube_materials(limit=50):
    init_database_tables()
    limit = max(1, min(int(limit or 50), 200))
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM published_youtube_materials
        ORDER BY published_at DESC, id DESC
        LIMIT ?
        ''', (limit,))
        return [_row_to_published_material(row) for row in cursor.fetchall()]


def _published_youtube_identity_sets(cursor):
    cursor.execute("SELECT video_id, source_url FROM published_youtube_materials")
    published_ids = set()
    published_urls = set()
    for row in cursor.fetchall():
        video_id = row["video_id"] or ""
        source_url = row["source_url"] or ""
        extracted_id = _extract_youtube_video_id(source_url)
        if video_id:
            published_ids.add(video_id)
        if extracted_id:
            published_ids.add(extracted_id)
        canonical_url = _canonical_youtube_url(source_url, video_id or extracted_id)
        if canonical_url:
            published_urls.add(canonical_url)
    return published_ids, published_urls


def _archive_published_material(cursor, material, video, platform_name, published_at, publish_title="", account_count=0):
    video_id = material.get("source_video_id") or _material_source_video_id(material) or (video or {}).get("id") or ""
    source_url = _canonical_youtube_url((video or {}).get("url") or material.get("displayUrl") or "", video_id)
    title = (video or {}).get("title") or material.get("displayTitle") or material.get("original_filename") or material.get("filename") or ""
    metadata = {
        "materialMetadata": material.get("metadata") or {},
        "sourceVideo": video or {},
        "archivedFrom": "publish_success",
    }
    cursor.execute('''
    INSERT INTO published_youtube_materials (
        video_id, source_url, title, platform, account_count, material_id,
        filename, file_path, filesize, thumbnail, channel, subscribers,
        source_published_at, publish_title, metadata, published_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        video_id,
        source_url,
        title,
        platform_name or "",
        int(account_count or 0),
        material.get("id"),
        material.get("filename") or "",
        str(_material_file_path(material) or material.get("file_path") or ""),
        float(material.get("filesize") or 0),
        material.get("displayThumbnail") or (video or {}).get("thumbnail") or "",
        material.get("displayChannel") or (video or {}).get("channel") or "",
        material.get("displaySubscribers") or (video or {}).get("subscribers") or "",
        material.get("displayPublishedAt") or (video or {}).get("publishedAt") or "",
        publish_title or "",
        json.dumps(metadata, ensure_ascii=False),
        published_at,
    ))


def _list_processed_versions_for_video(cursor, video_id):
    if not video_id:
        return []
    cursor.execute('''
    SELECT * FROM file_records
    WHERE source_type = 'youtube_processed'
    ORDER BY upload_time DESC, id DESC
    ''')
    versions = {}
    for row in cursor.fetchall():
        record = _row_to_material(row)
        if _material_source_video_id(record) != video_id:
            continue
        process_version = record.get("processVersion") or _material_process_version(record) or "translation_v1"
        if process_version in versions:
            continue
        versions[process_version] = {
            "materialId": record.get("id"),
            "filename": record.get("filename") or "",
            "filePath": str(_material_file_path(record) or ""),
            "processVersion": process_version,
            "processType": record.get("processType") or "",
            "subtitleLanguage": record.get("subtitleLanguage") or _material_subtitle_language(record),
            "subtitleLanguageLabel": record.get("subtitleLanguageLabel") or "",
            "duration": record.get("duration") or "",
            "filesize": record.get("filesize") or 0,
            "createdAt": record.get("upload_time") or "",
        }
    return list(versions.values())


def register_material(
    source_file,
    *,
    original_filename=None,
    source_type="manual_upload",
    source_video_id="",
    metadata=None,
    copy_to_library=False,
):
    init_database_tables()
    asset_id = uuid.uuid4().hex
    source_path = Path(source_file)
    if copy_to_library:
        target_dir = _ensure_dir(Path(BASE_DIR / "videoFile"))
        suffix = source_path.suffix or ".mp4"
        storage_key = f"{asset_id}{suffix}"
        stored_path = target_dir / storage_key
        shutil.copy2(source_path, stored_path)
        file_path_value = storage_key
    else:
        stored_path = source_path
        file_path_value = str(source_path)

    metadata_payload = metadata or {}
    duration_seconds = 0
    duration_label = metadata_payload.get("duration") or ""
    if source_path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"}:
        try:
            duration_seconds = _get_media_duration_seconds(stored_path)
            duration_label = duration_label or _format_duration_label(duration_seconds)
        except Exception:
            duration_seconds = 0
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?", (file_path_value, file_path_value))
        existing = cursor.fetchone()
        if existing:
            return _row_to_material(existing)
        cursor.execute('''
        INSERT INTO file_records (
            asset_id, filename, original_filename, filesize, file_path, storage_key,
            storage_backend, source_type, source_video_id, status, duration, duration_seconds, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id,
            source_path.name,
            original_filename or source_path.name,
            round(float(stored_path.stat().st_size) / (1024 * 1024), 2),
            file_path_value,
            file_path_value,
            "local",
            source_type,
            source_video_id or "",
            "ready",
            duration_label,
            round(float(duration_seconds or 0), 2),
            json.dumps(metadata_payload, ensure_ascii=False),
        ))
        conn.commit()
        cursor.execute("SELECT * FROM file_records WHERE id = ?", (cursor.lastrowid,))
        return _row_to_material(cursor.fetchone())


def _youtube_material_metadata(job, stage):
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    return {
        "stage": stage,
        "videoId": job.get("videoId") or "",
        "url": job.get("url") or "",
        "title": job.get("title") or "",
        "channel": job.get("channel") or "",
        "subscribers": job.get("subscribers") or "",
        "publishedAt": job.get("publishedAt") or "",
        "processVersion": job.get("processVersion") or "translation_v1",
        "subtitleLanguage": target_language,
        "subtitleLanguageLabel": language_meta["label"],
        "subtitleSize": _normalize_subtitle_size(job.get("subtitleSize")),
        "translatorLabel": _normalize_translator_label(job.get("translatorLabel")),
    }


def _save_processed_video_to_material(file_path, job=None):
    job = job or {}
    material = register_material(
        file_path,
        source_type="youtube_processed",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "processed"),
        copy_to_library=True,
    )
    video_id = job.get("videoId") or ""
    process_version = job.get("processVersion") or "translation_v1"
    if video_id:
        with sqlite3.connect(_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            replaced = _delete_replaced_processed_materials(
                cursor,
                video_id,
                process_version,
                material.get("id"),
            )
            sync_result = _sync_youtube_processed_state(cursor, video_id)
            conn.commit()
        material["replacedMaterials"] = replaced
        material["sync"] = sync_result
    return material


def _register_downloaded_video_material(file_path, job=None):
    job = job or {}
    return register_material(
        file_path,
        source_type="youtube_download",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "downloaded"),
        copy_to_library=False,
    )


def _validate_publish_processed_files(file_list):
    if not file_list:
        raise ValueError("文件列表不能为空")

    normalized_paths = [str(item or "").strip() for item in file_list if str(item or "").strip()]
    if len(normalized_paths) != len(file_list):
        raise ValueError("文件列表包含无效路径")

    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_path in normalized_paths:
            cursor.execute(
                "SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?",
                (file_path, file_path),
            )
            record = cursor.fetchone()
            if not record:
                raise ValueError(f"发布文件未登记到素材库: {file_path}")
            material = _row_to_material(record)
            if material.get("source_type") != "youtube_processed":
                raise ValueError("发布中心只支持处理后视频，请先完成字幕处理和兼容转码。")
            resolved_path = _material_file_path(material)
            if not resolved_path or not resolved_path.is_file():
                raise ValueError(f"处理后视频文件不存在: {file_path}")
    return normalized_paths


def _mark_published_materials(file_list, platform_type=None, title="", account_count=0):
    if not file_list:
        return []

    platform_map = {
        1: "小红书",
        2: "视频号",
        3: "抖音",
        4: "快手",
    }
    try:
        platform_name = platform_map.get(int(platform_type or 0), str(platform_type or ""))
    except (TypeError, ValueError):
        platform_name = str(platform_type or "")
    published_at = _now_iso()
    updated = []

    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for file_path in file_list:
            cursor.execute(
                "SELECT * FROM file_records WHERE file_path = ? OR storage_key = ?",
                (file_path, file_path),
            )
            record = cursor.fetchone()
            if not record:
                continue
            material = _row_to_material(record)
            video_id = material.get("source_video_id") or _material_source_video_id(material)
            if not video_id:
                continue

            video = _get_youtube_video_record(video_id) or {}
            _archive_published_material(
                cursor,
                material,
                video,
                platform_name,
                published_at,
                publish_title=title,
                account_count=account_count,
            )
            cursor.execute(
                """
                UPDATE youtube_videos
                SET publish_status = 1, updated_at = ?
                WHERE video_id = ?
                """,
                (published_at, video_id),
            )
            cursor.execute(
                """
                UPDATE youtube_workflow_jobs
                SET step = 'publish',
                    message = ?,
                    published_at = ?,
                    publish_command = ?,
                    updated_at = ?
                WHERE video_id = ?
                """,
                (
                    "发布中心已提交发布任务",
                    published_at,
                    f"platform={platform_name}; title={title}; accounts={account_count}",
                    published_at,
                    video_id,
                ),
            )
            updated.append(video_id)
        conn.commit()
    return updated


def _get_youtube_video_record(video_id):
    if not video_id:
        return None
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return _row_to_youtube_video(row) if row else None


def _resolve_downloaded_source_file(job):
    record = _get_youtube_video_record(job.get("videoId"))
    downloaded_path = Path((record or {}).get("downloadedFilePath") or "")
    if downloaded_path.is_file():
        return downloaded_path

    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = ? AND source_type = 'youtube_download'
        ORDER BY upload_time DESC, id DESC
        LIMIT 1
        ''', (job.get("videoId") or "",))
        material = cursor.fetchone()
        if material:
            material_path = _material_file_path(dict(material))
            if material_path and material_path.is_file():
                return material_path

    raise RuntimeError("未找到已下载视频文件，请先执行下载。")


def run_youtube_download_job(job_id):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
        source_file = _download_youtube_video(job)
        finish_workflow_event(event_id, "success", "下载完成", output_file_path=source_file)
        material = _register_downloaded_video_material(source_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="下载完成，已绑定到素材库",
            source_file_path=str(source_file),
            processed_file_path=str(source_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def run_youtube_translate_job(job_id):
    event_id = None
    analysis_event_id = None
    editing_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle",
            message=f"正在准备{language_meta['label']}字幕处理任务",
            progress=2,
            speed="",
            eta="",
        )
        source_file = _resolve_downloaded_source_file(job)

        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="处理版本二：正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在启动转写和处理",
            step="subtitle",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 5,
        )
        subtitle_result = _process_subtitles(job, source_file)
        if process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )
        final_message = "未检测到可识别人声，已跳过字幕处理并保存到素材库" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库"
        if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
            final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
        elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
            final_message = f"{final_message}；未找到可拼接的高光片段"
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            processed_file_path=str(processed_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(editing_event_id or event_id or analysis_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def run_youtube_analysis_job(job_id, source_file_override=""):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="analysis",
            message="正在准备处理版本二剪辑方案",
            progress=4,
            speed="",
            eta="",
        )
        source_file = Path(source_file_override) if source_file_override else _resolve_downloaded_source_file(job)
        event_id = start_workflow_event(job, "analysis", "开始生成发布文案与内容总结", input_file_path=source_file)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在复用转写文本分析内容",
            progress=8,
        )
        result, usage = _run_analysis_from_transcript_job(job, source_file)
        finish_workflow_event(
            event_id,
            "success",
            "发布文案与内容总结已生成",
            cloud_usage={
                "provider": usage.get("provider") or "openai-compatible",
                "model": usage.get("model") or LLM_MODEL,
                "tokens": int(usage.get("tokens") or 0),
                "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                "promptTokens": int(usage.get("promptTokens") or 0),
                "completionTokens": int(usage.get("completionTokens") or 0),
                "latencyMs": float(usage.get("latencyMs") or 0),
            },
            metadata={"highlightCount": len(result.get("highlight_segments") or [])},
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="发布文案与内容总结已生成，可在视频线索中查看",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        try:
            failed_job = get_youtube_workflow_job(job_id)
            update_youtube_video_analysis_status(failed_job.get("videoId"), 3, _analysis_error_payload(exc, failed_job))
        except Exception as status_exc:
            print(f"更新分析失败状态失败: {status_exc}")
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def _publish_to_douyin(job, processed_file):
    if not job["publishToDouyin"] or not job["account"]:
        return ""
    command = [
        SAU_COMMAND,
        "douyin",
        "upload-video",
        "--account",
        job["account"],
        "--file",
        str(processed_file),
        "--title",
        job["title"] or "YouTube 视频",
        "--desc",
        job["description"] or "",
        "--tags",
        ",".join(job["tags"]),
    ]
    if job["schedule"]:
        command.extend(["--schedule", job["schedule"]])
    command.append("--headless")
    _run_command(command, cwd=BASE_DIR)
    return " ".join(command)


def _publish_to_bilibili(job, processed_file):
    if not job["publishToBilibili"] or not job["bilibiliAccount"]:
        return ""
    command = [
        SAU_COMMAND,
        "bilibili",
        "upload-video",
        "--account",
        job["bilibiliAccount"],
        "--file",
        str(processed_file),
        "--title",
        job["title"] or "YouTube 视频",
        "--desc",
        job["description"] or job["url"] or "",
        "--tid",
        str(job["bilibiliTid"] or 249),
        "--tags",
        ",".join(job["tags"]),
    ]
    if job["schedule"]:
        command.extend(["--schedule", job["schedule"]])
    _run_command(command, cwd=BASE_DIR)
    return " ".join(command)


def _publish_center_to_bilibili(title, description, file_list, tags, account_list, tid=249, enable_timer=False, videos_per_day=1, daily_times=None, start_days=0):
    if ensure_biliup_binary is None:
        raise RuntimeError("后端未加载 B 站 biliup 运行时，请检查依赖。")

    biliup_binary = ensure_biliup_binary(force_check=False)
    files = [Path(BASE_DIR / "videoFile" / file) for file in file_list]
    account_files = [Path(BASE_DIR / "cookiesFile" / file) for file in account_list]
    if enable_timer:
        try:
            from utils.files_times import generate_schedule_time_next_day
            normalized_daily_times = []
            for item in daily_times or []:
                if isinstance(item, str) and ":" in item:
                    normalized_daily_times.append(int(item.split(":", 1)[0]))
                else:
                    normalized_daily_times.append(int(item))
            publish_datetimes = generate_schedule_time_next_day(len(files), videos_per_day, normalized_daily_times, start_days=start_days)
        except Exception:
            publish_datetimes = [0 for _ in files]
    else:
        publish_datetimes = [0 for _ in files]

    for index, file in enumerate(files):
        if not file.is_file():
            raise RuntimeError(f"B站发布文件不存在: {file}")
        for cookie in account_files:
            if not cookie.is_file():
                raise RuntimeError(f"B站 Cookie 文件不存在: {cookie}")
            command = [
                str(biliup_binary),
                "-u",
                str(cookie),
                "upload",
                str(file),
                "--title",
                title,
                "--desc",
                description or "",
                "--tid",
                str(tid or 249),
            ]
            if tags:
                command.extend(["--tag", ",".join(tags)])
            publish_datetime = publish_datetimes[index] if index < len(publish_datetimes) else 0
            if publish_datetime:
                command.extend(["--dtime", str(int(publish_datetime.timestamp()))])
            result = _run_command(command, cwd=BASE_DIR)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "").strip() or "B站发布失败")


def run_youtube_workflow(job_id):
    workflow_event_id = None
    download_event_id = None
    analysis_event_id = None
    editing_event_id = None
    subtitle_event_id = None
    publish_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        workflow_event_id = start_workflow_event(job, "workflow", "完整工作流开始")
        download_event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
        source_file = _download_youtube_video(job)
        finish_workflow_event(download_event_id, "success", "下载完成", output_file_path=source_file)
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )

        process_version = _normalize_process_version(job.get("processVersion"))
        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="视频已下载，正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message=f"视频已下载，正在处理{language_meta['label']}字幕",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 8,
            speed="",
            eta="",
        )
        subtitle_event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        subtitle_result = _process_subtitles(job, source_file)
        maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(subtitle_event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_workflow_job(
            job_id,
            processed_file_path=str(processed_file),
            step="publish",
            message="未检测到可识别人声，已跳过字幕处理并保存到素材库，准备发布" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库，准备发布",
            progress=96,
            speed="",
            eta="",
        )
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )

        latest_job = get_youtube_workflow_job(job_id)
        publish_commands = []
        publish_event_id = start_workflow_event(latest_job, "publish", "开始发布", input_file_path=processed_file)
        douyin_command = _publish_to_douyin(latest_job, processed_file)
        if douyin_command:
            publish_commands.append(douyin_command)
        bilibili_command = _publish_to_bilibili(latest_job, processed_file)
        if bilibili_command:
            publish_commands.append(bilibili_command)
        final_message = "任务完成"
        if not publish_commands:
            final_message = "任务完成，已保存到素材库，未配置抖音账号所以未发布"
        if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
            final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
        elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
            final_message = f"{final_message}；未找到可拼接的高光片段"
        if skipped_subtitles:
            final_message = f"{final_message}；未检测到可识别人声，已跳过字幕处理"
        finish_workflow_event(publish_event_id, "success", final_message, output_file_path=processed_file)
        finish_workflow_event(workflow_event_id, "success", final_message, output_file_path=processed_file)
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            publish_command="\n".join(publish_commands),
            progress=100,
            speed="",
            eta="",
        )
        if publish_commands:
            update_youtube_video_artifacts(job["videoId"], publish_status=1)
    except Exception as exc:
        finish_workflow_event(publish_event_id or editing_event_id or subtitle_event_id or analysis_event_id or download_event_id or workflow_event_id, "failed", str(exc))
        if workflow_event_id:
            finish_workflow_event(workflow_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
        )


def _extract_yt_initial_data(content):
    marker = "var ytInitialData = "
    start = content.find(marker)
    if start == -1:
        marker = "ytInitialData = "
        start = content.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = content.find(";</script>", start)
    if end == -1:
        end = content.find(";</", start)
    if end == -1:
        return None
    try:
        return json.loads(content[start:end])
    except json.JSONDecodeError:
        return None


def _walk_dict(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dict(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dict(item)


def _text_from_runs(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "simpleText" in value:
            return value["simpleText"]
        if "runs" in value:
            return "".join(run.get("text", "") for run in value["runs"])
    return ""


def _fetch_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _fetch_text(url, timeout=18):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _search_youtube_with_ytdlp(query, limit):
    try:
        import yt_dlp
    except ImportError:
        return []

    ydl_opts = {
        **_base_ytdlp_opts(include_ffmpeg=True),
        "extract_flat": False,
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": True,
    }
    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    for item in data.get("entries") or []:
        if not item:
            continue
        video_id = item.get("id")
        url = item.get("webpage_url") or item.get("url")
        if video_id and (not url or not url.startswith("http")):
            url = f"https://www.youtube.com/watch?v={video_id}"
        results.append({
            "id": video_id or "",
            "title": item.get("title") or "",
            "channel": item.get("channel") or item.get("uploader") or "",
            "subscribers": _format_count(item.get("channel_follower_count")),
            "publishedAt": _parse_upload_date(item.get("upload_date")),
            "url": url or "",
            "thumbnail": (item.get("thumbnail") or ""),
            "duration": item.get("duration_string") or "",
        })
    return results


def _extract_youtube_video_id(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0]
    return ""


def _canonical_youtube_url(url, video_id=""):
    normalized_video_id = video_id or _extract_youtube_video_id(url or "")
    if normalized_video_id:
        return f"https://www.youtube.com/watch?v={normalized_video_id}"
    return (url or "").strip()


def _video_from_ytdlp_info(item, fallback_url=""):
    video_id = item.get("id") or _extract_youtube_video_id(fallback_url)
    url = item.get("webpage_url") or item.get("original_url") or fallback_url
    if video_id and (not url or not str(url).startswith("http")):
        url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id or "",
        "title": item.get("title") or "",
        "channel": item.get("channel") or item.get("uploader") or "",
        "subscribers": _format_subscribers_w(item.get("channel_follower_count")),
        "publishedAt": _parse_upload_date(item.get("upload_date")) or _format_iso_date(item.get("release_date") or ""),
        "url": url or "",
        "thumbnail": item.get("thumbnail") or "",
        "duration": item.get("duration_string") or "",
    }


def _import_youtube_video_by_url(url):
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，请先安装依赖。") from exc

    ydl_opts = {
        **_base_ytdlp_opts(include_ffmpeg=True),
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    video = _video_from_ytdlp_info(info or {}, url)
    if not video.get("id") or not video.get("url"):
        raise RuntimeError("未能识别 YouTube 视频链接。")
    return _enrich_video_from_watch_page(video)


def _search_youtube_fallback(query, limit):
    queries = [query] + [q for q in YOUTUBE_FALLBACK_QUERIES if q != query]
    videos = []
    seen = set()

    for current_query in queries:
        if len(videos) >= limit:
            break
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(current_query)
        try:
            content = _fetch_text(url)
        except Exception:
            continue
        initial_data = _extract_yt_initial_data(content)
        if not initial_data:
            continue
        for node in _walk_dict(initial_data):
            renderer = node.get("videoRenderer")
            if not renderer:
                continue
            video_id = renderer.get("videoId")
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            title = _text_from_runs(renderer.get("title"))
            owner = _text_from_runs(renderer.get("ownerText"))
            published = _text_from_runs(renderer.get("publishedTimeText"))
            thumbnails = renderer.get("thumbnail", {}).get("thumbnails") or []
            videos.append({
                "id": video_id,
                "title": html.unescape(title),
                "channel": html.unescape(owner),
                "subscribers": "",
                "publishedAt": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": thumbnails[-1].get("url", "") if thumbnails else "",
                "duration": _text_from_runs(renderer.get("lengthText")),
            })
            if len(videos) >= limit:
                break

    for video in videos:
        if video["channel"]:
            continue
        try:
            encoded = urllib.parse.quote(video["url"], safe="")
            meta = _fetch_json(f"https://www.youtube.com/oembed?url={encoded}&format=json", timeout=8)
            video["title"] = video["title"] or meta.get("title", "")
            video["channel"] = meta.get("author_name", "")
        except Exception:
            pass
    return videos


def _enrich_video_from_watch_page(video):
    url = video.get("url")
    if not url:
        return video
    try:
        content = _fetch_text(url, timeout=12)
    except Exception:
        return video

    if not video.get("subscribers"):
        subscriber_match = re.search(
            r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"',
            content
        )
        if not subscriber_match:
            subscriber_match = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', content)
        if subscriber_match:
            video["subscribers"] = _format_subscribers_w(html.unescape(subscriber_match.group(1)))

    if not video.get("publishedAt") or " ago" in str(video.get("publishedAt")):
        publish_match = re.search(r'"publishDate":"([^"]+)"', content)
        if not publish_match:
            publish_match = re.search(r'"uploadDate":"([^"]+)"', content)
        if publish_match:
            video["publishedAt"] = _format_iso_date(publish_match.group(1))

    if not video.get("channel"):
        owner_match = re.search(r'"ownerChannelName":"([^"]+)"', content)
        if owner_match:
            video["channel"] = html.unescape(owner_match.group(1))

    return video


def _dedupe_videos(videos, limit):
    filtered = []
    seen = set()
    for video in videos:
        url = video.get("url") or ""
        video_id = video.get("id") or url
        title = video.get("title") or ""
        if not video_id or video_id in seen:
            continue
        if not re.search(r"China|Chinese|Beijing|Shanghai|Shenzhen|Chongqing|Guangzhou|Chengdu|Guilin|Wuhan|Xi", title, re.I):
            continue
        if re.search(r"NYC|New York|accountant", title, re.I):
            continue
        seen.add(video_id)
        filtered.append(video)
        if len(filtered) >= limit:
            break
    return filtered


def _enrich_videos(videos):
    return [_enrich_video_from_watch_page(video) for video in videos]

# 获取当前目录（假设 index.html 和 assets 在这里）
current_dir = os.path.dirname(os.path.abspath(__file__))

# 处理所有静态资源请求（未来打包用）
@app.route('/assets/<filename>')
def custom_static(filename):
    return send_from_directory(os.path.join(current_dir, 'assets'), filename)

# 处理 favicon.ico 静态资源（未来打包用）
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(current_dir, 'assets'), 'vite.svg')

@app.route('/vite.svg')
def vite_svg():
    return send_from_directory(os.path.join(current_dir, 'assets'), 'vite.svg')

# （未来打包用）
@app.route('/')
def index():  # put application's code here
    return send_from_directory(current_dir, 'index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400
    try:
        # 保存文件到指定位置
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        filepath = Path(BASE_DIR / "videoFile" / f"{uuid_v1}_{file.filename}")
        file.save(filepath)
        return jsonify({"code":200,"msg": "File uploaded successfully", "data": f"{uuid_v1}_{file.filename}"}), 200
    except Exception as e:
        return jsonify({"code":500,"msg": str(e),"data":None}), 500

@app.route('/getFile', methods=['GET'])
def get_file():
    # 获取 filename 参数
    filename = request.args.get('filename')

    if not filename:
        return jsonify({"code": 400, "msg": "filename is required", "data": None}), 400

    candidate = Path(filename)
    if candidate.is_absolute():
        allowed_roots = [
            Path(BASE_DIR / "videoFile").resolve(),
            Path(YOUTUBE_DOWNLOAD_DIR).resolve(),
            Path(YOUTUBE_PROCESSED_DIR).resolve(),
        ]
        resolved = candidate.resolve()
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            return jsonify({"code": 400, "msg": "Invalid filename", "data": None}), 400
        if not resolved.is_file():
            return jsonify({"code": 404, "msg": "File not found", "data": None}), 404
        return send_from_directory(str(resolved.parent), resolved.name)

    # 防止路径穿越攻击
    if '..' in filename or filename.startswith('/'):
        return jsonify({"code": 400, "msg": "Invalid filename", "data": None}), 400

    # 拼接完整路径
    file_path = str(Path(BASE_DIR / "videoFile"))

    # 返回文件
    return send_from_directory(file_path,filename)


@app.route('/uploadSave', methods=['POST'])
def upload_save():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400

    # 获取表单中的自定义文件名（可选）
    custom_filename = request.form.get('filename', None)
    if custom_filename:
        filename = custom_filename + "." + file.filename.split('.')[-1]
    else:
        filename = file.filename

    try:
        asset_id = uuid.uuid4().hex
        suffix = Path(filename).suffix or Path(file.filename).suffix
        final_filename = f"{asset_id}{suffix}"
        filepath = Path(BASE_DIR / "videoFile" / final_filename)

        # 保存文件
        file.save(filepath)
        duration_seconds = 0
        duration_label = ""
        if filepath.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"}:
            try:
                duration_seconds = _get_media_duration_seconds(filepath)
                duration_label = _format_duration_label(duration_seconds)
            except Exception:
                duration_seconds = 0

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO file_records (
                asset_id, filename, original_filename, filesize, file_path, storage_key,
                storage_backend, source_type, status, duration, duration_seconds, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id,
                filename,
                file.filename,
                round(float(os.path.getsize(filepath)) / (1024 * 1024), 2),
                final_filename,
                final_filename,
                "local",
                "manual_upload",
                "ready",
                duration_label,
                round(float(duration_seconds or 0), 2),
                json.dumps({"originalUploadName": file.filename}, ensure_ascii=False),
            ))
            conn.commit()
            print("✅ 上传文件已记录")

        return jsonify({
            "code": 200,
            "msg": "File uploaded and saved successfully",
            "data": {
                "filename": filename,
                "filepath": final_filename
            }
        }), 200

    except Exception as e:
        print(f"Upload failed: {e}")
        return jsonify({
            "code": 500,
            "msg": f"upload failed: {e}",
            "data": None
        }), 500

@app.route('/getFiles', methods=['GET'])
def get_all_files():
    try:
        init_database_tables()
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row  # 允许通过列名访问结果
            cursor = conn.cursor()

            # 查询所有记录
            cursor.execute("SELECT * FROM file_records ORDER BY upload_time DESC, id DESC")
            rows = cursor.fetchall()

            data = [
                _attach_material_workflow_state(cursor, _row_to_material(row))
                for row in rows
            ]

            return jsonify({
                "code": 200,
                "msg": "success",
                "data": data
            }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("get file failed!"),
            "data": None
        }), 500


@app.route('/youtube/search', methods=['GET'])
def youtube_search():
    query = request.args.get('query') or YOUTUBE_DEFAULT_QUERY
    try:
        limit = int(request.args.get('limit', 12))
    except (TypeError, ValueError):
        limit = 12
    limit = max(1, min(limit, 30))

    try:
        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        videos = _search_youtube_with_ytdlp(query, limit)
        source = "yt-dlp"
        if not videos:
            videos = _search_youtube_fallback(query, limit)
            source = "youtube-search-page"
        videos = _dedupe_videos(videos, limit)
        videos = _enrich_videos(videos)
        save_result = save_new_youtube_videos(videos, query)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "query": query,
                "source": source,
                "searchedAt": started_at,
                "total": save_result["created"],
                "created": save_result["created"],
                "duplicate": save_result["duplicate"],
                "publishedDuplicate": save_result.get("publishedDuplicate", 0),
                "requested": save_result["requested"],
                "items": save_result["items"],
            }
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"YouTube 查询失败: {str(e)}",
            "data": None
        }), 500


@app.route('/youtube/videos', methods=['GET'])
def youtube_videos():
    try:
        items = list_youtube_videos()
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "total": len(items),
                "items": items,
            }
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"获取 YouTube 视频记录失败: {str(e)}",
            "data": None
        }), 500


@app.route('/youtube/videos/import', methods=['POST'])
def import_youtube_video():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "YouTube 链接不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "链接必须是 http 或 https 地址", None, 400)
        if not _extract_youtube_video_id(url):
            return _json_response(400, "请输入有效的 YouTube 视频链接", None, 400)

        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        video = _import_youtube_video_by_url(url)
        save_result = save_new_youtube_videos([video], "manual-url")
        return _json_response(data={
            "query": url,
            "source": "manual-url",
            "searchedAt": started_at,
            "total": save_result["created"],
            "created": save_result["created"],
            "duplicate": save_result["duplicate"],
            "publishedDuplicate": save_result.get("publishedDuplicate", 0),
            "requested": save_result["requested"],
            "items": save_result["items"],
        })
    except Exception as e:
        return _json_response(500, f"导入 YouTube 视频失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/status', methods=['PATCH'])
def youtube_video_status(video_id):
    return jsonify({
        "code": 405,
        "msg": "视频状态由后台任务自动更新，不能手动修改",
        "data": None
    }), 405


@app.route('/youtube/videos/<video_id>/reset-processing', methods=['POST'])
def reset_youtube_video_processing_route(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        result = reset_youtube_video_processing(
            video_id,
            delete_processed=bool(payload.get("deleteProcessed", True)),
            process_version=payload.get("processVersion") or "",
        )
        return _json_response(data=result)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"重置视频处理状态失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['GET'])
def youtube_video_analysis(video_id):
    try:
        return _json_response(data=get_youtube_video_analysis(video_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"获取剪辑方案失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['PATCH'])
def update_youtube_video_analysis(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_analysis_result(video_id, payload))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"更新发布文案失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/publish-draft', methods=['PATCH'])
def update_youtube_publish_draft(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_publish_draft(video_id, payload))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"更新发布稿失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>', methods=['DELETE'])
def delete_youtube_video(video_id):
    try:
        return _json_response(data=delete_youtube_video_record(video_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except ValueError as e:
        return _json_response(409, str(e), None, 409)
    except Exception as e:
        return _json_response(500, f"删除视频线索失败: {str(e)}", None, 500)


@app.route('/youtube/videos/batch-delete-items', methods=['POST'])
@app.route('/youtube/videos:batch-delete', methods=['POST'])
def batch_delete_youtube_videos():
    try:
        payload = request.get_json(silent=True) or {}
        video_ids = [
            str(item or "").strip()
            for item in (payload.get("videoIds") or payload.get("ids") or [])
            if str(item or "").strip()
        ]
        if not video_ids:
            return _json_response(400, "请选择要删除的视频线索", None, 400)
        return _json_response(data=delete_youtube_video_records(video_ids))
    except Exception as e:
        return _json_response(500, f"批量删除视频线索失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs', methods=['GET'])
def youtube_workflow_jobs():
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 100))
        items = list_youtube_workflow_jobs(limit)
        return _json_response(data={"total": len(items), "items": items})
    except Exception as e:
        return _json_response(500, f"获取工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>', methods=['GET'])
def youtube_workflow_job_detail(job_id):
    try:
        return _json_response(data=get_youtube_workflow_job(job_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"获取工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/statistics', methods=['GET'])
def youtube_workflow_statistics():
    try:
        limit = int(request.args.get("limit", 200))
        limit = max(20, min(limit, 1000))
        return _json_response(data=get_workflow_statistics(limit))
    except Exception as e:
        return _json_response(500, f"获取工作流统计失败: {str(e)}", None, 500)


@app.route('/youtube/sync/verify-files', methods=['POST'])
def youtube_verify_files():
    try:
        return _json_response(data=verify_youtube_file_consistency())
    except Exception as e:
        return _json_response(500, f"校验视频文件一致性失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs', methods=['POST'])
def create_youtube_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job(payload)
        thread = threading.Thread(target=run_youtube_workflow, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/download/jobs', methods=['POST'])
def create_youtube_download():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "account": "",
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
        })
        thread = threading.Thread(target=run_youtube_download_job, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建下载任务失败: {str(e)}", None, 500)


@app.route('/youtube/translate/jobs', methods=['POST'])
def create_youtube_translate():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "account": "",
            "publishToDouyin": False,
            "publishToBilibili": False,
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
        })
        thread = threading.Thread(target=run_youtube_translate_job, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建处理任务失败: {str(e)}", None, 500)


@app.route('/youtube/analysis/jobs', methods=['POST'])
def create_youtube_analysis():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        existing = get_youtube_video_analysis(payload.get("videoId") or "")
        if int(existing.get("status") or 0) == 1:
            return _json_response(409, "该视频已生成发布文案，可直接查看。", existing, 409)

        force = int(existing.get("status") or 0) == 3
        job = maybe_start_youtube_analysis_job({
            **payload,
            "processVersion": PROCESS_VERSION_EDITING,
        }, force=force)
        if not job:
            return _json_response(409, "该视频已有文案生成任务正在执行。", existing, 409)
        return _json_response(data=job, status=202)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"创建剪辑方案任务失败: {str(e)}", None, 500)


@app.route('/youtube/analysis/jobs', methods=['GET'])
def youtube_analysis_jobs():
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 100))
        items = [
            item for item in list_youtube_workflow_jobs(limit)
            if item.get("processVersion") == PROCESS_VERSION_EDITING
        ]
        return _json_response(data={"total": len(items), "items": items})
    except Exception as e:
        return _json_response(500, f"获取剪辑方案任务失败: {str(e)}", None, 500)


@app.route("/getAccounts", methods=['GET'])
def getAccounts():
    """快速获取所有账号信息，不进行cookie验证"""
    try:
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM user_info''')
            rows = cursor.fetchall()
            rows_list = [list(row) for row in rows]

            print("\n📋 当前数据表内容（快速获取）：")
            for row in rows:
                print(row)

            return jsonify(
                {
                    "code": 200,
                    "msg": None,
                    "data": rows_list
                }), 200
    except Exception as e:
        print(f"获取账号列表时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"获取账号列表失败: {str(e)}",
            "data": None
        }), 500


@app.route("/getValidAccounts",methods=['GET'])
async def getValidAccounts():
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM user_info''')
        rows = cursor.fetchall()
        rows_list = [list(row) for row in rows]
        print("\n📋 当前数据表内容：")
        for row in rows:
            print(row)
        for row in rows_list:
            flag = await check_cookie(row[1],row[2])
            if not flag:
                row[4] = 0
                cursor.execute('''
                UPDATE user_info 
                SET status = ? 
                WHERE id = ?
                ''', (0,row[0]))
                conn.commit()
                print("✅ 用户状态已更新")
        for row in rows:
            print(row)
        return jsonify(
                        {
                            "code": 200,
                            "msg": None,
                            "data": rows_list
                        }),200

@app.route('/deleteFile', methods=['GET'])
def delete_file():
    file_id = request.args.get('id')

    if not file_id or not file_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing file ID",
            "data": None
        }), 400

    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            data = delete_material_record(cursor, int(file_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "File deleted successfully",
            "data": data
        }), 200

    except LookupError as e:
        return jsonify({
            "code": 404,
            "msg": str(e),
            "data": None
        }), 404

    except WorkflowConflictError as e:
        return jsonify({
            "code": 409,
            "msg": str(e),
            "data": {
                "errorCode": e.error_code,
                "errorType": e.error_type,
                **e.data,
            }
        }), 409

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("delete failed!"),
            "data": None
        }), 500


@app.route('/deleteFiles', methods=['POST'])
def batch_delete_files():
    try:
        payload = request.get_json(silent=True) or {}
        file_ids = [
            int(item)
            for item in (payload.get("ids") or payload.get("fileIds") or [])
            if str(item).isdigit()
        ]
        if not file_ids:
            return jsonify({"code": 400, "msg": "请选择要删除的素材", "data": None}), 400
        return jsonify({
            "code": 200,
            "msg": "Files deleted",
            "data": delete_material_records(file_ids)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"batch delete failed: {str(e)}", "data": None}), 500


@app.route('/published-materials', methods=['GET'])
def published_materials():
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_published_youtube_materials(limit)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取已发布素材失败: {str(e)}", "data": None}), 500


@app.route('/deleteAccount', methods=['GET'])
def delete_account():
    account_id = request.args.get('id')

    if not account_id or not account_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing account ID",
            "data": None
        }), 400

    account_id = int(account_id)

    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询要删除的记录
            cursor.execute("SELECT * FROM user_info WHERE id = ?", (account_id,))
            record = cursor.fetchone()

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "account not found",
                    "data": None
                }), 404

            record = dict(record)

            # 删除关联的cookie文件
            if record.get('filePath'):
                cookie_file_path = Path(BASE_DIR / "cookiesFile" / record['filePath'])
                if cookie_file_path.exists():
                    try:
                        cookie_file_path.unlink()
                        print(f"✅ Cookie文件已删除: {cookie_file_path}")
                    except Exception as e:
                        print(f"⚠️ 删除Cookie文件失败: {e}")

            # 删除数据库记录
            cursor.execute("DELETE FROM user_info WHERE id = ?", (account_id,))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account deleted successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"delete failed: {str(e)}",
            "data": None
        }), 500


@app.route('/account', methods=['POST'])
def create_account():
    try:
        data = request.get_json(silent=True) or {}
        platform_type = int(data.get("type") or 0)
        user_name = (data.get("userName") or data.get("name") or "").strip()
        file_path = (data.get("filePath") or "").strip()
        status = int(data.get("status") if data.get("status") is not None else 0)
        if platform_type not in {1, 2, 3, 4, 5}:
            return jsonify({"code": 400, "msg": "不支持的平台类型", "data": None}), 400
        if not user_name:
            return jsonify({"code": 400, "msg": "账号名称不能为空", "data": None}), 400
        if not file_path:
            file_prefix_map = {
                1: "xiaohongshu",
                2: "tencent",
                3: "douyin",
                4: "kuaishou",
                5: "bilibili",
            }
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", user_name).strip("_") or uuid.uuid4().hex
            file_path = f"{file_prefix_map[platform_type]}_{safe_name}.json"

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
            ''', (platform_type, file_path, user_name, status))
            conn.commit()
            account_id = cursor.lastrowid

        return jsonify({
            "code": 200,
            "msg": "account created successfully",
            "data": [account_id, platform_type, file_path, user_name, status]
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"account create failed: {str(e)}",
            "data": None
        }), 500


def _safe_account_name(value):
    return re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("_") or uuid.uuid4().hex


def _bilibili_account_file(user_name):
    return Path(BASE_DIR / "cookiesFile" / f"bilibili_{_safe_account_name(user_name)}.json")


def _image_file_to_data_url(path):
    image_path = Path(path)
    suffix = image_path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"


def _emit_sse_error(status_queue, message):
    if message:
        status_queue.put(f"ERROR::{str(message).strip()}")
    status_queue.put("500")


def _strip_ansi(value):
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>]", "", str(value or ""))


def _terminal_qrcode_to_data_url(output):
    lines = []
    for raw_line in _strip_ansi(output).splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        qr_chars = sum(1 for char in line if char in {"█", "▀", "▄", " "})
        if qr_chars >= 20 and qr_chars >= len(line) * 0.75:
            lines.append(line)

    if len(lines) < 8:
        return ""

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    cell = 6
    margin = 18
    width = max(len(line) for line in lines) * cell
    height = len(lines) * cell * 2
    image = Image.new("RGB", (width + margin * 2, height + margin * 2), "white")
    draw = ImageDraw.Draw(image)

    for row, line in enumerate(lines):
        for col, char in enumerate(line.ljust(width // cell)):
            x = margin + col * cell
            y = margin + row * cell * 2
            if char == "█":
                draw.rectangle([x, y, x + cell - 1, y + cell * 2 - 1], fill="black")
            elif char == "▀":
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill="black")
            elif char == "▄":
                draw.rectangle([x, y + cell, x + cell - 1, y + cell * 2 - 1], fill="black")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _save_bilibili_login_account(user_name, account_file, status_queue, account_id=None):
    relative_cookie_file = Path(account_file).name
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        if account_id is not None:
            cursor.execute("SELECT type FROM user_info WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if row is None or int(row[0]) != 5:
                status_queue.put("500")
                return False
            cursor.execute(
                '''
                UPDATE user_info
                SET type = ?, filePath = ?, userName = ?, status = ?
                WHERE id = ?
                ''',
                (5, relative_cookie_file, user_name, 1, account_id),
            )
        else:
            cursor.execute(
                '''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
                ''',
                (5, relative_cookie_file, user_name, 1),
            )
        conn.commit()
    return True


def bilibili_cookie_gen(user_name, status_queue, account_id=None):
    if ensure_biliup_binary is None:
        _emit_sse_error(status_queue, "后端未加载 B 站 biliup 运行时，请检查依赖。")
        return

    account_file = _bilibili_account_file(user_name)
    account_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        biliup_binary = ensure_biliup_binary(force_check=False)
    except Exception as exc:
        print(f"B站登录准备 biliup 失败: {exc}")
        _emit_sse_error(status_queue, f"B站登录准备 biliup 失败: {exc}")
        return

    try:
        from winpty import PtyProcess
    except ImportError:
        _emit_sse_error(status_queue, "B站扫码登录需要 pywinpty 支持，请先执行: python -m pip install pywinpty")
        return

    command = [str(biliup_binary), "-u", str(account_file), "login"]
    sent_qrcode = False
    started_at = time.time()
    output_buffer = ""
    process = None
    try:
        process = PtyProcess.spawn(command, cwd=str(BASE_DIR), dimensions=(42, 160))
        selected_scan_login = False
        while True:
            try:
                chunk = process.read(4096)
            except Exception:
                chunk = ""

            if chunk:
                output_buffer = (output_buffer + chunk)[-30000:]
                plain_output = _strip_ansi(output_buffer)
                if not selected_scan_login and "选择一种登录方式" in plain_output and "扫码登录" in plain_output:
                    process.write("\x1b[B\r")
                    selected_scan_login = True
                    time.sleep(0.5)

                if not sent_qrcode:
                    qrcode_data_url = _terminal_qrcode_to_data_url(output_buffer)
                    if qrcode_data_url:
                        status_queue.put(qrcode_data_url)
                        sent_qrcode = True

            if not process.isalive():
                break

            if time.time() - started_at > 180:
                process.terminate(force=True)
                _emit_sse_error(status_queue, "等待 B 站扫码确认超时，请重新获取二维码。")
                return

            time.sleep(0.2)

        exit_status = process.exitstatus
        if exit_status == 0 and account_file.is_file():
            if _save_bilibili_login_account(user_name, account_file, status_queue, account_id):
                status_queue.put("200")
            else:
                _emit_sse_error(status_queue, "B站登录成功但保存账号失败，请检查账号记录。")
        else:
            plain_output = _strip_ansi(output_buffer)
            tail = "\n".join([line.strip() for line in plain_output.splitlines() if line.strip()][-8:])
            _emit_sse_error(status_queue, tail or f"B站登录失败，biliup 退出码: {exit_status}")
    except Exception as exc:
        print(f"B站登录流程异常: {exc}")
        _emit_sse_error(status_queue, f"B站登录流程异常: {exc}")
    finally:
        if process is not None:
            try:
                if process.isalive():
                    process.terminate(force=True)
            except Exception:
                pass


# SSE 登录接口
@app.route('/login')
def login():
    # 1 小红书 2 视频号 3 抖音 4 快手 5 B站
    type = request.args.get('type')
    # 账号名
    id = (request.args.get('id') or '').strip()
    account_id = request.args.get('accountId')
    account_id = int(account_id) if account_id and account_id.isdigit() else None

    if type not in {'1', '2', '3', '4', '5'} or not id:
        return Response("data: 500\n\n", mimetype='text/event-stream')

    if account_id is not None:
        try:
            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT type FROM user_info WHERE id = ?", (account_id,))
                row = cursor.fetchone()
                if row is None or str(row[0]) != str(type):
                    return Response("data: 500\n\n", mimetype='text/event-stream')
        except Exception as e:
            print(f"校验重新连接账号失败: {e}")
            return Response("data: 500\n\n", mimetype='text/event-stream')

    # 模拟一个用于异步通信的队列
    status_queue = Queue()
    queue_key = f"{type}:{account_id or id}"
    active_queues[queue_key] = status_queue
    # 启动异步任务线程
    thread = threading.Thread(target=run_async_function, args=(type,id,status_queue,account_id), daemon=True)
    thread.start()
    response = Response(sse_stream(status_queue, queue_key), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # 关键：禁用 Nginx 缓冲
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Connection'] = 'keep-alive'
    return response

@app.route('/postVideo', methods=['POST'])
def postVideo():
    # 获取JSON数据
    data = request.get_json()

    if not data:
        return jsonify({"code": 400, "msg": "请求数据不能为空", "data": None}), 400

    # 从JSON数据中提取fileList和accountList
    file_list = data.get('fileList', [])
    account_list = _clean_unique_list(data.get('accountList', []))
    type = data.get('type')
    title = data.get('title')
    description = data.get('description') or ''
    tags = data.get('tags')
    category = data.get('category')
    enableTimer = data.get('enableTimer')
    if category == 0:
        category = None
    productLink = data.get('productLink', '')
    productTitle = data.get('productTitle', '')
    thumbnail_path = data.get('thumbnail', '')
    is_draft = data.get('isDraft', False)  # 新增参数：是否保存为草稿

    videos_per_day = data.get('videosPerDay')
    daily_times = data.get('dailyTimes')
    start_days = data.get('startDays')

    # 参数校验
    if not file_list:
        return jsonify({"code": 400, "msg": "文件列表不能为空", "data": None}), 400
    if not account_list:
        return jsonify({"code": 400, "msg": "账号列表不能为空", "data": None}), 400
    if not type:
        return jsonify({"code": 400, "msg": "平台类型不能为空", "data": None}), 400
    if not title:
        return jsonify({"code": 400, "msg": "标题不能为空", "data": None}), 400

    try:
        file_list = _validate_publish_processed_files(file_list)
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400

    # 打印获取到的数据（仅作为示例）
    print("File List:", file_list)
    print("Account List:", account_list)

    try:
        match type:
            case 1:
                post_video_xhs(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                   start_days)
            case 2:
                post_video_tencent(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                   start_days, is_draft)
            case 3:
                post_video_DouYin(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days, thumbnail_path, productLink, productTitle)
            case 4:
                post_video_ks(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days)
            case 5:
                _publish_center_to_bilibili(
                    title,
                    description,
                    file_list,
                    tags or [],
                    account_list,
                    tid=category or 249,
                    enable_timer=enableTimer,
                    videos_per_day=videos_per_day,
                    daily_times=daily_times,
                    start_days=start_days,
                )
            case _:
                return jsonify({"code": 400, "msg": f"不支持的平台类型: {type}", "data": None}), 400

        published_video_ids = _mark_published_materials(
            file_list,
            platform_type=type,
            title=f"{title}; description={description}" if description else title,
            account_count=len(account_list),
        )

        # 返回响应给客户端
        return jsonify(
            {
                "code": 200,
                "msg": "发布任务已提交",
                "data": {
                    "publishedVideoIds": published_video_ids,
                }
            }), 200
    except Exception as e:
        print(f"发布视频时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"发布失败: {str(e)}",
            "data": None
        }), 500


@app.route('/updateUserinfo', methods=['POST'])
def updateUserinfo():
    # 获取JSON数据
    data = request.get_json()

    # 从JSON数据中提取 type 和 userName
    user_id = data.get('id')
    type = data.get('type')
    userName = data.get('userName')
    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 更新数据库记录
            cursor.execute('''
                           UPDATE user_info
                           SET type     = ?,
                               userName = ?
                           WHERE id = ?;
                           ''', (type, userName, user_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account update successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("update failed!"),
            "data": None
        }), 500

@app.route('/postVideoBatch', methods=['POST'])
def postVideoBatch():
    data_list = request.get_json()

    if not isinstance(data_list, list):
        return jsonify({"code": 400, "msg": "Expected a JSON array", "data": None}), 400
    for data in data_list:
        # 从JSON数据中提取fileList和accountList
        file_list = data.get('fileList', [])
        account_list = _clean_unique_list(data.get('accountList', []))
        type = data.get('type')
        title = data.get('title')
        tags = data.get('tags')
        category = data.get('category')
        enableTimer = data.get('enableTimer')
        if category == 0:
            category = None
        productLink = data.get('productLink', '')
        productTitle = data.get('productTitle', '')
        is_draft = data.get('isDraft', False)

        videos_per_day = data.get('videosPerDay')
        daily_times = data.get('dailyTimes')
        start_days = data.get('startDays')
        # 打印获取到的数据（仅作为示例）
        print("File List:", file_list)
        print("Account List:", account_list)
        match type:
            case 1:
                post_video_xhs(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                               start_days)
            case 2:
                post_video_tencent(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                   start_days, is_draft)
            case 3:
                post_video_DouYin(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days, productLink, productTitle)
            case 4:
                post_video_ks(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days)
    # 返回响应给客户端
    return jsonify(
        {
            "code": 200,
            "msg": None,
            "data": None
        }), 200

# Cookie文件上传API
@app.route('/uploadCookie', methods=['POST'])
def upload_cookie():
    try:
        if 'file' not in request.files:
            return jsonify({
                "code": 400,
                "msg": "没有找到Cookie文件",
                "data": None
            }), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({
                "code": 400,
                "msg": "Cookie文件名不能为空",
                "data": None
            }), 400

        if not file.filename.endswith('.json'):
            return jsonify({
                "code": 400,
                "msg": "Cookie文件必须是JSON格式",
                "data": None
            }), 400

        # 获取账号信息
        account_id = request.form.get('id')
        platform = request.form.get('platform')

        if not account_id or not account_id.isdigit() or not platform:
            return jsonify({
                "code": 400,
                "msg": "缺少账号ID或平台信息",
                "data": None
            }), 400

        platform_type_map = {
            '小红书': 1,
            '视频号': 2,
            '抖音': 3,
            '快手': 4,
            'B站': 5,
            '哔哩哔哩': 5,
            'Bilibili': 5,
        }
        platform_type = platform_type_map.get(platform)
        if not platform_type:
            return jsonify({
                "code": 400,
                "msg": "不支持的平台类型",
                "data": None
            }), 400

        # 从数据库获取账号的文件路径
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT type, filePath FROM user_info WHERE id = ?', (account_id,))
            result = cursor.fetchone()

            if not result:
                return jsonify({
                    "code": 404,
                    "msg": "账号不存在",
                    "data": None
                }), 404

            if int(result['type']) != platform_type:
                return jsonify({
                    "code": 400,
                    "msg": "上传平台与账号平台不匹配",
                    "data": None
                }), 400

            # 保存上传的Cookie文件到对应路径
            cookie_file_path = Path(BASE_DIR / "cookiesFile" / result['filePath'])
            cookie_file_path.parent.mkdir(parents=True, exist_ok=True)

            file.save(str(cookie_file_path))

            cursor.execute('UPDATE user_info SET status = ? WHERE id = ?', (1, account_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "Cookie文件上传成功",
            "data": None
        }), 200

    except Exception as e:
        print(f"上传Cookie文件时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"上传Cookie文件失败: {str(e)}",
            "data": None
        }), 500


# Cookie文件下载API
@app.route('/downloadCookie', methods=['GET'])
def download_cookie():
    try:
        file_path = request.args.get('filePath')
        if not file_path:
            return jsonify({
                "code": 500,
                "msg": "缺少文件路径参数",
                "data": None
            }), 400

        # 验证文件路径的安全性，防止路径遍历攻击
        cookie_file_path = Path(BASE_DIR / "cookiesFile" / file_path).resolve()
        base_path = Path(BASE_DIR / "cookiesFile").resolve()

        if not cookie_file_path.is_relative_to(base_path):
            return jsonify({
                "code": 500,
                "msg": "非法文件路径",
                "data": None
            }), 400

        if not cookie_file_path.exists():
            return jsonify({
                "code": 500,
                "msg": "Cookie文件不存在",
                "data": None
            }), 404

        # 返回文件
        return send_from_directory(
            directory=str(cookie_file_path.parent),
            path=cookie_file_path.name,
            as_attachment=True
        )

    except Exception as e:
        print(f"下载Cookie文件时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"下载Cookie文件失败: {str(e)}",
            "data": None
        }), 500


# 包装函数：在线程中运行异步函数
def run_async_function(type,id,status_queue,account_id=None):
    if type == '5':
        bilibili_cookie_gen(id, status_queue, account_id)
        return

    if not all([xiaohongshu_cookie_gen, get_tencent_cookie, douyin_cookie_gen, get_ks_cookie]):
        status_queue.put("500")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        match type:
            case '1':
                loop.run_until_complete(xiaohongshu_cookie_gen(id, status_queue, account_id))
            case '2':
                loop.run_until_complete(get_tencent_cookie(id,status_queue, account_id))
            case '3':
                loop.run_until_complete(douyin_cookie_gen(id,status_queue, account_id))
            case '4':
                loop.run_until_complete(get_ks_cookie(id,status_queue, account_id))
            case _:
                status_queue.put("500")
    except Exception as e:
        print(f"登录流程异常: {e}")
        status_queue.put("500")
    finally:
        loop.close()

# SSE 流生成器函数
def sse_stream(status_queue, queue_key=None):
    try:
        while True:
            if not status_queue.empty():
                msg = status_queue.get()
                yield f"data: {msg}\n\n"
                if msg in {"200", "500"}:
                    break
            else:
                # 避免 CPU 占满
                time.sleep(0.1)
    finally:
        if queue_key:
            print(f"清理队列: {queue_key}")
            active_queues.pop(queue_key, None)


_shutdown_marked = False
_previous_signal_handlers = {}


def _mark_shutdown_once():
    global _shutdown_marked
    if _shutdown_marked:
        return
    _shutdown_marked = True
    try:
        interrupted = mark_shutdown_interrupted_jobs()
        if interrupted:
            print(f"已标记 {len(interrupted)} 个后端关闭中断任务")
    except Exception as exc:
        print(f"标记后端关闭中断任务失败: {exc}")


def _handle_shutdown_signal(signum, frame):
    _mark_shutdown_once()
    previous = _previous_signal_handlers.get(signum)
    if callable(previous):
        previous(signum, frame)
        return
    raise SystemExit(0)


def install_workflow_shutdown_handlers():
    atexit.register(_mark_shutdown_once)
    for signal_name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        try:
            _previous_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_shutdown_signal)
        except Exception as exc:
            print(f"注册 {signal_name} 关闭处理失败: {exc}")


if __name__ == '__main__':
    init_youtube_video_table()
    recovered_jobs = recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    normalize_existing_youtube_subscribers()
    install_workflow_shutdown_handlers()
    app.run(host='0.0.0.0' ,port=5409)
