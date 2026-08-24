"""真实评测与离线回放运行器。"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import statistics
import time
import wave
from collections import defaultdict
from pathlib import Path

from .io import PROJECT_ROOT, append_jsonl, existing_success_keys, load_jsonl, write_json
from .metrics import grade_agent_case, score_asr_case, score_translation_case, translation_completion


_ERROR_SECRET = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
_ERROR_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\s\"'，。；;]+")


def _safe_error(exc):
    detail = " ".join(str(exc).split())[:300]
    detail = _ERROR_SECRET.sub("[已隐藏敏感凭证]", detail)
    detail = _ERROR_PATH.sub("[已隐藏本机路径]", detail)
    return {"type": exc.__class__.__name__, "message": detail}


def _audio_duration(path):
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / float(source.getframerate() or 1)


def _faster_whisper_asr(case):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper 基线依赖，请安装 evaluation/requirements-whisper.txt。") from exc
    media = PROJECT_ROOT / case["media"]
    model_name = os.environ.get("WHISPER_MODEL_SIZE", "small")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    started = time.perf_counter()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    raw_segments, info = model.transcribe(str(media), beam_size=5, vad_filter=True, word_timestamps=True)
    segments = []
    for segment in raw_segments:
        words = []
        for word in list(getattr(segment, "words", None) or []):
            text = str(getattr(word, "word", "") or "").strip()
            start, end = float(word.start), float(word.end)
            if text and start >= 0 and end > start:
                words.append({"word": text, "start": start, "end": end})
        text = str(segment.text or "").strip()
        if text:
            segments.append({"text": text, "start": float(segment.start), "end": float(segment.end), "words": words})
    return {
        "segments": segments,
        "language": str(getattr(info, "language", "") or ""),
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
        "audioDurationSeconds": _audio_duration(media),
        "peakVramBytes": None,
        "model": f"faster-whisper:{model_name}:{device}:{compute_type}",
        "rtfIncludesModelLoad": True,
    }


def run_asr_case(case, system):
    if system == "replay":
        return dict(case.get("replayOutput") or {})
    if system == "faster-whisper":
        return _faster_whisper_asr(case)
    raise ValueError(f"不支持的 ASR system : {system}")


def _backend():
    from app.backend.runtime import create_backend_module

    return create_backend_module(f"vidferry_eval_{time.time_ns()}")


def _translation_context(case, initial_translation):
    items = []
    for item in case.get("previous") or []:
        items.append({"text": item.get("source") or "", "subtitle": item.get("initialTranslation") or ""})
    target_index = len(items)
    items.append({"text": case.get("source") or "", "subtitle": initial_translation})
    for item in case.get("following") or []:
        items.append({"text": item.get("source") or "", "subtitle": item.get("initialTranslation") or ""})
    return items, target_index


def _google_translation(case, backend):
    result = backend._translate_segments(
        [{"text": case["source"]}], "zh-CN", source_language=case["language"],
    )
    return str(result[0].get("subtitle") or "")


def _review_translation(case, backend, initial_translation):
    segments, target_index = _translation_context(case, initial_translation)
    if any(not str(item.get("subtitle") or "").strip() for item in segments):
        raise ValueError("LLM 修订上下文必须提供 initialTranslation")
    metadata = {}
    reviewed = backend.review_translated_segments(
        segments,
        "zh-CN",
        job={"title": case.get("videoTitle") or "", "channel": case.get("channel") or ""},
        source_language=case["language"],
        review_metadata=metadata,
    )
    return str(reviewed[target_index].get("subtitle") or ""), metadata


def run_translation_case(case, system):
    if system == "replay":
        value = case.get("replayOutput") or {}
        return dict(value) if isinstance(value, dict) else {"translation": value, "stage": "replay"}
    started = time.perf_counter()
    backend = _backend()
    metadata = {}
    stage_durations = {}
    if system == "google":
        stage_started = time.perf_counter()
        initial = translation = _google_translation(case, backend)
        stage_durations["google"] = round((time.perf_counter() - stage_started) * 1000, 2)
    elif system == "review":
        initial = str(case.get("initialTranslation") or "")
        stage_started = time.perf_counter()
        translation, metadata = _review_translation(case, backend, initial)
        stage_durations["review"] = round((time.perf_counter() - stage_started) * 1000, 2)
    elif system == "google-review":
        stage_started = time.perf_counter()
        initial = _google_translation(case, backend)
        stage_durations["google"] = round((time.perf_counter() - stage_started) * 1000, 2)
        stage_started = time.perf_counter()
        translation, metadata = _review_translation(case, backend, initial)
        stage_durations["review"] = round((time.perf_counter() - stage_started) * 1000, 2)
    else:
        raise ValueError(f"不支持的 translation system : {system}")
    return {
        "translation": translation,
        "initialTranslation": initial,
        "review": metadata,
        "stage": system,
        "stageDurationsMs": stage_durations,
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
    }


def _merge_state(target, patch):
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_state(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _frozen_tool_runner(frozen_tools, calls, environment_state):
    def run(name, args, session_id=""):
        calls.append({"tool": name, "args": dict(args or {})})
        if name not in frozen_tools:
            raise RuntimeError(f"AGENT_EVAL_UNEXPECTED_TOOL:{name}")
        value = frozen_tools[name]
        if isinstance(value, dict) and value.get("__error__"):
            raise RuntimeError(str(value["__error__"]))
        if isinstance(value, dict) and "__statePatch__" in value:
            _merge_state(environment_state, value.get("__statePatch__") or {})
            return copy.deepcopy(value.get("__result__"))
        return value

    return run


def _agent_intent(state, prepared):
    for key in ("intent", "recognized_intent", "route"):
        value = state.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("intent")
        if str(value or "").strip():
            return str(value).strip()
    safety = state.get("safety_decision") or {}
    if safety.get("allowed") is False:
        return "clarification" if safety.get("category") == "needs_clarification" else "safety"
    if prepared or state.get("copywriting_proposal"):
        return "proposal"
    return "query"


def run_agent_case(case, system):
    if system == "replay":
        return dict(case.get("replayOutput") or {})
    if system != "agent":
        raise ValueError(f"不支持的 agent system : {system}")
    started = time.perf_counter()
    backend = _backend()
    if case.get("requiresModel", True) and not backend._agent_llm_available():
        raise RuntimeError("Agent 模型配置不完整，无法运行 requiresModel 案例。")
    calls = []
    original_tool = backend._run_agent_tool
    original_selection = backend.get_agent_video_selection
    original_renewer = getattr(backend, "renew_agent_session_lease", None)
    usage_token = backend._AGENT_REQUEST_USAGE.set([])
    state_before = copy.deepcopy(case.get("initialState") or {})
    state_after = copy.deepcopy(state_before)
    try:
        backend._run_agent_tool = _frozen_tool_runner(case.get("frozenTools") or {}, calls, state_after)
        backend.get_agent_video_selection = lambda _session_id: list(case.get("selectedVideoIds") or [])
        backend.renew_agent_session_lease = lambda _session_id: True
        state = backend._node_policy_check({
            "session_id": f"eval-{case['id']}",
            "message": case["message"],
            "context": dict(case.get("context") or {}),
        })
        state = backend._node_react_loop(state)
        tool_results = list(state.get("tool_results") or [])
        prepared = next((item.get("result") for item in tool_results if item.get("tool") == "prepare_video_action"), None)
        intent = _agent_intent(state, prepared)
        skills = [str(item.get("args", {}).get("name") or "") for item in calls if item.get("tool") == "load_skill"]
        output = {
            "answer": str(state.get("answer") or ""),
            "toolCalls": calls,
            "toolResults": tool_results,
            "safetyDecision": state.get("safety_decision") or {},
            "executionProposal": prepared,
            "copywritingProposal": state.get("copywriting_proposal"),
            "importProposal": None,
            "intent": intent,
            "skills": [name for name in skills if name],
            "processTrace": ["policy_check", f"intent:{intent}", *[f"tool:{item['tool']}" for item in calls], "answer"],
            "stateBefore": state_before,
            "stateAfter": state_after,
            "iterations": int(state.get("iterations") or 0),
            "usage": backend._agent_usage_summary(backend._AGENT_REQUEST_USAGE.get() or []),
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
        }
        return output
    finally:
        backend._run_agent_tool = original_tool
        backend.get_agent_video_selection = original_selection
        if original_renewer is not None:
            backend.renew_agent_session_lease = original_renewer
        backend._AGENT_REQUEST_USAGE.reset(usage_token)


def system_metadata(suite, system):
    if suite == "asr" and system == "faster-whisper":
        return {
            "model": os.environ.get("WHISPER_MODEL_SIZE", "small"),
            "device": os.environ.get("WHISPER_DEVICE", "cpu"),
            "computeType": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        }
    if suite in {"translation", "agent"} and system != "replay":
        from app import config
        from app.core import llm_prompts

        return {
            "model": config.AGENT_LLM_MODEL if suite == "agent" else config.TEXT_LLM_MODEL,
            "promptVersion": llm_prompts.AGENT_PROMPT_VERSION if suite == "agent" else llm_prompts.SUBTITLE_REVIEW_PROMPT_VERSION,
        }
    return {"model": system}


def _duration_summary(rows, field):
    values = []
    for row in rows:
        value = row.get("wallDurationMs") if field == "wallDurationMs" else (row.get("output") or {}).get("durationMs")
        if value is not None:
            values.append(float(value))
    ordered = sorted(values)
    return {
        "count": len(values),
        "total": sum(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)] if ordered else None,
    }


def _performance(rows, all_rows):
    stage_names = sorted({name for row in rows for name in ((row.get("output") or {}).get("stageDurationsMs") or {})})
    return {
        "processingTimeMs": _duration_summary(rows, "durationMs"),
        "wallTimeMs": _duration_summary(all_rows, "wallDurationMs"),
        "stageTimeMs": {
            name: {
                "count": len(values),
                "mean": statistics.fmean(values),
                "p95": sorted(values)[min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)],
            }
            for name in stage_names
            if (values := [float((row.get("output") or {}).get("stageDurationsMs", {}).get(name)) for row in rows if (row.get("output") or {}).get("stageDurationsMs", {}).get(name) is not None])
        },
        "executionSuccessRate": len(rows) / len(all_rows) if all_rows else None,
    }


def _aggregate_asr(rows, all_rows):
    by_language = {}
    for language in sorted({row["language"] for row in rows}):
        selected = [row for row in rows if row["language"] == language]
        reference_units = sum(row["metrics"]["referenceUnits"] for row in selected)
        entity_total = sum(row["metrics"]["entity"]["total"] for row in selected)
        by_language[language] = {
            "cases": len(selected),
            "metric": "wer" if language == "en" else "cer",
            "errorRate": sum(row["metrics"]["distance"] for row in selected) / max(1, reference_units),
            "entityRecall": sum(row["metrics"]["entity"]["matched"] for row in selected) / entity_total if entity_total else 1.0,
        }
    timing = [row["metrics"]["timing"]["p95Seconds"] for row in rows if row["metrics"]["timing"]["p95Seconds"] is not None]
    return {
        **_performance(rows, all_rows),
        "macroErrorRate": statistics.fmean(item["errorRate"] for item in by_language.values()) if by_language else None,
        "macroEntityRecall": statistics.fmean(item["entityRecall"] for item in by_language.values()) if by_language else None,
        "termRecallByType": _aggregate_term_types(rows),
        "timingP95MeanSeconds": statistics.fmean(timing) if timing else None,
        "averageRtf": statistics.fmean(row["metrics"]["rtf"] for row in rows if row["metrics"]["rtf"] is not None) if any(row["metrics"]["rtf"] is not None for row in rows) else None,
        "languages": by_language,
    }


def _aggregate_translation(rows, all_rows):
    entity_total = sum(row["metrics"]["entity"]["total"] for row in rows)
    full = [row for row in rows if row["metrics"].get("completionStatus") == "full_success"]
    degraded = [row for row in rows if row["metrics"].get("completionStatus") == "degraded"]
    failed_count = len(all_rows) - len(full) - len(degraded)
    total = len(all_rows)
    return {
        **_performance(rows, all_rows),
        "meanChrf": statistics.fmean(row["metrics"]["chrf"] for row in rows) if rows else None,
        "meanInitialChrf": _mean_metric_value(rows, "initialChrf"),
        "meanReviewChrfDelta": _mean_metric_value(rows, "reviewChrfDelta"),
        "fullSuccessMeanChrf": statistics.fmean(row["metrics"]["chrf"] for row in full) if full else None,
        "degradedMeanChrf": statistics.fmean(row["metrics"]["chrf"] for row in degraded) if degraded else None,
        "entityRecall": sum(row["metrics"]["entity"]["matched"] for row in rows) / entity_total if entity_total else 1.0,
        "termRecallByType": _aggregate_term_types(rows),
        "emptyCount": sum(row["metrics"]["empty"] for row in rows),
        "unchangedCount": sum(row["metrics"]["unchanged"] for row in rows),
        "overLengthCount": sum(row["metrics"]["overLength"] for row in rows),
        "fullSuccessCount": len(full),
        "degradedCount": len(degraded),
        "failedCount": failed_count,
        "usableSuccessRate": (len(full) + len(degraded)) / total if total else None,
        "fullSuccessRate": len(full) / total if total else None,
        "degradationRate": len(degraded) / total if total else None,
        "failureRate": failed_count / total if total else None,
    }


def _aggregate_term_types(rows):
    totals = defaultdict(lambda: {"matched": 0, "total": 0})
    for row in rows:
        for term_type, values in row["metrics"]["entity"].get("byType", {}).items():
            totals[term_type]["matched"] += int(values.get("matched") or 0)
            totals[term_type]["total"] += int(values.get("total") or 0)
    return {
        term_type: {**values, "recall": values["matched"] / values["total"] if values["total"] else 1.0}
        for term_type, values in sorted(totals.items())
    }


def _mean_metric_value(rows, name):
    values = [row["metrics"].get(name) for row in rows if row["metrics"].get(name) is not None]
    return statistics.fmean(values) if values else None


def _aggregate_agent(rows, all_rows):
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["id"]].append(bool(row["metrics"]["passed"]))
    tool_results = [item for row in rows for item in row.get("output", {}).get("toolResults", [])]
    tool_errors = sum(bool(item.get("error")) for item in tool_results)
    return {
        **_performance(rows, all_rows),
        "trialSuccessRate": sum(row["metrics"]["passed"] for row in rows) / len(rows) if rows else None,
        "allTrialsSuccessRate": sum(all(values) for values in by_case.values()) / len(by_case) if by_case else None,
        "toolErrorCount": tool_errors,
        "toolCallCount": len(tool_results),
        "toolErrorRate": tool_errors / len(tool_results) if tool_results else 0.0,
        "intentAccuracy": _mean_metric_value(rows, "intentCorrect"),
        "toolPrecision": _mean_metric_value(rows, "toolPrecision"),
        "toolRecall": _mean_metric_value(rows, "toolRecall"),
        "toolF1": _mean_metric_value(rows, "toolF1"),
        "skillPrecision": _mean_metric_value(rows, "skillPrecision"),
        "skillRecall": _mean_metric_value(rows, "skillRecall"),
        "processSuccessRate": _mean_metric_value(rows, "processCorrect"),
        "taskCompletionRate": _mean_metric_value(rows, "taskCompleted"),
        "stateChangeRate": _mean_metric_value(rows, "stateChanged"),
        "averageIterations": statistics.fmean(row.get("output", {}).get("iterations", 0) for row in rows) if rows else 0,
        "totalTokens": sum(int(row.get("output", {}).get("usage", {}).get("totalTokens") or 0) for row in rows),
    }


def summarize(raw_path, metadata):
    latest = {}
    for row in load_jsonl(raw_path):
        latest[(row.get("id"), int(row.get("trial") or 1))] = row
    rows = list(latest.values())
    succeeded = [row for row in rows if row.get("status") == "success"]
    suite = metadata["suite"]
    aggregate = _aggregate_asr(succeeded, rows) if suite == "asr" else _aggregate_translation(succeeded, rows) if suite == "translation" else _aggregate_agent(succeeded, rows)
    return {
        **metadata,
        "complete": len(succeeded) == len(rows) and bool(rows),
        "sampleSize": len(rows),
        "succeeded": len(succeeded),
        "failed": len(rows) - len(succeeded),
        "metrics": aggregate,
    }


def run_evaluation(cases, *, suite, system, trials, run_dir, metadata, resume=False):
    raw_path = Path(run_dir) / "raw.jsonl"
    completed = existing_success_keys(raw_path) if resume else set()
    run_case = run_asr_case if suite == "asr" else run_translation_case if suite == "translation" else run_agent_case
    trial_count = max(1, trials if suite == "agent" else 1)
    for case in cases:
        for trial in range(1, trial_count + 1):
            key = (case["id"], trial)
            if key in completed:
                print(f"eval case skipped : suite = {suite} | case_id = {case['id']} | trial = {trial}", flush=True)
                continue
            print(f"eval case started : suite = {suite} | case_id = {case['id']} | trial = {trial}", flush=True)
            started = time.perf_counter()
            row = {"id": case["id"], "trial": trial, "suite": suite, "language": case["language"], "tags": list(case.get("tags") or [])}
            try:
                output = run_case(case, system)
                output.setdefault("durationMs", round((time.perf_counter() - started) * 1000, 2))
                metrics = score_asr_case(case, output) if suite == "asr" else score_translation_case(case, output) if suite == "translation" else grade_agent_case(case, output)
                if suite == "translation":
                    output["completionStatus"] = translation_completion(output)
                    if output["completionStatus"] == "degraded":
                        review = output.get("review") or {}
                        output["degradationReason"] = str(review.get("status") or "fallback")
                row.update({"status": "success", "input": _safe_input(case, suite), "output": output, "metrics": metrics})
                print(f"eval case completed : suite = {suite} | case_id = {case['id']} | trial = {trial}", flush=True)
            except Exception as exc:
                row.update({"status": "error", "input": _safe_input(case, suite), "error": _safe_error(exc)})
                print(f"eval case failed : suite = {suite} | case_id = {case['id']} | trial = {trial} | error_type = {exc.__class__.__name__}", flush=True)
            row["wallDurationMs"] = round((time.perf_counter() - started) * 1000, 2)
            append_jsonl(raw_path, row)
    summary = summarize(raw_path, {**metadata, "systemConfig": system_metadata(suite, system)})
    write_json(Path(run_dir) / "summary.json", summary)
    return summary


def _safe_input(case, suite):
    if suite == "asr":
        return {key: case.get(key) for key in ("media", "reference", "entities", "timings")}
    if suite == "translation":
        return {key: case.get(key) for key in ("source", "references", "previous", "following", "entities")}
    return {key: case.get(key) for key in ("message", "context", "initialState", "expected")}
