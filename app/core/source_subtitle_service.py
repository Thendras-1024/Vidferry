"""原视频字幕的多模态识别与处理决策。"""

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


SOURCE_SUBTITLE_SAMPLE_COUNT = 12
SOURCE_SUBTITLE_FRAME_WIDTH = 960
SOURCE_SUBTITLE_MIN_CONFIDENCE = 0.75
SOURCE_SUBTITLE_FALLBACK_REGION = {"x": 0.06, "y": 0.84, "width": 0.88, "height": 0.155}

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


def _validate_normalized_bbox(value, path):
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise ValueError(f"{path} 字段不合法")
    bbox = {}
    for key in ("x", "y", "width", "height"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError(f"{path}.{key} 必须是数值")
        bbox[key] = float(number)
    if bbox["width"] <= 0 or bbox["height"] <= 0 or bbox["x"] < 0 or bbox["y"] < 0:
        raise ValueError(f"{path} 超出归一化坐标范围")
    if bbox["x"] + bbox["width"] > 1 or bbox["y"] + bbox["height"] > 1:
        raise ValueError(f"{path} 超出归一化坐标范围")
    return {key: round(value, 4) for key, value in bbox.items()}


def validate_source_subtitle_result(value, frame_count):
    if not isinstance(value, dict) or set(value) != {"classification", "confidence", "evidenceFrames", "reason"}:
        raise ValueError("原视频字幕识别返回字段不合法")
    classification = str(value.get("classification") or "").strip()
    if classification not in {"zh", "non_zh", "none"}:
        raise ValueError("classification 必须是 zh、non_zh 或 none")
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence 必须在 0 到 1 之间")
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason 不能为空")
    raw_evidence = value.get("evidenceFrames")
    if not isinstance(raw_evidence, list):
        raise ValueError("evidenceFrames 必须是数组")
    evidence = []
    seen = set()
    for position, item in enumerate(raw_evidence):
        if not isinstance(item, dict) or set(item) != {"frameIndex", "language", "bbox"}:
            raise ValueError(f"evidenceFrames[{position}] 字段不合法")
        frame_index = item.get("frameIndex")
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or not 1 <= frame_index <= frame_count:
            raise ValueError(f"evidenceFrames[{position}].frameIndex 不合法")
        if frame_index in seen:
            raise ValueError("evidenceFrames 的 frameIndex 不得重复")
        seen.add(frame_index)
        language = str(item.get("language") or "").strip()
        if language not in {"zh", "non_zh", "mixed", "none"}:
            raise ValueError(f"evidenceFrames[{position}].language 不合法")
        bbox = item.get("bbox")
        if classification == "none":
            if language != "none" or bbox is not None:
                raise ValueError("none 分类的证据帧必须使用 language=none 且 bbox=null")
        else:
            bbox = _validate_normalized_bbox(bbox, f"evidenceFrames[{position}].bbox")
        evidence.append({"frameIndex": frame_index, "language": language, "bbox": bbox})
    return {
        "classification": classification,
        "confidence": round(float(confidence), 4),
        "evidenceFrames": evidence,
        "reason": reason[:500],
    }


def _source_subtitle_region(evidence_frames):
    boxes = [
        item["bbox"]
        for item in evidence_frames or []
        if isinstance(item.get("bbox"), dict)
        and item["bbox"]["y"] + item["bbox"]["height"] / 2 >= 0.55
        and item["bbox"]["width"] <= 0.88
    ]
    if len(boxes) < 2:
        return None
    # ponytail: 仅支持底部对白字幕；非底部字幕需要 OCR 跟踪后再扩展。
    top = max(0.0, min(item["y"] for item in boxes) - 0.01)
    bottom = 0.995
    return {
        "x": SOURCE_SUBTITLE_FALLBACK_REGION["x"],
        "y": round(top, 4),
        "width": SOURCE_SUBTITLE_FALLBACK_REGION["width"],
        "height": round(bottom - top, 4),
    }


def resolve_source_subtitle_decision(mode, classification, requested_mask=False):
    mode = str(mode or "legacy").strip()
    classification = str(classification or "unknown").strip()
    if mode == "legacy":
        return None
    if mode == "original":
        return {"translationEnabled": False, "subtitleMaskEnabled": False, "effectiveAction": "original"}
    if mode == "force_burn":
        mask = bool(requested_mask and classification != "none")
        return {
            "translationEnabled": True,
            "subtitleMaskEnabled": mask,
            "effectiveAction": "mask_and_burn" if mask else "burn",
        }
    if classification == "zh":
        return {"translationEnabled": False, "subtitleMaskEnabled": False, "effectiveAction": "original_zh"}
    if classification == "none":
        return {"translationEnabled": True, "subtitleMaskEnabled": False, "effectiveAction": "burn"}
    return {"translationEnabled": True, "subtitleMaskEnabled": True, "effectiveAction": "mask_and_burn"}


def _source_subtitle_system_prompt():
    return (
        "你是视频原字幕检测器。只识别承担对白字幕作用、位置稳定且随时间变化的文字；"
        "排除招牌、水印、弹幕、标题、界面文字和偶然出现的中文。"
        "中文和外语双语字幕归类为 zh。坐标使用 0 到 1 的归一化值。"
        "只返回 JSON，不要返回 Markdown。"
    )


def _source_subtitle_user_prompt(frame_count):
    return (
        f"分析以下按时间排序的 {frame_count} 帧。返回 classification(zh/non_zh/none)、confidence(0-1)、"
        "reason、evidenceFrames。每个证据项严格包含 frameIndex、language(zh/non_zh/mixed/none)、bbox。"
        "有字幕时 bbox={x,y,width,height}，无字幕时 bbox=null。至少给出两帧相互一致的证据。"
    )


def analyze_source_subtitles(job, video_path, duration, telemetry=None):
    mode = str((job or {}).get("subtitleMode") or "legacy")
    requested_mask = bool((job or {}).get("subtitleMaskEnabled"))
    if mode in {"legacy", "original"} or (mode == "force_burn" and not requested_mask):
        classification = "unknown"
        decision = resolve_source_subtitle_decision(mode, classification, requested_mask)
        return {
            "status": "skipped",
            "classification": classification,
            "confidence": 0,
            "evidenceFrames": [],
            "region": None,
            "reason": "当前字幕模式无需执行原字幕识别",
            "decision": decision,
        }, {}

    started_at = time.monotonic()
    try:
        multimodal = (get_llm_config_status() or {}).get("multimodal") or {}
        if not (MULTIMODAL_LLM_API_KEY and MULTIMODAL_LLM_BASE_URL and MULTIMODAL_LLM_MODEL):
            raise RuntimeError("未配置多模态模型")
        if not multimodal.get("ready") or not multimodal.get("visionReady"):
            raise RuntimeError(multimodal.get("message") or "多模态模型不支持图片输入")
        frames = _extract_source_subtitle_frames(video_path, _source_subtitle_timestamps(duration))
        content = [{"type": "text", "text": _source_subtitle_user_prompt(len(frames))}]
        for frame in frames:
            content.append({"type": "text", "text": f"frameIndex={frame['frameIndex']}, timestamp={frame['timestampSeconds']:.2f}s"})
            content.append({"type": "image_url", "image_url": {"url": frame["dataUrl"]}})
        result, usage, _ = call_json_contract(
            messages=[
                {"role": "system", "content": _source_subtitle_system_prompt()},
                {"role": "user", "content": content},
            ],
            contract_id="source_subtitle_analysis",
            validator=lambda value: validate_source_subtitle_result(value, len(frames)),
            model=MULTIMODAL_LLM_MODEL,
            api_key=MULTIMODAL_LLM_API_KEY,
            base_url=MULTIMODAL_LLM_BASE_URL,
            timeout=LLM_TIMEOUT,
            temperature=0.1,
            max_tokens=1400,
            prompt_version="source-subtitle-v1",
            telemetry=telemetry,
        )
        matching_languages = {
            "zh": {"zh", "mixed"},
            "non_zh": {"non_zh"},
            "none": {"none"},
        }[result["classification"]]
        consistent_frames = [
            item for item in result["evidenceFrames"] if item.get("language") in matching_languages
        ]
        accepted = result["confidence"] >= SOURCE_SUBTITLE_MIN_CONFIDENCE and len(consistent_frames) >= 2
        classification = result["classification"] if accepted else "unknown"
        region = _source_subtitle_region(consistent_frames) if accepted and classification != "none" else None
        decision = resolve_source_subtitle_decision(mode, classification, requested_mask)
        if decision and decision["subtitleMaskEnabled"] and not region:
            region = dict(SOURCE_SUBTITLE_FALLBACK_REGION)
        return {
            "status": "success" if accepted else "unknown",
            "classification": classification,
            "confidence": result["confidence"],
            "evidenceFrames": result["evidenceFrames"],
            "region": region,
            "reason": result["reason"] if accepted else "识别结果未达到双帧一致或置信度阈值",
            "decision": decision,
            "elapsedSeconds": round(time.monotonic() - started_at, 2),
        }, usage
    except Exception as exc:
        _logger.warning("原视频字幕识别降级 job_id=%s", (job or {}).get("id") or "", exc_info=True)
        classification = "unknown"
        decision = resolve_source_subtitle_decision(mode, classification, requested_mask)
        return {
            "status": "unknown",
            "classification": classification,
            "confidence": 0,
            "evidenceFrames": [],
            "region": dict(SOURCE_SUBTITLE_FALLBACK_REGION) if decision and decision["subtitleMaskEnabled"] else None,
            "reason": f"{exc.__class__.__name__}: {str(exc)[:300]}",
            "decision": decision,
            "elapsedSeconds": round(time.monotonic() - started_at, 2),
        }, {}
