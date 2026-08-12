"""候选视频的音频优先深度分析，不创建媒体库记录或完整视频下载。"""

from __future__ import annotations

import datetime as _datetime
import hashlib as _hashlib
import json as _json
import math as _math
import re as _re
import shutil as _shutil
import uuid as _uuid
from pathlib import Path as _Path


_CANDIDATE_ANALYSIS_VERSION = "candidate-v1"
_CANDIDATE_ANALYSIS_ACTIVE = {"queued", "running"}
_CANDIDATE_HOOK_PATTERNS = (
    r"\?", r"\b(?:why|how|what|secret|mistake|warning|truth|never)\b",
    r"(?:为什么|怎么|如何|真相|注意|千万|别再|秘密|误区|警告)",
)
_CANDIDATE_STRUCTURE_PATTERNS = (
    r"\b(?:first|then|finally|because|but|however|result)\b",
    r"(?:首先|然后|最后|因为|但是|结果|所以|总结)",
)


def _candidate_now():
    return _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _candidate_json(value, fallback=None):
    try:
        parsed = _json.loads(value or "{}")
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}
    return parsed if isinstance(parsed, dict) else (fallback if fallback is not None else {})


def _candidate_safe_video_id(value):
    value = _re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))
    return value[:128] or "unknown"


def _candidate_job_payload(row):
    item = dict(row or {})
    return {
        "id": str(item.get("id") or ""),
        "sessionId": str(item.get("session_id") or ""),
        "videoId": str(item.get("video_id") or ""),
        "url": str(item.get("source_url") or ""),
        "title": str(item.get("title") or ""),
        "channel": str(item.get("channel") or ""),
        "metadata": _candidate_json(item.get("metadata_snapshot")),
        "status": str(item.get("status") or "queued"),
        "step": str(item.get("step") or "queued"),
        "message": str(item.get("message") or ""),
        "progress": float(item.get("progress") or 0),
        "transcriptAvailable": bool(item.get("transcript_file_path")),
        "result": _candidate_json(item.get("result")),
        "errorReason": str(item.get("error_reason") or ""),
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "finishedAt": item.get("finished_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def get_candidate_analysis_job(job_id, session_id=""):
    init_database_tables()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        values = [str(job_id or "").strip()]
        sql = "SELECT * FROM candidate_analysis_jobs WHERE id = ?"
        if session_id:
            sql += " AND session_id = ?"
            values.append(str(session_id).strip())
        cursor.execute(sql, values)
        row = cursor.fetchone()
    if not row:
        raise LookupError("候选分析任务不存在")
    return _candidate_job_payload(row)


def _candidate_update_job(job_id, **changes):
    if not changes:
        return get_candidate_analysis_job(job_id)
    allowed = {
        "status", "step", "message", "progress", "transcript_file_path", "result",
        "error_reason", "started_at", "finished_at",
    }
    fields = []
    values = []
    for key, value in changes.items():
        if key not in allowed:
            continue
        fields.append(f"{key} = ?")
        values.append(_json.dumps(value, ensure_ascii=False) if key == "result" else value)
    if not fields:
        return get_candidate_analysis_job(job_id)
    fields.append("updated_at = ?")
    values.append(_candidate_now())
    values.append(str(job_id))
    with _db_connect() as conn:
        conn.execute(f"UPDATE candidate_analysis_jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return get_candidate_analysis_job(job_id)


def _candidate_latest_reusable_job(cursor, video_id):
    cursor.execute(
        """
        SELECT * FROM candidate_analysis_jobs
        WHERE video_id = ? AND analysis_version = ? AND status = 'success'
        ORDER BY finished_at DESC, updated_at DESC
        LIMIT 1
        """,
        (video_id, _CANDIDATE_ANALYSIS_VERSION),
    )
    return cursor.fetchone()


def _candidate_active_job(cursor, video_id):
    cursor.execute(
        """
        SELECT * FROM candidate_analysis_jobs
        WHERE video_id = ? AND analysis_version = ? AND status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (video_id, _CANDIDATE_ANALYSIS_VERSION),
    )
    return cursor.fetchone()


def create_candidate_analysis_jobs(session_id, candidates):
    """创建最多配置数量的音频分析任务，并优先复用同视频的转写结果。"""
    init_database_tables()
    session_id = str(session_id or "").strip()
    if not session_id:
        raise ValueError("缺少 Agent 会话标识")
    normalized = []
    seen = set()
    for item in candidates or []:
        item = item if isinstance(item, dict) else {}
        video_id = _candidate_safe_video_id(item.get("id"))
        url = str(item.get("url") or "").strip()
        if not url or video_id == "unknown" or video_id in seen:
            continue
        seen.add(video_id)
        normalized.append({
            "id": video_id,
            "url": url,
            "title": str(item.get("title") or ""),
            "channel": str(item.get("channel") or ""),
            "metadata": {
                "viewCount": int(item.get("viewCount") or 0),
                "durationSeconds": float(item.get("durationSeconds") or 0),
                "publishedAt": str(item.get("publishedAt") or ""),
                "subscribers": str(item.get("subscribers") or ""),
                "metadataScore": int(item.get("metadataScore") or 0),
                "metadataSignals": list(item.get("metadataSignals") or [])[:4],
            },
        })
    if not normalized:
        raise ValueError("请选择可分析的候选视频")
    if len(normalized) > CANDIDATE_ANALYSIS_MAX_ITEMS:
        raise ValueError(f"每次最多深度分析 {CANDIDATE_ANALYSIS_MAX_ITEMS} 条候选视频")

    created = []
    queued_ids = []
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        for item in normalized:
            cached = _candidate_latest_reusable_job(cursor, item["id"])
            if cached:
                cached_result = _candidate_json(cached["result"])
                content_score = int(cached_result.get("contentScore") or 0)
                metadata_score = int(item["metadata"].get("metadataScore") or 0)
                if content_score:
                    cached_result["metadataScore"] = metadata_score
                    cached_result["score"] = round(metadata_score * 0.55 + content_score * 0.45)
                job_id = f"candidate_{_uuid.uuid4().hex}"
                now = _candidate_now()
                cursor.execute(
                    """
                    INSERT INTO candidate_analysis_jobs (
                        id, session_id, video_id, source_url, title, channel, metadata_snapshot,
                        analysis_version, status, step, message, progress, transcript_file_path, result,
                        created_at, started_at, finished_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', 'done', ?, 100, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, session_id, item["id"], item["url"], item["title"], item["channel"],
                        _json.dumps(item["metadata"], ensure_ascii=False), _CANDIDATE_ANALYSIS_VERSION,
                        "已复用此前的候选音频分析结果", cached["transcript_file_path"] or "",
                        _json.dumps(cached_result, ensure_ascii=False), now, now, now, now,
                    ),
                )
                created.append({
                    "id": job_id, "sessionId": session_id, "videoId": item["id"], "url": item["url"],
                    "title": item["title"], "channel": item["channel"], "metadata": item["metadata"],
                    "status": "success", "step": "done", "message": "已复用此前的候选音频分析结果",
                    "progress": 100, "transcriptAvailable": bool(cached["transcript_file_path"]), "result": cached_result,
                    "errorReason": "", "createdAt": now, "startedAt": now, "finishedAt": now, "updatedAt": now,
                    "cached": True,
                })
                continue
            active = _candidate_active_job(cursor, item["id"])
            if active and str(active["session_id"] or "") == session_id:
                created.append(_candidate_job_payload(active))
                continue
            job_id = f"candidate_{_uuid.uuid4().hex}"
            now = _candidate_now()
            cursor.execute(
                """
                INSERT INTO candidate_analysis_jobs (
                    id, session_id, video_id, source_url, title, channel, metadata_snapshot,
                    analysis_version, status, step, message, progress, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', ?, 0, ?, ?)
                """,
                (
                    job_id, session_id, item["id"], item["url"], item["title"], item["channel"],
                    _json.dumps(item["metadata"], ensure_ascii=False), _CANDIDATE_ANALYSIS_VERSION,
                    "等待音频深度分析", now, now,
                ),
            )
            queued_ids.append(job_id)
            created.append({
                "id": job_id,
                "sessionId": session_id,
                "videoId": item["id"],
                "url": item["url"],
                "title": item["title"],
                "channel": item["channel"],
                "metadata": item["metadata"],
                "status": "queued",
                "step": "queued",
                "message": "等待音频深度分析",
                "progress": 0,
                "transcriptAvailable": False,
                "result": {},
                "errorReason": "",
                "createdAt": now,
                "startedAt": "",
                "finishedAt": "",
                "updatedAt": now,
            })
        conn.commit()
    for job_id in queued_ids:
        try:
            _submit_background_task("candidate_analysis", run_candidate_analysis_job, job_id)
        except Exception as exc:
            _candidate_update_job(job_id, status="failed", step="failed", message="候选分析任务未能排队", error_reason=str(exc), finished_at=_candidate_now())
    return created


def _candidate_claim_job(job_id):
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE candidate_analysis_jobs
            SET status = 'running', step = 'audio_download', message = '正在下载音频，不会下载完整视频',
                progress = 8, started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (_candidate_now(), _candidate_now(), str(job_id)),
        )
        conn.commit()
        return cursor.rowcount == 1


def _candidate_audio_dir(job_id):
    root = _Path(BASE_DIR) / ".runtime" / "candidate-analysis" / _candidate_safe_video_id(job_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _download_candidate_audio(job, work_dir):
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，无法执行候选音频分析") from exc
    output_template = str(_Path(work_dir) / "%(id)s.%(ext)s")
    options = {
        **_base_ytdlp_opts(include_ffmpeg=True),
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
        "overwrites": True,
        "retries": 2,
        "extractor_retries": 1,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(job["url"], download=True) or {}
        output = _Path(ydl.prepare_filename(info))
    if output.is_file():
        return output
    files = [path for path in _Path(work_dir).iterdir() if path.is_file()]
    if not files:
        raise RuntimeError("yt-dlp 未生成候选音频文件")
    return max(files, key=lambda path: path.stat().st_mtime)


def _candidate_transcript_path(video_id):
    root = _Path(YOUTUBE_TRANSCRIPT_DIR) / "candidate-analysis"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_candidate_safe_video_id(video_id)}.json"


def _candidate_transcript_text(segments, max_chars=LLM_MAX_TRANSCRIPT_CHARS):
    chunks = []
    total = 0
    for segment in segments or []:
        text = _re.sub(r"\s+", " ", str((segment or {}).get("text") or "").strip())
        if not text:
            continue
        stamp = f"[{int(float(segment.get('start') or 0))}s] "
        chunk = stamp + text
        if total + len(chunk) > max_chars:
            chunks.append(chunk[:max(0, max_chars - total)])
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n".join(chunks)


def _candidate_subscriber_count(value):
    text = str(value or "").strip().lower().replace(",", "")
    match = _re.search(r"([\d.]+)\s*(万|w|k|m)?", text)
    if not match:
        return 0
    try:
        amount = float(match.group(1))
    except ValueError:
        return 0
    unit = match.group(2)
    return int(amount * {"万": 10000, "w": 10000, "k": 1000, "m": 1000000}.get(unit, 1))


def _candidate_content_features(segments, metadata):
    transcript = _candidate_transcript_text(segments)
    early = " ".join(
        str((segment or {}).get("text") or "")
        for segment in segments or [] if float((segment or {}).get("start") or 0) < 45
    ).strip()
    duration = max(float(metadata.get("durationSeconds") or 0), float((segments or [{}])[-1].get("end") or 0), 1)
    text_length = len(_re.sub(r"\s+", "", transcript))
    hook_hits = sum(bool(_re.search(pattern, early, _re.I)) for pattern in _CANDIDATE_HOOK_PATTERNS)
    structure_hits = sum(bool(_re.search(pattern, transcript, _re.I)) for pattern in _CANDIDATE_STRUCTURE_PATTERNS)
    density = text_length / max(duration / 60, 1)
    hook_score = min(40, 12 + hook_hits * 11 + min(6, len(early) // 90)) if early else 0
    density_score = min(25, round(density / 18))
    structure_score = min(20, structure_hits * 7)
    duration_score = 15 if duration <= 600 else 11 if duration <= 1200 else 7
    content_score = int(min(100, hook_score + density_score + structure_score + duration_score))
    confidence = "低" if text_length < 180 else "中" if text_length < 900 else "高"
    reasons = []
    if hook_score >= 25:
        reasons.append("前 45 秒出现提问、反差或结论型开场信号")
    if density_score >= 15:
        reasons.append("转写内容的信息密度较高")
    if structure_score >= 14:
        reasons.append("字幕中检测到较完整的叙事连接词")
    if not reasons:
        reasons.append("已完成字幕结构扫描，但强开场信号有限")
    risks = []
    if text_length < 180:
        risks.append("有效语音较少，内容结论置信度较低")
    if duration > CANDIDATE_ANALYSIS_MAX_DURATION_SECONDS * 0.85:
        risks.append("视频时长接近深度分析上限，传播结构判断可能不完整")
    return {
        "transcript": transcript,
        "transcriptChars": text_length,
        "hookExcerpt": _re.sub(r"\s+", " ", early)[:220],
        "contentScore": content_score,
        "confidence": confidence,
        "reasons": reasons,
        "risks": risks,
    }


def _candidate_llm_analysis(features):
    if not (TEXT_LLM_API_KEY and TEXT_LLM_BASE_URL and TEXT_LLM_MODEL):
        return {}
    transcript = str(features.get("transcript") or "")
    if not transcript:
        return {}

    def validate(value):
        value = value if isinstance(value, dict) else {}
        strengths = [str(item).strip()[:100] for item in value.get("strengths") or [] if str(item).strip()][:3]
        risks = [str(item).strip()[:100] for item in value.get("risks") or [] if str(item).strip()][:3]
        clips = []
        for item in value.get("clipMoments") or []:
            if not isinstance(item, dict):
                continue
            try:
                start = max(0, int(float(item.get("startSeconds") or 0)))
            except (TypeError, ValueError):
                continue
            reason = str(item.get("reason") or "").strip()[:100]
            if reason:
                clips.append({"startSeconds": start, "reason": reason})
        return {
            "summary": str(value.get("summary") or "").strip()[:240],
            "strengths": strengths,
            "risks": risks,
            "clipMoments": clips[:3],
        }

    try:
        result, _, _ = call_json_contract(
            messages=[
                {"role": "system", "content": "你是短视频选题分析助手。仅根据转写内容给出中文、可解释的传播结构判断，不得承诺爆款，不得编造画面或数据。只返回 JSON。"},
                {"role": "user", "content": "转写内容：\n" + transcript},
            ],
            contract_id="candidate_audio_analysis",
            validator=validate,
            model=TEXT_LLM_MODEL,
            api_key=TEXT_LLM_API_KEY,
            base_url=TEXT_LLM_BASE_URL,
            timeout=LLM_TIMEOUT,
            temperature=0.1,
            max_tokens=700,
            prompt_version="candidate-audio-analysis-v1",
        )
        return result
    except Exception:
        backend_logger.exception("候选视频 LLM 字幕分析失败，将使用规则结果")
        return {}


def _candidate_final_result(job, segments):
    metadata = job.get("metadata") or {}
    features = _candidate_content_features(segments, metadata)
    llm = _candidate_llm_analysis(features)
    metadata_score = max(0, min(100, int(metadata.get("metadataScore") or 0)))
    content_score = int(features["contentScore"])
    total_score = round(metadata_score * 0.55 + content_score * 0.45)
    reasons = list(metadata.get("metadataSignals") or [])[:3] + features["reasons"]
    risks = features["risks"] + list(llm.get("risks") or [])
    return {
        "version": _CANDIDATE_ANALYSIS_VERSION,
        "analysisMethod": "audio_asr",
        "score": total_score,
        "metadataScore": metadata_score,
        "contentScore": content_score,
        "confidence": features["confidence"],
        "summary": llm.get("summary") or "已基于音频转写、元数据热度与内容结构完成分析。",
        "hookExcerpt": features["hookExcerpt"],
        "reasons": reasons[:5],
        "risks": list(dict.fromkeys(risks))[:4],
        "clipMoments": llm.get("clipMoments") or [],
        "transcriptChars": features["transcriptChars"],
        "transcriptHash": _hashlib.sha256(features["transcript"].encode("utf-8")).hexdigest(),
    }


def run_candidate_analysis_job(job_id):
    if not _candidate_claim_job(job_id):
        return get_candidate_analysis_job(job_id)
    job = get_candidate_analysis_job(job_id)
    metadata = job.get("metadata") or {}
    duration = float(metadata.get("durationSeconds") or 0)
    if duration > CANDIDATE_ANALYSIS_MAX_DURATION_SECONDS:
        return _candidate_update_job(
            job_id, status="failed", step="failed", progress=100,
            message=f"视频超过 {CANDIDATE_ANALYSIS_MAX_DURATION_SECONDS // 60} 分钟的深度分析上限",
            error_reason="CANDIDATE_DURATION_LIMIT", finished_at=_candidate_now(),
        )
    work_dir = _candidate_audio_dir(job_id)
    try:
        audio_source = _download_candidate_audio(job, work_dir)
        _candidate_update_job(job_id, step="asr", progress=35, message="音频下载完成，正在进行语音识别")
        whisper_audio = _extract_audio_for_whisper(audio_source, work_dir)
        if audio_source != whisper_audio:
            audio_source.unlink(missing_ok=True)
        segments, language = _transcribe_audio(
            whisper_audio,
            progress_callback=lambda message: _candidate_update_job(job_id, step="asr", progress=55, message=message),
        )
        whisper_audio.unlink(missing_ok=True)
        transcript_path = _candidate_transcript_path(job["videoId"])
        transcript_path.write_text(_json.dumps({
            "videoId": job["videoId"], "language": language, "segments": segments,
            "createdAt": _candidate_now(), "source": "candidate_audio_analysis",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _candidate_update_job(job_id, step="content_analysis", progress=76, message="正在计算内容结构与传播潜力")
        result = _candidate_final_result(job, segments)
        return _candidate_update_job(
            job_id, status="success", step="done", progress=100, message="候选音频深度分析完成",
            transcript_file_path=str(transcript_path), result=result, error_reason="", finished_at=_candidate_now(),
        )
    except Exception as exc:
        backend_logger.exception("候选音频深度分析失败 job_id=%s", job_id)
        return _candidate_update_job(
            job_id, status="failed", step="failed", progress=100, message="候选音频深度分析失败",
            error_reason=str(exc)[:500], finished_at=_candidate_now(),
        )
    finally:
        _shutil.rmtree(work_dir, ignore_errors=True)
