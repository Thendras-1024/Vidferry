import asyncio
import datetime
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import wave
import urllib.parse
import urllib.request
from pathlib import Path
from queue import Queue
from flask_cors import CORS
from flask import Flask, request, jsonify, Response, render_template, send_from_directory
from conf import BASE_DIR


def _load_local_env():
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

try:
    from myUtils.auth import check_cookie
    from myUtils.login import get_tencent_cookie, douyin_cookie_gen, get_ks_cookie, xiaohongshu_cookie_gen
    from myUtils.postVideo import post_video_tencent, post_video_DouYin, post_video_ks, post_video_xhs
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

active_queues = {}
app = Flask(__name__)

#允许所有来源跨域访问
CORS(app)

# 限制上传文件大小为160MB
app.config['MAX_CONTENT_LENGTH'] = 160 * 1024 * 1024


@app.before_request
def ensure_database_tables():
    init_youtube_workflow_table()

YOUTUBE_DEFAULT_QUERY = "foreigner China travel vlog first time in China"
YOUTUBE_FALLBACK_QUERIES = [
    "foreigner China travel vlog",
    "first time in China travel vlog foreigner",
    "American in China travel vlog",
    "British in China travel vlog",
]


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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_videos)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "translate_status" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_videos ADD COLUMN translate_status INTEGER DEFAULT 0")
        if "processed_file_path" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_videos ADD COLUMN processed_file_path TEXT")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_download_status ON youtube_videos(download_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_publish_status ON youtube_videos(publish_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_translate_status ON youtube_videos(translate_status)')
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_id ON youtube_workflow_jobs(video_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status ON youtube_workflow_jobs(status)')
        conn.commit()


def _row_to_youtube_video(row):
    item = dict(row)
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
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def upsert_youtube_videos(videos, query):
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for video in videos:
            video_id = video.get("id")
            url = video.get("url")
            if not video_id or not url:
                continue
            cursor.execute('''
            INSERT INTO youtube_videos (
                video_id, title, channel, subscribers, published_at, url, thumbnail, duration, query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title = excluded.title,
                channel = excluded.channel,
                subscribers = excluded.subscribers,
                published_at = excluded.published_at,
                url = excluded.url,
                thumbnail = excluded.thumbnail,
                duration = excluded.duration,
                query = excluded.query,
                updated_at = CURRENT_TIMESTAMP
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

        ids = [video.get("id") for video in videos if video.get("id")]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f'''
        SELECT * FROM youtube_videos
        WHERE video_id IN ({placeholders})
        ORDER BY CASE video_id {' '.join(f'WHEN ? THEN {index}' for index, _ in enumerate(ids))} END
        ''', ids + ids)
        return [_row_to_youtube_video(row) for row in cursor.fetchall()]


def list_youtube_videos():
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM youtube_videos
        ORDER BY updated_at DESC, id DESC
        ''')
        return [_row_to_youtube_video(row) for row in cursor.fetchall()]


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
        cursor = conn.cursor()
        cursor.execute("DELETE FROM youtube_videos WHERE video_id = ?", (video_id,))
        deleted = cursor.rowcount
        conn.commit()
    if not deleted:
        raise LookupError("视频线索不存在")
    return {"videoId": video_id}


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
        "createdAt": item.get("created_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def create_youtube_workflow_job(payload):
    init_youtube_workflow_table()
    job_id = str(uuid.uuid4())
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO youtube_workflow_jobs (
            id, video_id, url, account, channel, subscribers, published_at,
            bilibili_account, bilibili_tid, publish_to_douyin, publish_to_bilibili,
            title, description, tags, schedule, status, step, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        raise RuntimeError("Whisper 未识别到可用字幕文本。")
    return result, getattr(info, "language", "")


def _translate_segments_to_chinese(segments):
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise RuntimeError("未安装 deep-translator，请先安装依赖后再执行中文翻译。") from exc

    translator = GoogleTranslator(source="auto", target="zh-CN")
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
            translated[index]["zh"] = line or translated[index]["text"]
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
        "翻译: AI 中文字幕",
    ]


def _build_ass_file(job, segments, ass_file, audio_duration):
    ass_file = Path(ass_file)
    overlay_text = "\\N".join(_escape_ass_text(line) for line in _author_overlay_lines(job))
    dialogue_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Subtitle,Microsoft YaHei,54,&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,4,1,2,64,64,92,1",
        "Style: Info,Microsoft YaHei,42,&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,4,1,7,36,36,36,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{_format_ass_timestamp(0)},{_format_ass_timestamp(min(20, audio_duration or 20))},Info,,0,0,0,,{overlay_text}",
    ]
    for segment in segments:
        start = _format_ass_timestamp(segment["start"])
        end = _format_ass_timestamp(max(segment["end"], segment["start"] + 0.5))
        text = _escape_ass_text(segment.get("zh") or segment.get("text") or "")
        dialogue_lines.append(f"Dialogue: 0,{start},{end},Subtitle,,0,0,0,,{text}")
    ass_file.write_text("\n".join(dialogue_lines), encoding="utf-8")
    return ass_file


def _ffmpeg_subtitle_path(path):
    value = Path(path).resolve().as_posix()
    return value.replace(":", "\\:").replace("'", "\\'")


def _burn_subtitles_to_mp4(source_file, ass_file, output_file):
    ffmpeg = _resolve_ffmpeg_command()
    subtitle_filter = f"subtitles='{_ffmpeg_subtitle_path(ass_file)}'"
    _run_command([
        ffmpeg,
        "-y",
        "-i", str(source_file),
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_file),
    ], cwd=BASE_DIR)
    if not Path(output_file).exists():
        raise RuntimeError(f"FFmpeg 已执行，但未生成最终 MP4: {output_file}")
    return Path(output_file)


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


