"""版本二高光的多模态画面审核与语义边界收敛。"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import LLM_TIMEOUT, MULTIMODAL_LLM_API_KEY, MULTIMODAL_LLM_BASE_URL, MULTIMODAL_LLM_MODEL
from app.core import llm_prompts
from app.core.llm_harness import call_json_contract, contains_profanity
from app.utils.ffmpeg_util import _resolve_ffmpeg_command


HIGHLIGHT_CANDIDATE_LIMIT = 4
HIGHLIGHT_FRAME_COUNT = 10
HIGHLIGHT_CONTEXT_SECONDS = 4
HIGHLIGHT_MIN_START_SECONDS = 30
HIGHLIGHT_MIN_DURATION_SECONDS = 6
HIGHLIGHT_MAX_DURATION_SECONDS = 12
HIGHLIGHT_FRAME_WIDTH = 640
HIGHLIGHT_REVIEW_TOTAL_TIMEOUT_SECONDS = 720
HIGHLIGHT_REVIEW_MIN_REQUEST_SECONDS = 15


_logger = logging.getLogger("vidferry.backend")


def _clip_float(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _review_window(candidate, duration):
    start = max(HIGHLIGHT_MIN_START_SECONDS, _clip_float(candidate.get("start")))
    end = max(start, _clip_float(candidate.get("end")))
    return max(HIGHLIGHT_MIN_START_SECONDS, start - HIGHLIGHT_CONTEXT_SECONDS), min(duration, end + HIGHLIGHT_CONTEXT_SECONDS)


def _window_cues(transcript_segments, window_start, window_end):
    cues = []
    for segment in transcript_segments or []:
        start = _clip_float(segment.get("start"))
        end = _clip_float(segment.get("end"))
        text = str(segment.get("text") or "").strip()
        if not text or start < window_start or end > window_end or end <= start:
            continue
        cues.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return cues


def _blocked_ranges(transcript_segments):
    return [
        (_clip_float(segment.get("start")), _clip_float(segment.get("end")))
        for segment in transcript_segments or []
        if contains_profanity(segment.get("text")) and _clip_float(segment.get("end")) > _clip_float(segment.get("start"))
    ]


def _frame_timestamps(window_start, window_end):
    if window_end <= window_start:
        return []
    if HIGHLIGHT_FRAME_COUNT == 1:
        return [round(window_start, 2)]
    step = (window_end - window_start) / (HIGHLIGHT_FRAME_COUNT - 1)
    return [round(window_start + index * step, 2) for index in range(HIGHLIGHT_FRAME_COUNT)]


def _extract_frames(video_path, timestamps):
    ffmpeg = _resolve_ffmpeg_command()
    frames = []
    with tempfile.TemporaryDirectory(prefix="vidferry-highlight-frames-") as tmp_dir:
        tmp_dir = Path(tmp_dir)
        for index, timestamp in enumerate(timestamps, start=1):
            frame_path = tmp_dir / f"frame_{index}.jpg"
            command = [
                ffmpeg, "-y", "-ss", f"{timestamp:.2f}", "-i", str(video_path),
                "-frames:v", "1", "-vf", f"scale='min({HIGHLIGHT_FRAME_WIDTH},iw)':-2", str(frame_path),
            ]
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if frame_path.is_file():
                frames.append({
                    "timestamp": timestamp,
                    "dataUrl": "data:image/jpeg;base64," + base64.b64encode(frame_path.read_bytes()).decode("ascii"),
                })
    if len(frames) != len(timestamps):
        raise RuntimeError("高光审核关键帧抽取不完整")
    return frames


def _validate_vision_result(value, cues):
    if not isinstance(value, dict) or set(value) != {"startCueIndex", "endCueIndex", "score", "reason"}:
        raise ValueError("高光视觉审核返回字段不合法")
    start_index = int(value.get("startCueIndex"))
    end_index = int(value.get("endCueIndex"))
    score = _clip_float(value.get("score"), -1)
    reason = str(value.get("reason") or "").strip()
    if not (0 <= start_index <= end_index < len(cues)) or not reason or not 0 <= score <= 100:
        raise ValueError("高光视觉审核返回值不合法")
    start = cues[start_index]["start"]
    end = cues[end_index]["end"]
    if not HIGHLIGHT_MIN_DURATION_SECONDS <= end - start <= HIGHLIGHT_MAX_DURATION_SECONDS:
        raise ValueError("高光视觉审核时长不符合要求")
    return {"start": start, "end": end, "score": round(score, 2), "reason": reason}


def _review_candidate(candidate, video_path, transcript_segments, video_duration, blocked_ranges=(), timeout=LLM_TIMEOUT, telemetry=None):
    window_start, window_end = _review_window(candidate, video_duration)
    cues = _window_cues(transcript_segments, window_start, window_end)
    if not cues:
        raise RuntimeError("高光审核窗口内没有可用字幕边界")
    frames = _extract_frames(video_path, _frame_timestamps(window_start, window_end))
    content = [{
        "type": "text",
        "text": llm_prompts.build_highlight_vision_prompt(candidate, window_start, window_end, cues),
    }]
    for frame in frames:
        content.append({"type": "text", "text": f"画面时间：{frame['timestamp']:.2f} 秒"})
        content.append({"type": "image_url", "image_url": {"url": frame["dataUrl"]}})
    result, _, _ = call_json_contract(
        messages=[
            {"role": "system", "content": llm_prompts.highlight_vision_system_prompt()},
            {"role": "user", "content": content},
        ],
        contract_id="highlight_vision_review",
        validator=lambda value: _validate_vision_result(value, cues),
        model=MULTIMODAL_LLM_MODEL,
        api_key=MULTIMODAL_LLM_API_KEY,
        base_url=MULTIMODAL_LLM_BASE_URL,
        timeout=timeout,
        temperature=0.2,
        max_tokens=600,
        prompt_version=llm_prompts.HIGHLIGHT_VISION_PROMPT_VERSION,
        telemetry=telemetry,
    )
    if any(result["start"] < end and result["end"] > start for start, end in blocked_ranges):
        raise ValueError("高光视觉审核覆盖风险转写区间")
    return result


def refine_highlight_segments(job, video_path, transcript_segments, candidates, video_duration, progress_callback=None, total_timeout_seconds=HIGHLIGHT_REVIEW_TOTAL_TIMEOUT_SECONDS, telemetry=None):
    try:
        target_count = int((job or {}).get("highlightCount") or 3)
    except (TypeError, ValueError):
        target_count = 3
    target_count = max(1, min(3, target_count))
    candidates = list(candidates or [])[:HIGHLIGHT_CANDIDATE_LIMIT]
    fallback = [dict(item) for item in candidates[:target_count]]
    if not candidates:
        return [], {"status": "skipped", "reason": "无可用文本候选", "candidateCount": 0, "timedOut": False}
    if not (MULTIMODAL_LLM_API_KEY and MULTIMODAL_LLM_BASE_URL and MULTIMODAL_LLM_MODEL):
        return fallback, {"status": "degraded", "reason": "未配置多模态模型", "candidateCount": len(candidates), "timedOut": False}

    started_at = time.monotonic()
    reviewed = []
    failures = []
    timed_out = False
    blocked_ranges = _blocked_ranges(transcript_segments)
    _logger.info(
        "高光视觉审核开始 job_id=%s candidates=%s target=%s timeout_seconds=%s",
        (job or {}).get("id") or "", len(candidates), target_count, total_timeout_seconds,
    )
    for index, candidate in enumerate(candidates):
        elapsed = time.monotonic() - started_at
        remaining = float(total_timeout_seconds) - elapsed
        remaining_candidates = len(candidates) - index
        if remaining < HIGHLIGHT_REVIEW_MIN_REQUEST_SECONDS * remaining_candidates:
            timed_out = True
            failures.append("高光视觉审核总耗时超过限制，已降级为文本候选")
            _logger.warning("高光视觉审核超时 job_id=%s elapsed_seconds=%.1f", (job or {}).get("id") or "", elapsed)
            break
        if progress_callback:
            progress_callback(index + 1, len(candidates), round(remaining, 1))
        request_timeout = max(
            HIGHLIGHT_REVIEW_MIN_REQUEST_SECONDS,
            min(LLM_TIMEOUT, int(remaining / remaining_candidates)),
        )
        _logger.info(
            "高光视觉审核候选开始 job_id=%s candidate=%s/%s start=%.2f end=%.2f timeout_seconds=%s",
            (job or {}).get("id") or "", index + 1, len(candidates),
            _clip_float(candidate.get("start")), _clip_float(candidate.get("end")), request_timeout,
        )
        try:
            result = _review_candidate(candidate, video_path, transcript_segments, video_duration, blocked_ranges, request_timeout, telemetry)
            reviewed.append({
                **candidate,
                "start": result["start"],
                "end": result["end"],
                "reason": f"{candidate.get('reason') or ''}；视觉审核：{result['reason']}".strip("；"),
                "_score": result["score"],
            })
            _logger.info(
                "高光视觉审核候选完成 job_id=%s candidate=%s/%s score=%.1f",
                (job or {}).get("id") or "", index + 1, len(candidates), result["score"],
            )
        except Exception as exc:
            failures.append(str(exc)[:160])
            _logger.warning(
                "高光视觉审核候选失败 job_id=%s candidate=%s/%s reason=%s",
                (job or {}).get("id") or "", index + 1, len(candidates), str(exc)[:300],
            )

    selected = []
    for candidate in sorted(reviewed, key=lambda item: item["_score"], reverse=True):
        if any(candidate["start"] < item["end"] and candidate["end"] > item["start"] for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= target_count:
            break
    if len(selected) < target_count:
        for candidate in fallback:
            if any(candidate["start"] < item["end"] and candidate["end"] > item["start"] for item in selected):
                continue
            selected.append(candidate)
            if len(selected) >= target_count:
                break
    for candidate in selected:
        candidate.pop("_score", None)
    elapsed_seconds = round(time.monotonic() - started_at, 2)
    status = "success" if not failures else ("partial" if reviewed else "degraded")
    _logger.info(
        "高光视觉审核结束 job_id=%s status=%s reviewed=%s selected=%s elapsed_seconds=%.1f",
        (job or {}).get("id") or "", status, len(reviewed), len(selected), elapsed_seconds,
    )
    return selected, {
        "status": status,
        "candidateCount": len(candidates),
        "reviewedCount": len(reviewed),
        "failureCount": len(failures),
        "failures": failures,
        "elapsedSeconds": elapsed_seconds,
        "timeoutSeconds": total_timeout_seconds,
        "timedOut": timed_out,
    }
