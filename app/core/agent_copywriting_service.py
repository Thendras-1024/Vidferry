"""Agent 发布稿改写提案：候选视频、结构化文案与确认保存。"""

from __future__ import annotations

import datetime as _datetime
import secrets as _secrets
import threading as _threading
import time as _time
from zoneinfo import ZoneInfo as _ZoneInfo


_AGENT_COPYWRITING_PROPOSAL_TTL_SECONDS = 15 * 60
_AGENT_COPYWRITING_PROPOSALS = {}
_AGENT_COPYWRITING_PROPOSALS_LOCK = _threading.Lock()
_AGENT_COPYWRITING_TIMEZONE = _ZoneInfo("Asia/Shanghai")


def is_agent_copywriting_request(message):
    text = str(message or "").lower()
    has_content = any(word in text for word in ("文案", "标题", "话题", "标签", "发布稿"))
    has_change = any(word in text for word in ("改", "修改", "重写", "优化", "调整", "换", "不好", "重新"))
    return has_content and has_change


def _agent_copywriting_now():
    return _datetime.datetime.now(_AGENT_COPYWRITING_TIMEZONE)


def _agent_copywriting_parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = _datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_AGENT_COPYWRITING_TIMEZONE)
    return parsed.astimezone(_AGENT_COPYWRITING_TIMEZONE)


def _agent_copywriting_cleanup_expired(now=None):
    now = float(now if now is not None else _time.time())
    expired = [
        proposal_id
        for proposal_id, proposal in _AGENT_COPYWRITING_PROPOSALS.items()
        if float(proposal.get("expiresAt") or 0) <= now
    ]
    for proposal_id in expired:
        _AGENT_COPYWRITING_PROPOSALS.pop(proposal_id, None)


