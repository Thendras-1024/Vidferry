"""原视频字幕烧制与遮罩决策。"""

from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import (
    LLM_TIMEOUT,
    MULTIMODAL_LLM_API_KEY,
    MULTIMODAL_LLM_BASE_URL,
    MULTIMODAL_LLM_MODEL,
    get_llm_config_status,
)
from app.core.llm_harness import call_json_contract
from app.utils.ffmpeg_util import _resolve_ffmpeg_command


SOURCE_SUBTITLE_ANALYSIS_VERSION = 3
SOURCE_SUBTITLE_SAMPLE_COUNT = 12
SOURCE_SUBTITLE_FRAME_WIDTH = 960
SOURCE_SUBTITLE_FIRST_MAX_TOKENS = 3000
SOURCE_SUBTITLE_RETRY_MAX_TOKENS = 6000

_logger = logging.getLogger("vidferry.backend")


def _source_subtitle_timestamps(duration, count=SOURCE_SUBTITLE_SAMPLE_COUNT):
    duration = max(0.1, float(duration or 0.1))
    count = max(2, min(SOURCE_SUBTITLE_SAMPLE_COUNT, int(count or SOURCE_SUBTITLE_SAMPLE_COUNT)))
    start, end = duration * 0.05, duration * 0.95
    step = (end - start) / (count - 1)
    return [round(start + step * index, 2) for index in range(count)]


def _extract_source_subtitle_frames(video_path, timestamps):
    ffmpeg = _resolve_ffmpeg_command()
    frames = []
    with tempfile.TemporaryDirectory(prefix="vidferry-source-subtitles-") as tmp_dir:
        tmp_dir = Path(tmp_dir)
        for index, timestamp in enumerate(timestamps, start=1):
            frame_path = tmp_dir / f"frame_{index}.jpg"
            command = [
                ffmpeg, "-y", "-ss", f"{timestamp:.2f}", "-i", str(video_path),
                "-frames:v", "1", "-vf", f"scale='min({SOURCE_SUBTITLE_FRAME_WIDTH},iw)':-2", str(frame_path),
            ]
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if frame_path.is_file():
                frames.append({
                    "frameIndex": index,
                    "timestampSeconds": timestamp,
                    "dataUrl": "data:image/jpeg;base64," + base64.b64encode(frame_path.read_bytes()).decode("ascii"),
                })
    if len(frames) < 2:
        raise RuntimeError("原视频字幕识别未能抽取至少两帧")
    return frames


def validate_source_subtitle_result(value, _frame_count=None):
    if not isinstance(value, dict) or set(value) != {"classification", "reason"}:
        raise ValueError("原视频字幕决策返回字段不合法")
    classification = str(value.get("classification") or "").strip()
    if classification not in {"zh", "non_zh", "none"}:
        raise ValueError("classification 必须是 zh、non_zh 或 none")
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason 不能为空")
    return {
        "classification": classification,
        "reason": reason[:500],
    }


def resolve_source_subtitle_decision(mode, classification="unknown", requested_mask=False):
    mode = str(mode or "legacy").strip()
    classification = str(classification or "unknown").strip()
    if mode == "legacy":
        return None
    if mode == "original":
        return {"translationEnabled": False, "subtitleMaskEnabled": False, "effectiveAction": "original"}
    if mode == "force_burn":
        mask = bool(requested_mask)
        return {
            "translationEnabled": True,
            "subtitleMaskEnabled": mask,
            "effectiveAction": "mask_and_burn" if mask else "burn",
        }
    if classification == "zh":
        return {"translationEnabled": False, "subtitleMaskEnabled": False, "effectiveAction": "original_zh"}
    if classification == "none":
        return {"translationEnabled": True, "subtitleMaskEnabled": False, "effectiveAction": "burn"}
    if classification == "non_zh":
        return {"translationEnabled": True, "subtitleMaskEnabled": True, "effectiveAction": "mask_and_burn"}
    return {
        "translationEnabled": True,
        "subtitleMaskEnabled": True,
        "effectiveAction": "mask_and_burn",
    }


def _source_subtitle_analysis(
    mode,
    classification,
    reason,
    status,
    elapsed_seconds=0,
    requested_mask=False,
    fallback_translation_enabled=None,
):
    decision = resolve_source_subtitle_decision(
        mode,
        classification=classification,
        requested_mask=requested_mask,
    )
    burn_subtitles = bool((decision or {}).get("translationEnabled"))
    subtitle_mask_enabled = bool((decision or {}).get("subtitleMaskEnabled"))
    if decision is None and fallback_translation_enabled is not None:
        burn_subtitles = bool(fallback_translation_enabled)
        subtitle_mask_enabled = bool(requested_mask and burn_subtitles)
    return {
        "analysisVersion": SOURCE_SUBTITLE_ANALYSIS_VERSION,
        "status": status,
        "classification": classification,
        "burnSubtitles": burn_subtitles,
        "subtitleMaskEnabled": subtitle_mask_enabled,
        "reason": str(reason or "")[:500],
        "decision": decision,
        "elapsedSeconds": round(float(elapsed_seconds or 0), 2),
    }


