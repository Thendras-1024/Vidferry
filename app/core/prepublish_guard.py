"""发布前质检守卫:文本与关键帧风险检测、严重度决策与拦截/人工确认。"""


from __future__ import annotations

import base64 as _base64
import hashlib as _hashlib
import json as _json
import tempfile as _tempfile
import time as _time

from app.core.llm_harness import call_json_contract, validate_guard_result
from app.core import llm_prompts
from app.core.errors import AgentGuardError


AGENT_ERROR_BLOCKED = "VF-AGENT-BLOCKED"
AGENT_ERROR_REQUIRES_CONFIRMATION = "VF-AGENT-REQUIRES-CONFIRMATION"


def _agent_guard_summary(data, file_list=None, targets=None):
    return {
        "title": str((data or {}).get("title") or "").strip(),
        "description": str((data or {}).get("description") or "").strip(),
        "tags": _normalize_publish_tags((data or {}).get("tags")),
        "fileList": [str(item or "") for item in (file_list or (data or {}).get("fileList") or [])],
        "targets": [
            {
                "platformType": int(item.get("platformType") or 0),
                "accountId": str(item.get("accountId") or ""),
                "accountName": str(item.get("accountName") or ""),
                "tags": _normalize_publish_tags(item.get("tags")),
            }
            for item in (targets or (data or {}).get("targets") or [])
        ],
    }


def agent_content_hash(data, file_list=None, targets=None):
    payload = _json.dumps(_agent_guard_summary(data, file_list, targets), ensure_ascii=False, sort_keys=True)
    return _hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _severity_rank(value):
    return {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(value or "none").lower(), 0)


def _max_severity(issues):
    severity = "none"
    for issue in issues or []:
        if _severity_rank(issue.get("severity")) > _severity_rank(severity):
            severity = issue.get("severity") or severity
    return severity


def _decision_from_issues(issues):
    severity = _max_severity(issues)
    if _severity_rank(severity) >= _severity_rank(AGENT_BLOCK_LEVEL):
        return "block", severity
    if _severity_rank(severity) > 0:
        return "warn", severity
    return "allow", "none"


def _keyword_issues(text):
    issues = []
    for keyword, category in AGENT_HIGH_RISK_KEYWORDS.items():
        if keyword in text:
            issues.append({
                "category": category,
                "severity": "high",
                "evidence": keyword,
                "reason": f"内容包含高风险词：{keyword}",
                "suggestion": "删除或重写相关表达，确认视频画面和语境合规后重新质检。",
                "blocking": True,
            })
    for keyword, category in AGENT_MEDIUM_RISK_KEYWORDS.items():
        if keyword in text:
            issues.append({
                "category": category,
                "severity": "medium",
                "evidence": keyword,
                "reason": f"内容包含需要人工确认的风险词：{keyword}",
                "suggestion": "弱化绝对化表达，补充事实依据或改为中性描述。",
                "blocking": False,
            })
    return issues


def _call_guard_llm(messages, model, contract_id, validator, max_tokens=900):
    return call_json_contract(
        messages=messages,
        contract_id=contract_id,
        validator=validator,
        model=model,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=AGENT_GUARD_TEMPERATURE,
        max_tokens=int(max_tokens or AGENT_GUARD_MAX_TOKENS),
        prompt_version=llm_prompts.GUARD_PROMPT_VERSION,
    )


def _text_guard_result(summary):
    text = "\n".join([
        summary.get("title") or "",
        summary.get("description") or "",
        " ".join(summary.get("tags") or []),
    ])
    issues = _keyword_issues(text)
    if _agent_llm_available():
        try:
            result, _, _ = _call_guard_llm(
                llm_prompts.prepublish_text_guard_messages(summary),
                AGENT_CHAT_MODEL,
                "prepublish_text_guard",
                lambda value: validate_guard_result(value, with_suggested_edits=True),
            )
            if isinstance(result.get("issues"), list):
                issues.extend(result.get("issues"))
            suggested = result.get("suggestedEdits") if isinstance(result.get("suggestedEdits"), dict) else {}
        except Exception as exc:
            issues.append({
                "category": "text_model",
                "severity": "medium",
                "evidence": "LLM 文本质检失败",
                "reason": str(exc)[:300],
                "suggestion": "请检查 LLM 配置后重新质检。",
                "blocking": False,
            })
            suggested = {}
    else:
        suggested = {}
    return issues, suggested


def _publish_material_file(material):
    if not material:
        return None
    path = _material_file_path(material)
    return path if path and path.is_file() else None


