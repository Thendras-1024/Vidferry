"""短视频检索、人工审核和拼接服务。"""

import base64 as _base64
import datetime as _datetime
import json as _json
import logging as _logging
import subprocess as _subprocess
import uuid as _uuid
from pathlib import Path as _Path

from flask import g as _g
from werkzeug.utils import secure_filename as _secure_filename

from app.config import BASE_DIR as _BASE_DIR, BURN_PROFILES as _BURN_PROFILES, DEFAULT_BURN_PROFILE as _DEFAULT_BURN_PROFILE, MULTIMODAL_LLM_API_KEY as _VISION_KEY, MULTIMODAL_LLM_BASE_URL as _VISION_URL, MULTIMODAL_LLM_MODEL as _VISION_MODEL, get_llm_config_status as _llm_status
from app.core.llm_harness import call_json_contract as _call_json_contract
from app.db.base import _db_connect
from app.db.schema import init_database_tables
from app.utils.ffmpeg_util import _resolve_ffmpeg_command, video_encode_args


_logger = _logging.getLogger(__name__)
_ROOT = _Path(_BASE_DIR) / "videos" / "short_video"
_BGM_ROOT = _ROOT / "bgm"
_PREVIEW_ROOT = _ROOT / "previews"
_OUTPUT_ROOT = _ROOT / "outputs"
_VALID_TRANSITIONS = {"cut", "fade", "slideleft", "zoomin"}


def _now():
    return _datetime.datetime.now().isoformat(timespec="seconds")


def _owner_id():
    user = getattr(_g, "current_user", None) or {}
    return int(user.get("id") or 0)


def _is_admin():
    return (getattr(_g, "current_user", None) or {}).get("role") == "admin"


def _ensure_tables():
    init_database_tables()


def _project(cursor, project_id, owner_id=None):
    cursor.execute("SELECT * FROM short_video_projects WHERE id = %s", (project_id,))
    row = cursor.fetchone()
    if not row or (owner_id is not None and int(row["owner_user_id"] or 0) != int(owner_id)):
        raise LookupError("短视频项目不存在或无权访问")
    return dict(row)


def _candidate_payload(row):
    item = dict(row)
    item.update({
        "selected": bool(item.get("selected")),
        "keyframes": _json.loads(item.get("keyframes") or "[]"),
        "durationSeconds": float(item.get("duration_seconds") or 0),
        "clipDurationSeconds": float(item.get("clip_duration_seconds") or 0),
        "licenseType": item.get("license_type") or "",
        "licenseBasis": item.get("license_basis") or "",
        "analysisStatus": item.get("analysis_status") or "pending",
        "analysisScore": int(item.get("analysis_score") or 0),
        "analysisReason": item.get("analysis_reason") or "",
    })
    return item


def _project_payload(cursor, row, include_candidates=True):
    item = dict(row)
    item.update({
        "targetCount": int(item.get("target_count") or 0),
        "targetDurationSeconds": int(item.get("target_duration_seconds") or 0),
        "transitionType": item.get("transition_type") or "cut",
        "bgmTrackId": item.get("bgm_track_id"),
        "keepOriginalAudio": bool(item.get("keep_original_audio")),
        "outputMaterialId": item.get("output_material_id"),
    })
    if include_candidates:
        cursor.execute("SELECT * FROM short_video_candidates WHERE project_id = %s ORDER BY ordinal, created_at", (item["id"],))
        item["candidates"] = [_candidate_payload(candidate) for candidate in cursor.fetchall()]
    return item


def list_short_video_projects():
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM short_video_projects WHERE owner_user_id = %s ORDER BY updated_at DESC", (_owner_id(),))
        return [_project_payload(cursor, row, include_candidates=False) for row in cursor.fetchall()]