def _source_subtitle_system_prompt():
    return (
        "你是视频原字幕识别器。只识别承担对白作用、位置稳定且随时间变化的字幕；"
        "忽略水印、招牌、弹幕、标题和界面文字。只返回 JSON，不要返回 Markdown。"
    )


def _source_subtitle_user_prompt(frame_count):
    return (
        f"分析以下按时间排序的 {frame_count} 帧。返回 classification(zh/non_zh/none) 和 reason。"
        "中文对白字幕返回 zh；存在非中文对白字幕时返回 non_zh；没有原视频对白字幕时返回 none。"
    )


def _source_subtitle_messages(frames, retry_reason=""):
    prompt = _source_subtitle_user_prompt(len(frames))
    if retry_reason:
        prompt += (
            " 上一次检查失败，失败原因如下；请重新检查全部视频帧并只返回合法 JSON："
            f" {str(retry_reason)[:500]}"
        )
    content = [{"type": "text", "text": prompt}]
    for frame in frames:
        content.append({"type": "text", "text": f"frameIndex={frame['frameIndex']}, timestamp={frame['timestampSeconds']:.2f}s"})
        content.append({"type": "image_url", "image_url": {"url": frame["dataUrl"]}})
    return [
        {"role": "system", "content": _source_subtitle_system_prompt()},
        {"role": "user", "content": content},
    ]


def _run_source_subtitle_attempt(job, video_path, duration, telemetry, max_tokens, retry_reason=""):
    frames = _extract_source_subtitle_frames(video_path, _source_subtitle_timestamps(duration))
    result, usage, _ = call_json_contract(
        messages=_source_subtitle_messages(frames, retry_reason),
        contract_id="source_subtitle_analysis",
        validator=validate_source_subtitle_result,
        model=MULTIMODAL_LLM_MODEL,
        api_key=MULTIMODAL_LLM_API_KEY,
        base_url=MULTIMODAL_LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=0.1,
        max_tokens=max_tokens,
        max_attempts=1,
        prompt_version="source-subtitle-v3",
        telemetry=telemetry,
        profile_channel="multimodal",
    )
    return result, usage


def analyze_source_subtitles(job, video_path, duration, telemetry=None):
    mode = str((job or {}).get("subtitleMode") or "legacy")
    requested_mask = bool((job or {}).get("subtitleMaskEnabled"))
    if mode != "auto":
        return _source_subtitle_analysis(
            mode,
            "unknown",
            "当前字幕模式无需执行 LLM 判断",
            "skipped",
            requested_mask=requested_mask,
            fallback_translation_enabled=(job or {}).get("translationEnabled", True),
        ), {}

    started_at = time.monotonic()
    multimodal = (get_llm_config_status() or {}).get("multimodal") or {}
    if not (MULTIMODAL_LLM_API_KEY and MULTIMODAL_LLM_BASE_URL and MULTIMODAL_LLM_MODEL):
        reason = "未配置多模态模型"
        _logger.warning("原视频字幕判断不可用 : job_id = %s reason = %s", (job or {}).get("id") or "", reason)
        return _source_subtitle_analysis(mode, "unknown", reason, "degraded", time.monotonic() - started_at), {}
    if not multimodal.get("ready") or not multimodal.get("visionReady"):
        reason = multimodal.get("message") or "多模态模型不支持图片输入"
        _logger.warning("原视频字幕判断不可用 : job_id = %s reason = %s", (job or {}).get("id") or "", reason)
        return _source_subtitle_analysis(mode, "unknown", reason, "degraded", time.monotonic() - started_at), {}
    try:
        result, usage = _run_source_subtitle_attempt(
            job, video_path, duration, telemetry, SOURCE_SUBTITLE_FIRST_MAX_TOKENS,
        )
        return _source_subtitle_analysis(
            mode,
            result["classification"],
            result["reason"],
            "success",
            time.monotonic() - started_at,
        ), usage
    except Exception as first_exc:
        first_reason = f"{first_exc.__class__.__name__}: {str(first_exc)[:500]}"
        _logger.warning(
            "原视频字幕首次判断失败 : job_id = %s reason = %s",
            (job or {}).get("id") or "", first_reason,
        )
        try:
            result, usage = _run_source_subtitle_attempt(
                job,
                video_path,
                duration,
                telemetry,
                SOURCE_SUBTITLE_RETRY_MAX_TOKENS,
                retry_reason=first_reason,
            )
            return _source_subtitle_analysis(
                mode,
                result["classification"],
                result["reason"],
                "success",
                time.monotonic() - started_at,
            ), usage
        except Exception as retry_exc:
            reason = f"首次检查失败 : {first_reason}；二次检查失败 : {retry_exc.__class__.__name__}: {str(retry_exc)[:300]}"
            _logger.warning(
                "原视频字幕二次判断失败 : job_id = %s reason = %s",
                (job or {}).get("id") or "", reason,
            )
        return _source_subtitle_analysis(
            mode,
            "unknown",
            reason,
            "degraded",
            time.monotonic() - started_at,
        ), {}