def get_source_content_risk(publish_materials):
    """返回需要发布确认的来源内容风险；仅依赖已保存的转写分析结果。"""
    for material in publish_materials or []:
        if not isinstance(material, dict):
            continue
        analysis_result = material.get("analysisResult") or {}
        metadata = material.get("metadata") or {}
        video_id = str(
            material.get("source_video_id")
            or metadata.get("videoId")
            or metadata.get("sourceVideoId")
            or ""
        ).strip()
        if (not isinstance(analysis_result, dict) or not analysis_result) and video_id:
            try:
                analysis_result = (get_youtube_video_analysis(video_id) or {}).get("result") or {}
            except Exception:
                analysis_result = {}
        risk = analysis_result.get("contentRisk") if isinstance(analysis_result, dict) else {}
        if not isinstance(risk, dict) or not risk.get("requiresPublishConfirmation"):
            continue
        return {
            "requiresPublishConfirmation": True,
            "categories": list(risk.get("categories") or ["explicit_profanity"]),
            "excludedHighlightCount": int(risk.get("excludedHighlightCount") or 0),
            "availableHighlightCount": int(risk.get("availableHighlightCount") or 0),
            "message": str(risk.get("message") or "检测到来源内容风险，发布前需要人工确认。"),
            "videoId": video_id,
        }
    return {}


def _extract_guard_frames(publish_materials):
    if AGENT_REQUIRE_VISION_CHECK and not AGENT_VISION_MODEL:
        raise RuntimeError("AGENT_VISION_MODEL 未配置，无法完成关键帧审核。")
    if not AGENT_VISION_MODEL:
        return []
    material = (publish_materials or [{}])[0]
    video_path = _publish_material_file(material)
    if not video_path:
        raise RuntimeError("未找到可抽帧的视频文件。")
    duration = float(material.get("duration_seconds") or 0) if isinstance(material, dict) else 0
    timestamps = [AGENT_FRAME_FIRST_SECOND]
    if duration > 8:
        timestamps.extend([duration * ratio for ratio in AGENT_FRAME_SAMPLE_RATIOS])
        timestamps.append(max(AGENT_FRAME_FIRST_SECOND, duration - AGENT_FRAME_END_OFFSET_SECONDS))
    timestamps = sorted({max(0.5, round(float(item), 2)) for item in timestamps})[:AGENT_FRAME_MAX_COUNT]
    ffmpeg = _resolve_ffmpeg_command()
    frames = []
    with _tempfile.TemporaryDirectory(prefix="vidferry-agent-frames-") as tmp_dir:
        tmp_dir = Path(tmp_dir)
        for index, timestamp in enumerate(timestamps, start=1):
            frame_path = tmp_dir / f"frame_{index}.jpg"
            _run_command([
                ffmpeg,
                "-y",
                "-ss",
                f"{timestamp:.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({AGENT_FRAME_SCALE_WIDTH},iw)':-2",
                str(frame_path),
            ], cwd=BASE_DIR)
            if frame_path.is_file():
                frames.append({
                    "timestamp": timestamp,
                    "dataUrl": "data:image/jpeg;base64," + _base64.b64encode(frame_path.read_bytes()).decode("ascii"),
                })
    if not frames:
        raise RuntimeError("关键帧抽取失败。")
    return frames


def _vision_guard_result(summary, publish_materials):
    frames = _extract_guard_frames(publish_materials)
    if not frames:
        return []
    content = [
        {
            "type": "text",
            "text": (
                "请审核这些视频关键帧是否存在发布风险。只输出 JSON："
                "issues 数组，每项含 category,severity,evidence,reason,suggestion,blocking。"
                f"发布文本摘要：{_json.dumps(summary, ensure_ascii=False)}"
            ),
        }
    ]
    for frame in frames:
        content.append({"type": "text", "text": f"关键帧时间：{frame['timestamp']}秒"})
        content.append({"type": "image_url", "image_url": {"url": frame["dataUrl"]}})
    result, _, _ = _call_guard_llm(
        [
            {"role": "system", "content": llm_prompts.prepublish_vision_system_prompt()},
            {"role": "user", "content": content},
        ],
        AGENT_VISION_MODEL,
        "prepublish_vision_guard",
        lambda value: validate_guard_result(value, with_suggested_edits=False),
        max_tokens=AGENT_GUARD_MAX_TOKENS,
    )
    return result.get("issues") if isinstance(result.get("issues"), list) else []