def create_short_video_project(payload):
    _ensure_tables()
    topic = str((payload or {}).get("topic") or "").strip()[:160]
    if not topic:
        raise ValueError("主题不能为空")
    target_count = max(2, min(12, int((payload or {}).get("targetCount") or 10)))
    target_duration = max(15, min(90, int((payload or {}).get("targetDurationSeconds") or 45)))
    project_id, now = _uuid.uuid4().hex, _now()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO short_video_projects
            (id, owner_user_id, topic, target_count, target_duration_seconds, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)''', (project_id, _owner_id(), topic, target_count, target_duration, now, now))
        return _project_payload(cursor, _project(cursor, project_id, _owner_id()), include_candidates=True)


def get_short_video_project(project_id):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        return _project_payload(cursor, _project(cursor, project_id, _owner_id()))


def _whitelisted_channels(cursor):
    cursor.execute("SELECT channel FROM short_video_channel_whitelist")
    return {str(row[0] or "").strip().lower() for row in cursor.fetchall()}


def _video_is_vertical(info):
    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    return width > 0 and height > 0 and height / width >= 1.55


def _license_basis(info, whitelisted):
    license_name = str(info.get("license") or "").strip()
    channel = str(info.get("channel") or info.get("uploader") or "").strip().lower()
    if "creative commons" in license_name.lower():
        return license_name, "Creative Commons"
    if channel and channel in whitelisted:
        return license_name, "授权频道白名单"
    return license_name, ""


def _topic_matches_metadata(info, topic):
    normalized_topic = " ".join(str(topic or "").lower().split())
    if not normalized_topic:
        return False
    metadata = " ".join((str(info.get(field) or "") for field in ("title", "description", "channel", "uploader"))).lower()
    terms = [term for term in normalized_topic.replace("/", " ").replace("，", " ").split() if len(term) > 1]
    if len(terms) == 1 and len(normalized_topic) >= 4 and " " not in normalized_topic:
        terms = [normalized_topic[index:index + 2] for index in range(0, len(normalized_topic) - 1, 2)]
    return not terms or any(term in metadata for term in terms)


def _search_candidates(project_id, owner_id):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        project = _project(cursor, project_id, owner_id)
        whitelist = _whitelisted_channels(cursor)
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp") from exc
    wanted = min(50, max(int(project["target_count"]) * 5, 20))
    opts = {"quiet": True, "skip_download": True, "noplaylist": True, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(f"ytsearch{wanted}:{project['topic']}", download=False) or {}
    accepted = []
    seen_sources = set()
    for raw in result.get("entries") or []:
        if not raw:
            continue
        url = raw.get("webpage_url") or raw.get("url") or ""
        if not url.startswith("http"):
            video_id = raw.get("id") or ""
            url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        if not url:
            continue
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        license_name, basis = _license_basis(info, whitelist)
        duration = float(info.get("duration") or 0)
        source_video_id = str(info.get("id") or "")
        source_key = source_video_id or str(info.get("webpage_url") or url)
        if source_key in seen_sources or not basis or not _video_is_vertical(info) or not 0 < duration <= 180 or not _topic_matches_metadata(info, project["topic"]):
            continue
        seen_sources.add(source_key)
        accepted.append({
            "source_video_id": source_video_id, "source_url": info.get("webpage_url") or url,
            "title": str(info.get("title") or "")[:500], "channel": str(info.get("channel") or info.get("uploader") or "")[:300],
            "license_type": license_name[:200], "license_basis": basis, "duration_seconds": duration,
            "width": int(info.get("width") or 0), "height": int(info.get("height") or 0), "thumbnail": str(info.get("thumbnail") or ""),
        })
        if len(accepted) >= int(project["target_count"]):
            break
    now = _now()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        _project(cursor, project_id, owner_id)
        cursor.execute("DELETE FROM short_video_candidates WHERE project_id = %s", (project_id,))
        for ordinal, item in enumerate(accepted, start=1):
            cursor.execute('''INSERT INTO short_video_candidates
                (id, project_id, source_video_id, source_url, title, channel, license_type, license_basis,
                duration_seconds, width, height, thumbnail, ordinal, clip_duration_seconds, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (_uuid.uuid4().hex, project_id, item["source_video_id"], item["source_url"], item["title"], item["channel"],
                 item["license_type"], item["license_basis"], item["duration_seconds"], item["width"], item["height"], item["thumbnail"],
                 ordinal, min(8.0, item["duration_seconds"]), now, now))
        cursor.execute("UPDATE short_video_projects SET status = 'reviewing', message = %s, updated_at = %s WHERE id = %s", (f"已筛选 {len(accepted)} 条候选", now, project_id))
    _logger.info("Short video search completed : projectId = %s | accepted = %s", project_id, len(accepted))
    return {"projectId": project_id, "status": "reviewing"}