def _process_subtitles(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    output_file = processed_dir / f"{Path(source_file).stem}_zh.mp4"

    if SUBTITLE_COMMAND_TEMPLATE:
        command = _render_command_template(
            SUBTITLE_COMMAND_TEMPLATE,
            input=str(source_file),
            output=str(output_file),
            video_id=job["videoId"] or job["id"],
        )
        _run_command(command, cwd=BASE_DIR)
        if not output_file.exists():
            raise RuntimeError(f"字幕处理命令已执行，但未生成文件: {output_file}")
        return output_file

    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_work")
    audio_file = _extract_audio_for_whisper(source_file, work_dir)
    segments, language = _transcribe_audio(audio_file)
    translated_segments = _translate_segments_to_chinese(segments)
    duration = _get_media_duration_seconds(audio_file)
    ass_file = _build_ass_file(job, translated_segments, work_dir / f"{Path(source_file).stem}.ass", duration)
    return _burn_subtitles_to_mp4(source_file, ass_file, output_file)


def _material_file_path(record):
    raw_path = record.get("storage_key") or record.get("file_path") or ""
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return Path(BASE_DIR / "videoFile" / raw_path)


def _row_to_material(row):
    item = dict(row)
    metadata = item.get("metadata") or "{}"
    try:
        metadata = json.loads(metadata)
    except (TypeError, ValueError):
        metadata = {}
    if not item.get("asset_id"):
        item["asset_id"] = ""
    item["uuid"] = item.get("asset_id") or ""
    item["storage_key"] = item.get("storage_key") or item.get("file_path") or ""
    item["storage_backend"] = item.get("storage_backend") or "local"
    item["source_type"] = item.get("source_type") or "manual_upload"
    item["source_video_id"] = item.get("source_video_id") or ""
    item["status"] = item.get("status") or "ready"
    item["metadata"] = metadata
    return item


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
            storage_backend, source_type, source_video_id, status, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            json.dumps(metadata_payload, ensure_ascii=False),
        ))
        conn.commit()
        cursor.execute("SELECT * FROM file_records WHERE id = ?", (cursor.lastrowid,))
        return _row_to_material(cursor.fetchone())


def _youtube_material_metadata(job, stage):
    return {
        "stage": stage,
        "videoId": job.get("videoId") or "",
        "url": job.get("url") or "",
        "title": job.get("title") or "",
        "channel": job.get("channel") or "",
        "subscribers": job.get("subscribers") or "",
        "publishedAt": job.get("publishedAt") or "",
    }


def _save_processed_video_to_material(file_path, job=None):
    job = job or {}
    return register_material(
        file_path,
        source_type="youtube_processed",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "processed"),
        copy_to_library=True,
    )


