"""视频广告风险检测、人工决议与多区间裁剪。"""

import json
import re
from pathlib import Path

from app.config import BASE_DIR, LLM_TIMEOUT, TEXT_LLM_API_KEY, TEXT_LLM_BASE_URL, TEXT_LLM_MODEL, YOUTUBE_PROCESSED_DIR
from app.core import llm_prompts
from app.core.llm_harness import call_json_contract


CONTENT_SAFETY_VERSION = "ad-risk-v1"
CONTENT_SAFETY_SIGNAL_RE = re.compile(
    r"\b(?:download|sign\s*up|register|promo\s*code|discount|coupon|sponsor(?:ed)?|"
    r"link\s+in|scan\s+(?:the\s+)?qr|website|app|use\s+code|free\s+trial)\b|"
    r"(?:下载|注册|优惠码|折扣码|赞助|链接|二维码|扫码|官网|应用|平台)", re.IGNORECASE,
)
CONTENT_SAFETY_URL_RE = re.compile(r"(?:https?://|www\.|\b[\w-]+\.(?:com|net|org|io|app|cn)\b)", re.IGNORECASE)


def _content_safety_format_time(value):
    seconds = max(0, float(value or 0))
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


def _content_safety_normalize_ranges(ranges, duration=0):
    normalized = []
    for item in ranges or []:
        try:
            start = float(item.get("start") if isinstance(item, dict) else item[0])
            end = float(item.get("end") if isinstance(item, dict) else item[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError("裁剪区间必须包含有效的起止秒数")
        if start < 0 or end <= start:
            raise ValueError("裁剪区间起止时间不合法")
        if duration and end > float(duration) + 0.05:
            raise ValueError("裁剪区间超出视频时长")
        normalized.append({"start": round(start, 3), "end": round(end, 3)})
    normalized.sort(key=lambda item: (item["start"], item["end"]))
    merged = []
    for item in normalized:
        if merged and item["start"] <= merged[-1]["end"] + 0.05:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
        else:
            merged.append(item)
    return merged


def _content_safety_keep_ranges(duration, cut_ranges):
    cursor, kept = 0.0, []
    for item in cut_ranges:
        if item["start"] > cursor:
            kept.append({"start": cursor, "end": item["start"]})
        cursor = item["end"]
    if cursor < duration:
        kept.append({"start": cursor, "end": duration})
    return [item for item in kept if item["end"] - item["start"] >= 0.08]


def _content_safety_remap_segments(segments, cut_ranges):
    remapped = []
    for segment in segments or []:
        try:
            start, end = float(segment.get("start") or 0), float(segment.get("end") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if end <= start or any(start < item["end"] and end > item["start"] for item in cut_ranges):
            continue
        offset = sum(item["end"] - item["start"] for item in cut_ranges if item["end"] <= start)
        remapped.append({**segment, "start": round(start - offset, 3), "end": round(end - offset, 3)})
    return remapped


def _content_safety_rule_candidates(segments):
    candidates, current = [], []
    for index, segment in enumerate(segments or []):
        text = str(segment.get("text") or "")
        if CONTENT_SAFETY_SIGNAL_RE.search(text) or CONTENT_SAFETY_URL_RE.search(text):
            current.append(index)
            continue
        if current:
            candidates.append(current)
            current = []
    if current:
        candidates.append(current)
    result = []
    for indexes in candidates:
        first, last = segments[indexes[0]], segments[indexes[-1]]
        start, end = float(first.get("start") or 0), float(last.get("end") or 0)
        combined = " ".join(str(segments[index].get("text") or "") for index in indexes)
        # 单句提及不进入模型判断；必须有持续语境或两个推广信号。
        signals = len(CONTENT_SAFETY_SIGNAL_RE.findall(combined)) + len(CONTENT_SAFETY_URL_RE.findall(combined))
        if end - start >= 12 or signals >= 2:
            result.append({"startCueIndex": indexes[0], "endCueIndex": indexes[-1], "start": start, "end": end})
    return result


def _validate_content_safety_result(value, segments):
    if not isinstance(value, dict) or not isinstance(value.get("risks"), list):
        raise ValueError("risks 必须为数组")
    risks = []
    for item in value["risks"]:
        if not isinstance(item, dict):
            raise ValueError("风险项必须为对象")
        start_index, end_index = int(item.get("startCueIndex")), int(item.get("endCueIndex"))
        if start_index < 0 or end_index < start_index or end_index >= len(segments):
            raise ValueError("风险项字幕边界无效")
        if str(item.get("verdict") or "") != "advertising":
            continue
        risks.append({
            "start": float(segments[start_index].get("start") or 0),
            "end": float(segments[end_index].get("end") or 0),
            "startCueIndex": start_index,
            "endCueIndex": end_index,
            "evidence": str(item.get("evidence") or "").strip()[:240],
            "signals": [str(signal)[:40] for signal in item.get("signals") or [] if str(signal).strip()][:5],
            "riskLevel": str(item.get("riskLevel") or "medium"),
        })
    return {"risks": risks}


def detect_content_safety(job, segments, telemetry=None):
    if not segments:
        return {"status": "unavailable", "version": CONTENT_SAFETY_VERSION, "candidates": [], "risks": [], "reason": "未检测到可用语音转写"}, {}
    candidates = _content_safety_rule_candidates(segments)
    if not candidates:
        return {"status": "clear", "version": CONTENT_SAFETY_VERSION, "candidates": [], "risks": []}, {}
    prompt = llm_prompts.build_content_safety_prompt(job, segments, candidates)
    result, usage, _ = call_json_contract(
        messages=[{"role": "system", "content": llm_prompts.content_safety_system_prompt()}, {"role": "user", "content": prompt}],
        contract_id="content_safety_detection",
        validator=lambda value: _validate_content_safety_result(value, segments),
        model=TEXT_LLM_MODEL,
        api_key=TEXT_LLM_API_KEY,
        base_url=TEXT_LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=0,
        max_tokens=1800,
        prompt_version=CONTENT_SAFETY_VERSION,
        telemetry=telemetry,
        retry_max_tokens=2600,
    )
    risks = _content_safety_normalize_ranges(result.get("risks") or [])
    by_range = {(round(item["start"], 3), round(item["end"], 3)): item for item in result.get("risks") or []}
    return {
        "status": "pending" if risks else "clear", "version": CONTENT_SAFETY_VERSION,
        "candidates": candidates,
        "risks": [{**item, **by_range.get((item["start"], item["end"]), {})} for item in risks],
    }, usage


def save_content_safety_snapshot(job, snapshot):
    """PostgreSQL 审查明细；任务 content_risk 同时保存摘要供工作流快速读取。"""
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO youtube_content_safety_audits (job_id, video_id, video_title, snapshot, status, saved_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (job_id) DO UPDATE SET snapshot = EXCLUDED.snapshot, status = EXCLUDED.status, saved_at = CURRENT_TIMESTAMP
        ''', (job.get("id") or "", job.get("videoId") or "", job.get("title") or "", json.dumps(snapshot, ensure_ascii=False), snapshot.get("status") or ""))
        conn.commit()


def get_content_safety_snapshot(job_id):
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT snapshot FROM youtube_content_safety_audits WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        return {}


def resolve_content_safety_confirmation(job_id, decision, ranges=None, reason="", owner_user_id=None):
    if decision not in {"trim", "safe"}:
        raise ValueError("decision 必须是 trim 或 safe")
    reason = str(reason or "").strip()
    if decision == "safe" and not reason:
        raise ValueError("标记安全时必须填写原因")
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        if owner_user_id is None:
            cursor.execute("SELECT * FROM youtube_workflow_jobs WHERE id = ? FOR UPDATE", (job_id,))
        else:
            cursor.execute(
                "SELECT * FROM youtube_workflow_jobs WHERE id = ? AND owner_user_id = ? FOR UPDATE",
                (job_id, int(owner_user_id)),
            )
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        job = _row_to_workflow_job(row)
        if job.get("status") != "waiting_confirmation" or job.get("step") != "content_safety_confirm":
            raise WorkflowConflictError("该任务当前无需视频处理确认，或确认已处理。", "VF-CONTENT-SAFETY-CONFIRMATION-INVALID", "CONTENT_SAFETY_CONFIRMATION_INVALID", {"job": job})
        cursor.execute("SELECT snapshot FROM youtube_content_safety_audits WHERE job_id = ? FOR UPDATE", (job_id,))
        audit_row = cursor.fetchone()
        if not audit_row:
            raise WorkflowConflictError("未找到广告风险审查记录。", "VF-CONTENT-SAFETY-SNAPSHOT-MISSING", "CONTENT_SAFETY_SNAPSHOT_MISSING", {"jobId": job_id})
        snapshot = json.loads(audit_row["snapshot"] or "{}")
        source_file = Path(job.get("sourceFilePath") or "")
        if not source_file.is_file():
            raise FileNotFoundError("未找到待裁剪源视频")
        duration = float(_get_video_info(source_file).get("duration") or 0)
        selected = _content_safety_normalize_ranges(
            ranges if ranges is not None else snapshot.get("risks") or [], duration
        ) if decision == "trim" else []
        if decision == "trim" and not selected:
            raise ValueError("裁剪时至少保留一个有效区间")
        snapshot.update({
            "status": "confirmed", "decision": decision, "decisionReason": reason,
            "trimRanges": selected, "confirmedAt": _now_iso(),
        })
        content_risk = {**(job.get("contentRisk") or {}), "contentSafety": snapshot}
        cursor.execute('''
            UPDATE youtube_content_safety_audits
            SET snapshot = ?, status = 'confirmed', saved_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
        ''', (json.dumps(snapshot, ensure_ascii=False), job_id))
        cursor.execute('''
            UPDATE youtube_workflow_jobs
            SET status = 'queued', step = ?, message = ?, content_risk = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'waiting_confirmation' AND step = 'content_safety_confirm'
        ''', (
            "content_trim" if decision == "trim" else "subtitle",
            "已确认广告裁剪，正在恢复处理" if decision == "trim" else "已标记广告候选安全，正在恢复处理",
            json.dumps(content_risk, ensure_ascii=False), job_id,
        ))
        if cursor.rowcount != 1:
            raise WorkflowConflictError("该任务的视频处理确认已被其他请求处理。", "VF-CONTENT-SAFETY-CONFIRMATION-INVALID", "CONTENT_SAFETY_CONFIRMATION_INVALID", {"jobId": job_id})
        conn.commit()
    return get_youtube_workflow_job(job_id)


def _content_safety_trim_video(job, source_file, ranges):
    source_file = Path(source_file)
    info = _get_video_info(source_file)
    duration = float(info.get("duration") or 0)
    ranges = _content_safety_normalize_ranges(ranges, duration)
    kept = _content_safety_keep_ranges(duration, ranges)
    if not kept:
        raise ValueError("裁剪区间删除了全部视频内容")
    output = _ensure_dir(YOUTUBE_PROCESSED_DIR) / f"{job.get('id')}_content_safe.mp4"
    ffmpeg = _resolve_ffmpeg_command()
    _, burn_config = _burn_profile_config(job.get("burnProfile"))
    command = [ffmpeg, "-y"]
    for _ in kept:
        command.extend(["-i", str(source_file)])
    filters, concat_inputs = [], []
    for index, item in enumerate(kept):
        clip_duration = item["end"] - item["start"]
        filters.append(f"[{index}:v]trim=start={item['start']}:end={item['end']},setpts=PTS-STARTPTS,fade=t=in:st=0:d=0.08,fade=t=out:st={max(0, clip_duration - 0.08):.3f}:d=0.08[v{index}]")
        filters.append(f"[{index}:a]atrim=start={item['start']}:end={item['end']},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.12,afade=t=out:st={max(0, clip_duration - 0.12):.3f}:d=0.12[a{index}]")
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append(f"{''.join(concat_inputs)}concat=n={len(kept)}:v=1:a=1[v][a]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", *video_encode_args(burn_config), "-c:a", "aac", "-movflags", "+faststart", str(output)])
    _run_command(command, cwd=BASE_DIR)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("CONTENT_TRIM_OUTPUT_INVALID")
    return output, ranges