def run_short_video_search(project_id, owner_id):
    try:
        result = _search_candidates(project_id, owner_id)
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM short_video_candidates WHERE project_id = %s ORDER BY ordinal LIMIT 12", (project_id,))
            candidate_ids = [row["id"] for row in cursor.fetchall()]
        for candidate_id in candidate_ids:
            run_short_video_candidate_review(project_id, candidate_id, owner_id)
        _set_project_status(project_id, "reviewing", "自动初筛已完成，等待人工确认")
        return result
    except Exception as exc:
        _set_project_status(project_id, "failed", "检索失败，请查看服务端日志")
        _logger.exception("Short video search failed : projectId = %s", project_id)
        raise


def _set_project_status(project_id, status, message, **updates):
    fields, values = ["status = %s", "message = %s", "updated_at = %s"], [status, message[:500], _now()]
    for column, value in updates.items():
        fields.append(f"{column} = %s")
        values.append(value)
    values.append(project_id)
    with _db_connect() as conn:
        conn.execute(f"UPDATE short_video_projects SET {', '.join(fields)} WHERE id = %s", values)


def _download_candidate_preview(candidate):
    import yt_dlp
    target = _PREVIEW_ROOT / candidate["project_id"]
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"{candidate['id']}.%(ext)s"
    opts = {"quiet": True, "noplaylist": True, "format": "worst[height<=360]/worst", "outtmpl": str(output), "merge_output_format": "mp4"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(candidate["source_url"], download=True)
    files = sorted(target.glob(f"{candidate['id']}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("预览下载后未找到视频文件")
    return files[0]


def _preview_frames(preview_path):
    duration = max(1.0, _media_duration(preview_path))
    frame_dir = preview_path.parent / f"{preview_path.stem}_frames"
    frame_dir.mkdir(exist_ok=True)
    frames = []
    for index, ratio in enumerate((0.12, 0.32, 0.52, 0.72, 0.88), start=1):
        frame = frame_dir / f"{index}.jpg"
        _subprocess.run([_resolve_ffmpeg_command(), "-y", "-ss", f"{duration * ratio:.2f}", "-i", str(preview_path), "-frames:v", "1", "-vf", "scale=480:-2", str(frame)], check=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.PIPE)
        frames.append({"timestamp": round(duration * ratio, 2), "dataUrl": "data:image/jpeg;base64," + _base64.b64encode(frame.read_bytes()).decode("ascii")})
    return frames


def _media_duration(path):
    result = _subprocess.run([_resolve_ffmpeg_command(), "-i", str(path)], stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT, text=True, errors="replace")
    output = result.stdout
    import re
    matched = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", output)
    return int(matched.group(1)) * 3600 + int(matched.group(2)) * 60 + float(matched.group(3)) if matched else 0


def _vision_review(candidate, frames, topic):
    status = (_llm_status() or {}).get("multimodal") or {}
    if not (_VISION_KEY and _VISION_URL and _VISION_MODEL and status.get("ready") and status.get("visionReady")):
        return 0, "多模态模型不可用，已保留文本初筛结果", "degraded"
    content = [{"type": "text", "text": f"判断这些关键帧是否适合主题『{topic}』的无字幕短视频拼接。仅返回 JSON：{{\"score\":0-100,\"reason\":\"简短中文理由\"}}。"}]
    for frame in frames:
        content.append({"type": "image_url", "image_url": {"url": frame["dataUrl"]}})
    def validate(value):
        score = int(value.get("score") or 0)
        reason = str(value.get("reason") or "").strip()
        if not 0 <= score <= 100 or not reason:
            raise ValueError("视觉审核返回无效")
        return {"score": score, "reason": reason[:300]}
    result, _, _ = _call_json_contract(messages=[{"role": "user", "content": content}], contract_id="short_video_candidate_review", validator=validate, model=_VISION_MODEL, api_key=_VISION_KEY, base_url=_VISION_URL, timeout=90, temperature=0.2, max_tokens=300)
    return result["score"], result["reason"], "success"


def run_short_video_candidate_review(project_id, candidate_id, owner_id):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        project = _project(cursor, project_id, owner_id)
        cursor.execute("SELECT * FROM short_video_candidates WHERE id = %s AND project_id = %s", (candidate_id, project_id))
        row = cursor.fetchone()
        if not row:
            raise LookupError("候选素材不存在")
        candidate = dict(row)
    try:
        preview = _download_candidate_preview(candidate)
        frames = _preview_frames(preview)
        score, reason, review_status = _vision_review(candidate, frames, project["topic"])
    except Exception as exc:
        preview, frames, score, reason, review_status = None, [], 0, f"预览分析失败，已降级为文本初筛: {str(exc)[:240]}", "degraded"
        _logger.warning("Short video candidate review degraded : projectId = %s | candidateId = %s | reason = %s", project_id, candidate_id, str(exc)[:300])
    with _db_connect() as conn:
        conn.execute('''UPDATE short_video_candidates SET preview_path = %s, keyframes = %s, analysis_score = %s, analysis_reason = %s, analysis_status = %s, updated_at = %s WHERE id = %s''',
                     (str(preview) if preview else "", _json.dumps([{"timestamp": frame["timestamp"]} for frame in frames]), score, reason, review_status, _now(), candidate_id))
    return {"projectId": project_id, "candidateId": candidate_id, "status": review_status}


def update_short_video_candidates(project_id, candidates):
    _ensure_tables()
    candidates = list(candidates or [])
    if not candidates:
        raise ValueError("至少保留 2 条素材")
    if not 2 <= len(candidates) <= 12:
        raise ValueError("一次合成需选择 2 至 12 条素材")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        project = _project(cursor, project_id, _owner_id())
        for ordinal, entry in enumerate(candidates, start=1):
            candidate_id = str(entry.get("id") or "")
            duration = max(1.0, float(entry.get("clipDurationSeconds") or 0))
            transition = str(entry.get("transitionType") or "")
            if transition and transition not in _VALID_TRANSITIONS:
                raise ValueError("转场类型无效")
            cursor.execute("SELECT duration_seconds FROM short_video_candidates WHERE id = %s AND project_id = %s", (candidate_id, project_id))
            source = cursor.fetchone()
            if not source:
                raise LookupError("候选素材不存在")
            source_duration = float(source.get("duration_seconds") if hasattr(source, "get") else source[0])
            if duration > source_duration:
                raise ValueError("截取时长不能超过原视频时长")
            cursor.execute('''UPDATE short_video_candidates SET selected = 1, ordinal = %s, clip_duration_seconds = %s, transition_type = %s, updated_at = %s
                WHERE id = %s AND project_id = %s''', (ordinal, duration, transition, _now(), candidate_id, project_id))
        ids = [str(entry.get("id") or "") for entry in candidates]
        placeholders = ",".join("%s" for _ in ids)
        cursor.execute(f"UPDATE short_video_candidates SET selected = 0 WHERE project_id = %s AND id NOT IN ({placeholders})", [project_id, *ids])
        total = sum(max(1.0, float(entry.get("clipDurationSeconds") or 0)) for entry in candidates)
        if not 15 <= total <= 90:
            raise ValueError("选段总时长需在 15 至 90 秒之间")
        cursor.execute("UPDATE short_video_projects SET status = 'ready', message = '候选素材已确认', updated_at = %s WHERE id = %s", (_now(), project_id))
    return get_short_video_project(project_id)


def list_short_video_bgm_tracks(enabled_only=True):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM short_video_bgm_tracks" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY title, id")
        return [{**dict(row), "enabled": bool(row["enabled"])} for row in cursor.fetchall()]


def create_short_video_bgm_track(uploaded, payload):
    if not _is_admin():
        raise PermissionError("仅管理员可管理 BGM")
    title = str((payload or {}).get("title") or "").strip()[:120]
    artist = str((payload or {}).get("artist") or "").strip()[:120]
    source_url = str((payload or {}).get("sourceUrl") or "").strip()[:1000]
    license_note = str((payload or {}).get("licenseNote") or "").strip()[:1000]
    if not all((title, artist, source_url, license_note)) or not uploaded or not uploaded.filename:
        raise ValueError("曲名、作者、来源 URL、授权说明和音频文件均为必填")
    suffix = _Path(uploaded.filename).suffix.lower()
    if suffix not in {".mp3", ".m4a", ".aac", ".wav", ".ogg"}:
        raise ValueError("仅支持 MP3、M4A、AAC、WAV 或 OGG 音频")
    _BGM_ROOT.mkdir(parents=True, exist_ok=True)
    destination = _BGM_ROOT / f"{_uuid.uuid4().hex}_{_secure_filename(uploaded.filename)}"
    uploaded.save(destination)
    now = _now()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO short_video_bgm_tracks (title, artist, source_url, license_note, file_path, enabled, created_by_user_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s) RETURNING id''', (title, artist, source_url, license_note, str(destination), _owner_id(), now, now))
        track_id = cursor.fetchone()[0]
    return {"id": track_id, "title": title}


def update_short_video_bgm_track(track_id, payload):
    if not _is_admin():
        raise PermissionError("仅管理员可管理 BGM")
    enabled = 1 if (payload or {}).get("enabled") else 0
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("UPDATE short_video_bgm_tracks SET enabled = %s, updated_at = %s WHERE id = %s", (enabled, _now(), int(track_id)))
        if cursor.rowcount != 1:
            raise LookupError("BGM 不存在")
    return {"id": int(track_id), "enabled": bool(enabled)}


def delete_short_video_bgm_track(track_id):
    if not _is_admin():
        raise PermissionError("仅管理员可管理 BGM")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM short_video_bgm_tracks WHERE id = %s", (int(track_id),))
        row = cursor.fetchone()
        if not row:
            raise LookupError("BGM 不存在")
        cursor.execute("SELECT 1 FROM short_video_projects WHERE bgm_track_id = %s AND status IN ('queued', 'rendering') LIMIT 1", (int(track_id),))
        if cursor.fetchone():
            raise ValueError("BGM 正被运行中的合成任务使用，暂不可删除")
        cursor.execute("DELETE FROM short_video_bgm_tracks WHERE id = %s", (int(track_id),))
    file_path = _Path(row["file_path"] or "")
    if file_path.is_file() and file_path.resolve().is_relative_to(_BGM_ROOT.resolve()):
        file_path.unlink()
    return {"id": int(track_id), "deleted": True}


def add_short_video_channel_whitelist(payload):
    if not _is_admin():
        raise PermissionError("仅管理员可管理授权频道")
    channel = str((payload or {}).get("channel") or "").strip()[:300]
    if not channel:
        raise ValueError("频道名称不能为空")
    with _db_connect() as conn:
        conn.execute("INSERT INTO short_video_channel_whitelist (channel, note, created_by_user_id, created_at) VALUES (%s, %s, %s, %s)", (channel, str((payload or {}).get("note") or "")[:500], _owner_id(), _now()))
    return {"channel": channel}


def list_short_video_channel_whitelist():
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM short_video_channel_whitelist ORDER BY channel, id")
        return [dict(row) for row in cursor.fetchall()]


def delete_short_video_channel_whitelist(channel_id):
    if not _is_admin():
        raise PermissionError("仅管理员可管理授权频道")
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM short_video_channel_whitelist WHERE id = %s", (int(channel_id),))
        if cursor.rowcount != 1:
            raise LookupError("授权频道不存在")
    return {"id": int(channel_id), "deleted": True}


def _download_selected_candidate(candidate):
    import yt_dlp
    target = _ROOT / "sources" / candidate["project_id"]
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"{candidate['id']}.%(ext)s"
    opts = {"quiet": True, "noplaylist": True, "format": "best[height<=1920]/best", "outtmpl": str(output), "merge_output_format": "mp4"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(candidate["source_url"], download=True)
    files = sorted(target.glob(f"{candidate['id']}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("正式下载后未找到视频文件")
    return files[0]


def _render_concat(project, candidates, bgm):
    project_dir = _OUTPUT_ROOT / project["id"]
    project_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    for index, candidate in enumerate(candidates):
        source = _Path(candidate.get("downloaded_file_path") or "")
        if not source.is_file():
            source = _download_selected_candidate(candidate)
            with _db_connect() as conn:
                conn.execute("UPDATE short_video_candidates SET downloaded_file_path = %s, updated_at = %s WHERE id = %s", (str(source), _now(), candidate["id"]))
        normalized_file = project_dir / f"segment_{index:02d}.mp4"
        duration = float(candidate["clip_duration_seconds"])
        command = [_resolve_ffmpeg_command(), "-y", "-i", str(source)]
        if project.get("keep_original_audio"):
            command.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
        command.extend(["-t", f"{duration:.2f}", "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1", "-r", "30"])
        if not project.get("keep_original_audio"):
            command.append("-an")
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a?", "-map", "1:a:0", "-shortest"])
        command.extend([*video_encode_args(_BURN_PROFILES[_DEFAULT_BURN_PROFILE]), "-pix_fmt", "yuv420p", str(normalized_file)])
        _subprocess.run(command, check=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.PIPE)
        normalized.append(normalized_file)
    inputs, filters = [], []
    for index, path in enumerate(normalized):
        inputs.extend(["-i", str(path)])
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
    transition = project["transition_type"]
    per_segment_transitions = [candidate.get("transition_type") or transition for candidate in candidates[1:]]
    if all(mode == "cut" for mode in per_segment_transitions):
        video_filter = ";".join(filters) + ";" + "".join(f"[v{index}]" for index in range(len(normalized))) + f"concat=n={len(normalized)}:v=1:a=0[vout]"
    else:
        current, timeline = "v0", float(candidates[0]["clip_duration_seconds"])
        for index in range(1, len(normalized)):
            name = f"x{index}"
            mode = candidates[index].get("transition_type") or transition
            if mode == "cut":
                filters.append(f"[{current}][v{index}]concat=n=2:v=1:a=0[{name}]")
                timeline += float(candidates[index]["clip_duration_seconds"])
            else:
                filters.append(f"[{current}][v{index}]xfade=transition={mode}:duration=0.35:offset={max(0, timeline - 0.35):.2f}[{name}]")
                timeline += float(candidates[index]["clip_duration_seconds"]) - 0.35
            current = name
        video_filter = ";".join(filters) + f";[{current}]null[vout]"
    if project.get("keep_original_audio"):
        filters.append(";".join(f"[{index}:a]aresample=async=1[a{index}]" for index in range(len(normalized))) + ";" + "".join(f"[a{index}]" for index in range(len(normalized))) + f"concat=n={len(normalized)}:v=0:a=1[aout_raw];[aout_raw]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        video_filter = video_filter + ";" + ";".join(filters[-1:])
    output = project_dir / f"{project['id']}.mp4"
    command = [_resolve_ffmpeg_command(), "-y", *inputs]
    if bgm:
        command.extend(["-stream_loop", "-1", "-i", bgm["file_path"]])
        bgm_input = len(normalized)
        audio_filter = f"[{bgm_input}:a]volume=0.28,aloop=loop=-1:size=2147483647,loudnorm=I=-16:TP=-1.5:LRA=11[bgm]"
        if project.get("keep_original_audio"):
            audio_filter += ";[aout][bgm]amix=inputs=2:duration=first:weights='1 0.6',loudnorm=I=-16:TP=-1.5:LRA=11[mix]"
            command.extend(["-filter_complex", video_filter + ";" + audio_filter, "-map", "[vout]", "-map", "[mix]", "-shortest"])
        else:
            command.extend(["-filter_complex", video_filter + ";" + audio_filter, "-map", "[vout]", "-map", "[bgm]", "-shortest"])
    else:
        command.extend(["-filter_complex", video_filter, "-map", "[vout]"])
        if project.get("keep_original_audio"):
            command.extend(["-map", "[aout]", "-shortest"])
    command.extend([*video_encode_args(_BURN_PROFILES[_DEFAULT_BURN_PROFILE]), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)])
    _subprocess.run(command, check=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.PIPE)
    return output


def run_short_video_render(project_id, owner_id):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        project = _project(cursor, project_id, owner_id)
        cursor.execute("SELECT * FROM short_video_candidates WHERE project_id = %s AND selected = 1 ORDER BY ordinal", (project_id,))
        candidates = [dict(row) for row in cursor.fetchall()]
        if not 2 <= len(candidates) <= 12:
            raise ValueError("请确认 2 至 12 条素材后再渲染")
        bgm = None
        if project.get("bgm_track_id"):
            cursor.execute("SELECT * FROM short_video_bgm_tracks WHERE id = %s AND enabled = 1", (project["bgm_track_id"],))
            bgm_row = cursor.fetchone()
            if not bgm_row:
                raise ValueError("所选 BGM 不可用")
            bgm = dict(bgm_row)
    _set_project_status(project_id, "rendering", "正在下载并合成短视频")
    try:
        output = _render_concat(project, candidates, bgm)
        material = register_material(
            output,
            owner_user_id=_owner_id(),
            source_type="short_video_compilation",
            metadata={"projectId": project_id, "topic": project["topic"], "sourceUrls": [candidate["source_url"] for candidate in candidates]},
            copy_to_library=True,
        )
        _set_project_status(project_id, "success", "短视频拼接完成", output_file_path=str(output), output_material_id=material["id"])
        return {"projectId": project_id, "status": "success", "materialId": material["id"]}
    except Exception as exc:
        _set_project_status(project_id, "failed", f"渲染失败: {str(exc)[:300]}")
        _logger.exception("Short video render failed : projectId = %s", project_id)
        raise


def request_short_video_render(project_id, payload):
    _ensure_tables()
    payload = payload or {}
    transition = str(payload.get("transitionType") or "cut")
    if transition not in _VALID_TRANSITIONS:
        raise ValueError("转场类型无效")
    bgm_id = payload.get("bgmTrackId") or None
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        _project(cursor, project_id, _owner_id())
        cursor.execute("UPDATE short_video_projects SET transition_type = %s, bgm_track_id = %s, keep_original_audio = %s, status = 'queued', message = '合成任务已提交', updated_at = %s WHERE id = %s", (transition, bgm_id, int(bool(payload.get("keepOriginalAudio"))), _now(), project_id))
    _submit_background_task("processing", run_short_video_render, project_id, _owner_id(), owner_user_id=_owner_id())
    return get_short_video_project(project_id)


def short_video_output_file(project_id):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        project = _project(conn.cursor(), project_id, _owner_id())
    output = _Path(project.get("output_file_path") or "")
    if not output.is_file() or not output.resolve().is_relative_to(_OUTPUT_ROOT.resolve()):
        raise LookupError("成片尚不可预览")
    return output


def short_video_candidate_file(project_id, candidate_id, asset="preview", frame_index=0):
    _ensure_tables()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        _project(cursor, project_id, _owner_id())
        cursor.execute("SELECT preview_path FROM short_video_candidates WHERE id = %s AND project_id = %s", (candidate_id, project_id))
        row = cursor.fetchone()
    preview = _Path((row or {}).get("preview_path") or "")
    if not preview.is_file() or not preview.resolve().is_relative_to(_PREVIEW_ROOT.resolve()):
        raise LookupError("候选预览尚不可用")
    if asset == "preview":
        return preview
    frame = preview.parent / f"{preview.stem}_frames" / f"{int(frame_index)}.jpg"
    if not frame.is_file() or not frame.resolve().is_relative_to(_PREVIEW_ROOT.resolve()):
        raise LookupError("关键帧尚不可用")
    return frame