def _register_downloaded_video_material(file_path, job=None):
    job = job or {}
    return register_material(
        file_path,
        source_type="youtube_download",
        source_video_id=job.get("videoId") or "",
        metadata=_youtube_material_metadata(job, "downloaded"),
        copy_to_library=False,
    )


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
        source_file = _download_youtube_video(job)
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
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def run_youtube_translate_job(job_id):
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle",
            message="正在基于已下载视频处理中文字幕",
            progress=0,
            speed="",
            eta="",
        )
        source_file = _resolve_downloaded_source_file(job)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在转写和翻译字幕",
        )
        processed_file = _process_subtitles(job, source_file)
        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=1,
            processed_file_path=str(processed_file),
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="中文字幕视频已生成并保存到素材库",
            processed_file_path=str(processed_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
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


def run_youtube_workflow(job_id):
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
        )
        source_file = _download_youtube_video(job)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message="视频已下载，正在处理中文字幕",
        )
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )

        processed_file = _process_subtitles(job, source_file)
        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_workflow_job(
            job_id,
            processed_file_path=str(processed_file),
            step="publish",
            message="中文字幕视频已生成并保存到素材库，准备发布",
        )
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=1,
            processed_file_path=str(processed_file),
        )

        latest_job = get_youtube_workflow_job(job_id)
        publish_commands = []
        douyin_command = _publish_to_douyin(latest_job, processed_file)
        if douyin_command:
            publish_commands.append(douyin_command)
        bilibili_command = _publish_to_bilibili(latest_job, processed_file)
        if bilibili_command:
            publish_commands.append(bilibili_command)
        final_message = "任务完成"
        if not publish_commands:
            final_message = "任务完成，已保存到素材库，未配置抖音账号所以未发布"
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            publish_command="\n".join(publish_commands),
        )
        if publish_commands:
            update_youtube_video_artifacts(job["videoId"], publish_status=1)
    except Exception as exc:
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

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO file_records (
                asset_id, filename, original_filename, filesize, file_path, storage_key,
                storage_backend, source_type, status, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            data = [_row_to_material(row) for row in rows]

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
        saved_videos = upsert_youtube_videos(videos, query)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "query": query,
                "source": source,
                "searchedAt": started_at,
                "total": len(saved_videos),
                "items": saved_videos,
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


@app.route('/youtube/videos/<video_id>/status', methods=['PATCH'])
def youtube_video_status(video_id):
    return jsonify({
        "code": 405,
        "msg": "视频状态由后台任务自动更新，不能手动修改",
        "data": None
    }), 405


@app.route('/youtube/videos/<video_id>', methods=['DELETE'])
def delete_youtube_video(video_id):
    try:
        return _json_response(data=delete_youtube_video_record(video_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"删除视频线索失败: {str(e)}", None, 500)


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
        return _json_response(500, f"创建翻译任务失败: {str(e)}", None, 500)


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

            # 查询要删除的记录
            cursor.execute("SELECT * FROM file_records WHERE id = ?", (file_id,))
            record = cursor.fetchone()

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "File not found",
                    "data": None
                }), 404

            record = dict(record)

            file_path = _material_file_path(record)
            if file_path and file_path.exists():
                try:
                    file_path.unlink()  # 删除文件
                    print(f"✅ 实际文件已删除: {file_path}")
                except Exception as e:
                    print(f"⚠️ 删除实际文件失败: {e}")
                    # 即使删除文件失败，也要继续删除数据库记录，避免数据不一致
            else:
                print(f"⚠️ 实际文件不存在: {file_path}")

            # 删除数据库记录
            cursor.execute("DELETE FROM file_records WHERE id = ?", (file_id,))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "File deleted successfully",
            "data": {
                "id": record['id'],
                "filename": record['filename']
            }
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("delete failed!"),
            "data": None
        }), 500

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


# SSE 登录接口
@app.route('/login')
def login():
    # 1 小红书 2 视频号 3 抖音 4 快手
    type = request.args.get('type')
    # 账号名
    id = (request.args.get('id') or '').strip()
    account_id = request.args.get('accountId')
    account_id = int(account_id) if account_id and account_id.isdigit() else None

    if type not in {'1', '2', '3', '4'} or not id:
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
    account_list = data.get('accountList', [])
    type = data.get('type')
    title = data.get('title')
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
            case _:
                return jsonify({"code": 400, "msg": f"不支持的平台类型: {type}", "data": None}), 400

        # 返回响应给客户端
        return jsonify(
            {
                "code": 200,
                "msg": "发布任务已提交",
                "data": None
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
        account_list = data.get('accountList', [])
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
            '快手': 4
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

if __name__ == '__main__':
    init_youtube_video_table()
    normalize_existing_youtube_subscribers()
    app.run(host='0.0.0.0' ,port=5409)