def run_prepublish_guard(data, file_list=None, targets=None, publish_materials=None, session_id=""):
    started_at = _time.time()
    summary = _agent_guard_summary(data, file_list, targets)
    content_hash = agent_content_hash(data, file_list, targets)
    material = (publish_materials or [{}])[0]
    material_id = str(material.get("id") or "") if isinstance(material, dict) else ""
    if not AGENT_ENABLED or not AGENT_REQUIRE_PREPUBLISH_CHECK:
        result = {
            "decision": "allow",
            "severity": "none",
            "issues": [],
            "suggestedEdits": {},
            "contentHash": content_hash,
            "materialId": material_id,
            "disabled": True,
        }
        run_id = save_agent_run("prepublish_check", session_id=session_id, subject_type="material", subject_id=material_id, decision="allow", severity="none", content_hash=content_hash, input_summary=summary, output=result, model=AGENT_CHAT_MODEL, started_at=started_at)
        result["runId"] = run_id
        return result

    issues, suggested = _text_guard_result(summary)
    if AGENT_REQUIRE_VISION_CHECK:
        try:
            issues.extend(_vision_guard_result(summary, publish_materials or []))
        except Exception as exc:
            issues.append({
                "category": "vision_model",
                "severity": "high" if AGENT_VISION_FAIL_CLOSED else "medium",
                "evidence": "关键帧审核未完成",
                "reason": str(exc)[:300],
                "suggestion": "配置 AGENT_VISION_MODEL 并确保视频可抽帧后重新质检。",
                "blocking": AGENT_VISION_FAIL_CLOSED,
            })

    decision, severity = _decision_from_issues(issues)
    result = {
        "decision": decision,
        "severity": severity,
        "confidence": 0.85 if issues else 0.65,
        "issues": issues,
        "suggestedEdits": suggested,
        "contentHash": content_hash,
        "materialId": material_id,
    }
    run_id = save_agent_run(
        "prepublish_check",
        session_id=session_id,
        subject_type="material",
        subject_id=material_id,
        status="blocked" if decision == "block" else "success",
        decision=decision,
        severity=severity,
        content_hash=content_hash,
        input_summary=summary,
        output=result,
        model=f"{AGENT_CHAT_MODEL}/{AGENT_VISION_MODEL}",
        started_at=started_at,
    )
    result["runId"] = run_id
    return result


def agent_guard_run_payload(run, current_content_hash=""):
    if not run:
        return None
    result = dict(run.get("output") or {})
    result.update({
        "runId": run.get("id") or "",
        "materialId": run.get("subjectId") or result.get("materialId") or "",
        "checkedAt": run.get("createdAt") or "",
        "inputSummary": run.get("inputSummary") or {},
        "contentChanged": bool(current_content_hash and run.get("contentHash") != current_content_hash),
    })
    return result


def validate_prepublish_guard_or_raise(
    data,
    file_list=None,
    targets=None,
    publish_materials=None,
    check_agent=True,
):
    source_content_risk = get_source_content_risk(publish_materials)
    override = (data or {}).get("riskOverride") or {}
    if source_content_risk and not override.get("sourceContentConfirmed"):
        raise AgentGuardError(
            "检测到转写中含明确粗口，中文字幕已打码，但原声及英文字幕可能仍含风险；请确认后继续发布。",
            AGENT_ERROR_REQUIRES_CONFIRMATION,
            409,
            {
                "decision": "warn",
                "severity": "medium",
                "issues": [],
                "contentRisk": source_content_risk,
                "requiresSourceContentConfirmation": True,
            },
        )
    if not check_agent or not AGENT_ENABLED or not AGENT_REQUIRE_PREPUBLISH_CHECK:
        return {"decision": "allow", "disabled": True}

    content_hash = agent_content_hash(data, file_list, targets)
    guard_result = None
    run_id = str((data or {}).get("agentRunId") or "").strip()
    if run_id:
        run = get_agent_run(run_id)
        if run and run.get("type") == "prepublish_check" and run.get("contentHash") == content_hash:
            guard_result = dict(run.get("output") or {})
            guard_result.setdefault("runId", run_id)

    if not guard_result:
        guard_result = run_prepublish_guard(data, file_list, targets, publish_materials)

    decision = guard_result.get("decision")
    if decision == "block":
        raise AgentGuardError("发布前质检已拦截，请修改内容后重新质检。", AGENT_ERROR_BLOCKED, 422, guard_result)
    if decision == "warn":
        reason = str(override.get("reason") or "").strip()
        if not override.get("confirmed") or not reason:
            raise AgentGuardError("发布前质检发现风险，需要填写人工确认原因。", AGENT_ERROR_REQUIRES_CONFIRMATION, 409, guard_result)
        guard_result["override"] = {"confirmed": True, "reason": reason}
    return guard_result
