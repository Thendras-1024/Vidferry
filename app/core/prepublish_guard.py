"""发布前质检守卫:文本与关键帧风险检测、严重度决策与拦截/人工确认。"""


from __future__ import annotations

import base64 as _base64
import hashlib as _hashlib
import json as _json
import tempfile as _tempfile
import time as _time


AGENT_ERROR_BLOCKED = "VF-AGENT-BLOCKED"
AGENT_ERROR_REQUIRES_CONFIRMATION = "VF-AGENT-REQUIRES-CONFIRMATION"


class AgentGuardError(RuntimeError):
    def __init__(self, message, error_code, status_code, result=None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.result = result or {}


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


def _call_guard_llm(messages, model, max_tokens=900):
    if not LLM_API_KEY or not LLM_BASE_URL or not model:
        raise RuntimeError("LLM 或视觉模型未配置")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": AGENT_GUARD_TEMPERATURE,
        "max_tokens": int(max_tokens or AGENT_GUARD_MAX_TOKENS),
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
        data = _json.loads(response.read().decode("utf-8"))
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    return _json.loads(content)


def _text_guard_result(summary):
    text = "\n".join([
        summary.get("title") or "",
        summary.get("description") or "",
        " ".join(summary.get("tags") or []),
    ])
    issues = _keyword_issues(text)
    if _agent_llm_available():
        try:
            result = _call_guard_llm([
                {
                    "role": "system",
                    "content": (
                        "你是 Vidferry 发布前文本安全质检器。只输出 JSON："
                        "issues 数组，每项含 category,severity,evidence,reason,suggestion,blocking；"
                        "suggestedEdits 对象，含 title,description,tags。severity 只能 none/low/medium/high/critical。"
                    ),
                },
                {"role": "user", "content": _json.dumps(summary, ensure_ascii=False)},
            ], AGENT_CHAT_MODEL)
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
    result = _call_guard_llm([{"role": "user", "content": content}], AGENT_VISION_MODEL, max_tokens=AGENT_GUARD_MAX_TOKENS)
    return result.get("issues") if isinstance(result.get("issues"), list) else []


def run_prepublish_guard(data, file_list=None, targets=None, publish_materials=None, session_id=""):
    started_at = _time.time()
    summary = _agent_guard_summary(data, file_list, targets)
    content_hash = agent_content_hash(data, file_list, targets)
    if not AGENT_ENABLED or not AGENT_REQUIRE_PREPUBLISH_CHECK:
        result = {
            "decision": "allow",
            "severity": "none",
            "issues": [],
            "suggestedEdits": {},
            "contentHash": content_hash,
            "disabled": True,
        }
        run_id = save_agent_run("prepublish_check", session_id=session_id, decision="allow", severity="none", content_hash=content_hash, input_summary=summary, output=result, model=AGENT_CHAT_MODEL, started_at=started_at)
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
    }
    run_id = save_agent_run(
        "prepublish_check",
        session_id=session_id,
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


def validate_prepublish_guard_or_raise(data, file_list=None, targets=None, publish_materials=None):
    if not AGENT_ENABLED or not AGENT_REQUIRE_PREPUBLISH_CHECK:
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
        override = (data or {}).get("riskOverride") or {}
        reason = str(override.get("reason") or "").strip()
        if not override.get("confirmed") or not reason:
            raise AgentGuardError("发布前质检发现风险，需要填写人工确认原因。", AGENT_ERROR_REQUIRES_CONFIRMATION, 409, guard_result)
        guard_result["override"] = {"confirmed": True, "reason": reason}
    return guard_result