def _agent_copywriting_load_video(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute(
            "SELECT * FROM youtube_videos WHERE video_id = ? AND owner_user_id = ?",
            (video_id, _agent_current_user_id()),
        ).fetchone()
    return _row_to_youtube_video(row) if row else None


def _agent_copywriting_is_ready_video(video):
    return bool(video) and int(video.get("translateStatus") or 0) == 1


def _agent_copywriting_latest_processed_at(video_id):
    owner_user_id = _agent_current_user_id()
    with _db_connect() as conn:
        conn.row_factory = True
        row = conn.execute(
            """
            SELECT updated_at
            FROM youtube_workflow_jobs
            WHERE video_id = ? AND owner_user_id = ? AND status = 'success'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (str(video_id or "").strip(), owner_user_id),
        ).fetchone()
    return row["updated_at"] if row else ""


def _agent_copywriting_analysis_snapshot(video_id):
    try:
        analysis = get_youtube_video_analysis(video_id, _agent_current_user_id())
    except LookupError:
        analysis = {}
    result = analysis.get("result") if isinstance(analysis.get("result"), dict) else {}
    draft = analysis.get("draft") if isinstance(analysis.get("draft"), dict) else {}
    return {
        "analysis": {
            "summary": result.get("summary") or "",
            "chinaViewAngle": result.get("china_view_angle") or "",
            "titleOptions": result.get("title_options") or [],
            "publishCopy": result.get("publish_copy") or "",
            "tags": result.get("tags") or [],
            "riskNotes": result.get("risk_notes") or [],
        },
        "publishDraft": {
            "title": draft.get("title") or "",
            "description": draft.get("description") or "",
            "tags": draft.get("tags") or [],
            "customTags": draft.get("customTags") or [],
            "coverTitle": draft.get("coverTitle") or "",
        },
    }


def _agent_copywriting_video_snapshot(video, processed_at=""):
    analysis = _agent_copywriting_analysis_snapshot(video.get("id"))
    return {
        "id": video.get("id") or "",
        "title": video.get("title") or "",
        "channel": video.get("channel") or "",
        "duration": video.get("duration") or "",
        "subscribers": video.get("subscribers") or "",
        "publishedAt": video.get("publishedAt") or "",
        "query": video.get("query") or "",
        "groupName": video.get("groupName") or "",
        "thumbnail": video.get("thumbnail") or "",
        "processedAt": processed_at or "",
        "status": "已处理未发布",
        **analysis,
    }


def list_agent_today_processed_videos(now=None):
    current_time = now if isinstance(now, _datetime.datetime) else _agent_copywriting_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=_AGENT_COPYWRITING_TIMEZONE)
    today = current_time.astimezone(_AGENT_COPYWRITING_TIMEZONE).date()
    owner_user_id = _agent_current_user_id()
    if owner_user_id is None:
        raise PermissionError("Agent 文案查询缺少当前用户身份")
    with _db_connect() as conn:
        conn.row_factory = True
        rows = conn.execute(
            """
            SELECT video.*, job.updated_at AS agent_processed_at
            FROM youtube_videos AS video
            JOIN youtube_workflow_jobs AS job ON job.id = (
                SELECT latest.id
                FROM youtube_workflow_jobs AS latest
                WHERE latest.video_id = video.video_id
                  AND latest.owner_user_id = video.owner_user_id
                  AND latest.status = 'success'
                ORDER BY latest.updated_at DESC, latest.created_at DESC
                LIMIT 1
            )
            WHERE COALESCE(video.translate_status, 0) = 1
              AND COALESCE(video.publish_status, 0) != 1
              AND video.owner_user_id = ?
            ORDER BY job.updated_at DESC, job.created_at DESC
            """,
            (owner_user_id,),
        ).fetchall()
    candidates = []
    for row in rows:
        processed_at = _agent_copywriting_parse_time(row["agent_processed_at"])
        if not processed_at or processed_at.date() != today:
            continue
        candidates.append(_agent_copywriting_video_snapshot(_row_to_youtube_video(row), row["agent_processed_at"] or ""))
    return candidates


def _agent_copywriting_new_proposal(session_id, message, candidates):
    proposal_id = _secrets.token_urlsafe(18)
    proposal = {
        "proposalId": proposal_id,
        "sessionId": str(session_id or ""),
        "status": "selecting_video",
        "request": str(message or "").strip(),
        "candidates": candidates,
        "selectedVideoId": "",
        "selectedVideoIds": [],
        "currentIndex": 0,
        "video": None,
        "drafts": [],
        "manualDraft": {},
        "savedVideoIds": [],
        "resultMessage": "",
        "expiresAt": _time.time() + _AGENT_COPYWRITING_PROPOSAL_TTL_SECONDS,
    }
    with _AGENT_COPYWRITING_PROPOSALS_LOCK:
        _agent_copywriting_cleanup_expired()
        _AGENT_COPYWRITING_PROPOSALS[proposal_id] = proposal
    return _agent_copywriting_public_proposal(proposal)


def _agent_copywriting_public_proposal(proposal):
    return {key: value for key, value in proposal.items() if key != "sessionId"}


def _agent_copywriting_get_proposal(proposal_id, session_id):
    proposal_id = str(proposal_id or "").strip()
    session_id = str(session_id or "").strip()
    if not get_agent_session(session_id):
        raise ValueError("文案提案已失效，请重新让 Agent 生成。")
    with _AGENT_COPYWRITING_PROPOSALS_LOCK:
        _agent_copywriting_cleanup_expired()
        proposal = _AGENT_COPYWRITING_PROPOSALS.get(proposal_id)
        if not proposal or proposal.get("sessionId") != session_id:
            raise ValueError("文案提案已失效，请重新让 Agent 生成。")
        return proposal


def invalidate_agent_copywriting_selection(session_id):
    """选择集变化后，旧的多视频文案提案不得继续写入。"""
    session_id = str(session_id or "").strip()
    expired_ids = []
    with _AGENT_COPYWRITING_PROPOSALS_LOCK:
        _agent_copywriting_cleanup_expired()
        for proposal in _AGENT_COPYWRITING_PROPOSALS.values():
            if proposal.get("sessionId") == session_id and proposal.get("status") in {"selecting_video", "ready"}:
                proposal["status"] = "expired"
                proposal["resultMessage"] = "视频选择已变更，请重新生成文案提案。"
                expired_ids.append(proposal.get("proposalId"))
    for proposal_id in expired_ids:
        update_agent_proposal_state(
            session_id,
            proposal_id,
            "copywritingProposal",
            "expired",
            result_message="视频选择已变更，请重新生成文案提案。",
        )


def create_agent_copywriting_proposal(session_id, message, page_context):
    session = get_agent_session(session_id) if session_id else None
    if not session:
        return {
            "status": "unavailable",
            "message": "Agent 会话不可用，请重新发送改写请求。",
            "candidates": [],
        }
    if session and session.get("source") == "feishu":
        return {
            "status": "unavailable",
            "message": "手机端 Agent 仅支持查询，请在网页端修改待发布稿。",
            "candidates": [],
        }
    context = page_context if isinstance(page_context, dict) else {}
    video_context = context.get("videoContext") if isinstance(context.get("videoContext"), dict) else {}
    selected_id = str(video_context.get("videoId") or "").strip()
    selected_ids = get_agent_video_selection(session_id)
    if selected_ids:
        candidates = []
        for video_id in selected_ids:
            video = _agent_copywriting_load_video(video_id)
            if _agent_copywriting_is_ready_video(video):
                candidates.append(_agent_copywriting_video_snapshot(video, _agent_copywriting_latest_processed_at(video_id)))
        if not candidates:
            return {
                "status": "unavailable",
            "message": "已选视频中没有已处理视频，请重新选择。",
                "candidates": [],
            }
        proposal = _agent_copywriting_new_proposal(session_id, message, candidates)
        proposal_id = proposal["proposalId"]
        with _AGENT_COPYWRITING_PROPOSALS_LOCK:
            stored = _AGENT_COPYWRITING_PROPOSALS.get(proposal_id)
            stored["selectedVideoIds"] = [item["id"] for item in candidates]
        return generate_agent_copywriting_candidates(proposal_id, session_id, candidates[0]["id"], message)
    if selected_id:
        video = _agent_copywriting_load_video(selected_id)
        if not _agent_copywriting_is_ready_video(video):
            return {
                "status": "unavailable",
            "message": "当前视频尚未处理完成，无法改写本地发布稿。",
                "candidates": [],
            }
        proposal = _agent_copywriting_new_proposal(
            session_id,
            message,
            [_agent_copywriting_video_snapshot(video, _agent_copywriting_latest_processed_at(selected_id))],
        )
        with _AGENT_COPYWRITING_PROPOSALS_LOCK:
            _AGENT_COPYWRITING_PROPOSALS[proposal["proposalId"]]["selectedVideoIds"] = [selected_id]
        return generate_agent_copywriting_candidates(proposal["proposalId"], session_id, selected_id)

    candidates = list_agent_today_processed_videos()
    if not candidates:
        return {
            "status": "unavailable",
            "message": "今天没有找到已处理未发布的视频，请在视频页面选中素材后再试。",
            "candidates": [],
        }
    return _agent_copywriting_new_proposal(session_id, message, candidates)


def _agent_copywriting_validate_draft(value):
    value = value if isinstance(value, dict) else {}
    title = str(value.get("title") or "").strip()
    description = str(value.get("description") or "").strip()
    if not title:
        raise ValueError("发布标题不能为空。")
    if len(description) > 500:
        raise ValueError("发布正文不能超过 500 个字符。")
    tags = []
    for item in value.get("tags") or []:
        tag = str(item or "").strip().lstrip("#").strip()
        if tag and tag not in tags:
            tags.append(tag)
    return {"title": title, "description": description, "tags": tags}


def _agent_copywriting_generate_drafts(proposal, snapshot):
    if not (TEXT_LLM_API_KEY and TEXT_LLM_BASE_URL and TEXT_LLM_MODEL):
        raise ValueError("文案模型未配置，无法生成候选。")
    result, _, _ = call_json_contract(
        messages=llm_prompts.agent_copywriting_messages(proposal.get("request") or "", snapshot),
        contract_id="agent_copywriting",
        validator=validate_agent_copywriting,
        model=TEXT_LLM_MODEL,
        api_key=TEXT_LLM_API_KEY,
        base_url=TEXT_LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=AGENT_CHAT_TEMPERATURE,
        max_tokens=1800,
        prompt_version=llm_prompts.AGENT_COPYWRITING_PROMPT_VERSION,
    )
    return [{**_agent_copywriting_validate_draft(item), "reason": item.get("reason") or ""} for item in result["options"]], snapshot


def _agent_copywriting_manual_draft(snapshot):
    draft = snapshot.get("publishDraft") if isinstance(snapshot.get("publishDraft"), dict) else {}
    return {
        "title": str(draft.get("title") or ""),
        "description": str(draft.get("description") or ""),
        "tags": _agent_copywriting_validate_draft({"title": "placeholder", "tags": draft.get("tags") or []})["tags"],
    }


def generate_agent_copywriting_candidates(proposal_id, session_id, video_id, request=None):
    proposal = _agent_copywriting_get_proposal(proposal_id, session_id)
    if proposal.get("status") not in {"selecting_video", "ready"}:
        raise ValueError("该文案提案不能继续生成候选。")
    if request is not None:
        normalized_request = str(request or "").strip()
        if not normalized_request:
            raise ValueError("请填写文案要求。")
        proposal["request"] = normalized_request[:2000]
    candidate_ids = {str(item.get("id") or "") for item in proposal.get("candidates") or []}
    video_id = str(video_id or "").strip()
    if video_id not in candidate_ids:
        raise ValueError("所选视频不在当前文案提案中。")
    video = _agent_copywriting_load_video(video_id)
    if not _agent_copywriting_is_ready_video(video):
        raise ValueError("该视频已不是已处理未发布状态，请重新选择。")
    candidate = next((item for item in proposal.get("candidates") or [] if item.get("id") == video_id), {})
    snapshot = _agent_copywriting_video_snapshot(video, candidate.get("processedAt") or _agent_copywriting_latest_processed_at(video_id))
    drafts, snapshot = _agent_copywriting_generate_drafts(proposal, snapshot)
    manual_draft = _agent_copywriting_manual_draft(snapshot)
    with _AGENT_COPYWRITING_PROPOSALS_LOCK:
        stored = _AGENT_COPYWRITING_PROPOSALS.get(str(proposal_id))
        if stored is not proposal:
            raise ValueError("文案提案已失效，请重新生成。")
        stored.update({
            "status": "ready",
            "selectedVideoId": video_id,
            "video": snapshot,
            "drafts": drafts,
            "manualDraft": manual_draft,
            "expiresAt": _time.time() + _AGENT_COPYWRITING_PROPOSAL_TTL_SECONDS,
        })
        public = _agent_copywriting_public_proposal(stored)
    update_agent_proposal_state(
        session_id,
        proposal_id,
        "copywritingProposal",
        "ready",
        proposal_updates={
            "selectedVideoId": video_id,
            "video": snapshot,
            "drafts": drafts,
            "manualDraft": manual_draft,
            "request": proposal.get("request") or "",
            "currentIndex": int(proposal.get("currentIndex") or 0),
            "selectedVideoIds": proposal.get("selectedVideoIds") or [video_id],
            "expiresAt": public["expiresAt"],
        },
    )
    return public


def apply_agent_copywriting_proposal(proposal_id, session_id, draft_index, payload, draft_kind="llm"):
    proposal = _agent_copywriting_get_proposal(proposal_id, session_id)
    if proposal.get("status") != "ready":
        raise ValueError("请先生成文案候选。")
    draft_kind = str(draft_kind or "llm").strip().lower()
    drafts = proposal.get("drafts") or []
    if draft_kind == "manual":
        base = proposal.get("manualDraft") if isinstance(proposal.get("manualDraft"), dict) else {}
        selected_draft_key = "manual"
    else:
        try:
            draft_index = int(draft_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("文案候选索引不正确。") from exc
        if draft_index < 0 or draft_index >= len(drafts):
            raise ValueError("所选文案候选不存在。")
        base = drafts[draft_index]
        selected_draft_key = f"llm-{draft_index}"
    video_id = str(proposal.get("selectedVideoId") or "").strip()
    video = _agent_copywriting_load_video(video_id)
    if not _agent_copywriting_is_ready_video(video):
        raise ValueError("该视频尚未处理完成，无法覆盖本地发布稿。")
    draft = _agent_copywriting_validate_draft({
        "title": payload.get("title", base.get("title")),
        "description": payload.get("description", base.get("description")),
        "tags": payload.get("tags", base.get("tags")),
    })
    saved = update_youtube_video_publish_draft(video_id, {**draft, "customTags": []}, _agent_current_user_id())
    saved_draft = saved.get("draft") if isinstance(saved.get("draft"), dict) else draft
    selected_video_ids = [str(item) for item in proposal.get("selectedVideoIds") or [] if str(item)]
    if not selected_video_ids:
        selected_video_ids = [video_id]
    current_index = int(proposal.get("currentIndex") or 0)
    saved_video_ids = [str(item) for item in proposal.get("savedVideoIds") or [] if str(item)]
    if video_id not in saved_video_ids:
        saved_video_ids.append(video_id)
    has_next = current_index + 1 < len(selected_video_ids)
    result_message = "待发布稿已保存。"
    with _AGENT_COPYWRITING_PROPOSALS_LOCK:
        stored = _AGENT_COPYWRITING_PROPOSALS.get(str(proposal_id))
        if stored is proposal:
            stored.update({
                "status": "selecting_video" if has_next else "confirmed",
                "selectedDraftIndex": draft_index if draft_kind == "llm" else None,
                "selectedDraftKey": selected_draft_key,
                "savedVideoIds": saved_video_ids,
                "resultMessage": result_message,
                "drafts": [],
                "manualDraft": {},
            })
            if has_next:
                stored.update({
                    "currentIndex": current_index + 1,
                    "selectedVideoId": "",
                    "video": None,
                })
            public = _agent_copywriting_public_proposal(stored)
        else:
            public = {}
    update_agent_proposal_state(
        session_id,
        proposal_id,
        "copywritingProposal",
        "selecting_video" if has_next else "confirmed",
        result_message=result_message,
        proposal_updates={
            "selectedDraftIndex": draft_index if draft_kind == "llm" else None,
            "selectedDraftKey": selected_draft_key,
            "savedDraft": saved_draft,
            "savedVideoIds": saved_video_ids,
            "currentIndex": current_index + 1 if has_next else current_index,
        },
    )
    if has_next:
        next_video_id = selected_video_ids[current_index + 1]
        try:
            public = generate_agent_copywriting_candidates(proposal_id, session_id, next_video_id, proposal.get("request"))
            result_message = f"已保存第 {current_index + 1} 条，已生成下一条视频的文案候选。"
            public["resultMessage"] = result_message
        except Exception as exc:
            result_message = f"已保存当前待发布稿；下一条文案生成失败：{str(exc)}"
            with _AGENT_COPYWRITING_PROPOSALS_LOCK:
                stored = _AGENT_COPYWRITING_PROPOSALS.get(str(proposal_id))
                if stored is proposal:
                    stored["resultMessage"] = result_message
                    public = _agent_copywriting_public_proposal(stored)
    return {"proposal": public, "videoId": video_id, "draft": saved_draft, "message": result_message}
