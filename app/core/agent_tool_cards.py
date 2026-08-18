"""将 Agent 只读工具结果规范为前端可直接渲染的信息卡。"""

from __future__ import annotations


def _agent_card_text(value, limit=180):
    text = str(value or "").strip()
    return text[:limit]


def _agent_card_items(items, title_key="title", detail_keys=(), status_key="status"):
    result = []
    for item in items or []:
        item = item if isinstance(item, dict) else {}
        detail = " · ".join(
            _agent_card_text(item.get(key), 80)
            for key in detail_keys
            if _agent_card_text(item.get(key), 80)
        )
        result.append({
            "title": _agent_card_text(item.get(title_key) or item.get("name") or item.get("filename") or "未命名记录", 120),
            "detail": detail,
            "status": _agent_card_text(item.get(status_key), 48),
        })
    return result


def _agent_card(title, items=(), count=None, card_type="tool_info"):
    payload = {"type": card_type, "title": title, "items": list(items or [])}
    if count is not None:
        payload["count"] = int(count)
    return payload


def agent_tool_result_cards(tool_results):
    """覆盖所有非专用卡片工具；专用视频、账号和快手卡由调用方补充。"""
    cards = []
    actions = []
    for item in tool_results or []:
        name = item.get("tool") if isinstance(item, dict) else ""
        result = item.get("result") if isinstance(item, dict) and isinstance(item.get("result"), dict) else {}
        if name in {"list_videos_by_status", "get_video_detail", "list_failed_jobs", "get_account_status", "prepare_video_action"}:
            continue
        if name in KUAISHOU_ANALYTICS_TOOL_NAMES:
            continue
        if name in {"load_skill", "read_skill_reference"}:
            cards.append(_agent_card("Skill 文档", [{
                "title": _agent_card_text(result.get("name") or item.get("args", {}).get("name") or "Skill", 120),
                "detail": _agent_card_text(result.get("description") or result.get("content") or "仅供查看，不会扩展 Agent 权限。", 240),
                "status": "只读",
            }], 1, "skill"))
        elif name == "explain_vidferry_pipeline":
            cards.append(_agent_card("视频工作流", _agent_card_items(result.get("steps"), "label", ("description",), "key"), len(result.get("steps") or []), "workflow"))
        elif name == "get_workflow_overview":
            labels = result.get("labels") if isinstance(result.get("labels"), dict) else {}
            counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
            cards.append(_agent_card("工作流概览", [
                {"title": labels.get(key) or key, "detail": f"{int(value or 0)} 个视频", "status": ""}
                for key, value in counts.items()
            ], len(counts), "workflow_overview"))
        elif name == "get_publish_platforms":
            cards.append(_agent_card("发布平台记录", _agent_card_items(result.get("items"), "platform", ("accountName", "publishedAt")), result.get("total", 0), "publish_platforms"))
        elif name == "list_publish_tasks":
            cards.append(_agent_card("发布任务", _agent_card_items(result.get("items"), "chineseTitle", ("publishedAt",), "overallStatus"), len(result.get("items") or []), "publish_tasks"))
        elif name == "get_agent_run_overview":
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else result
            cards.append(_agent_card("Agent 运行统计", [
                {"title": key, "detail": _agent_card_text(value, 80), "status": ""}
                for key, value in summary.items()
                if isinstance(value, (int, float, str))
            ][:8], None, "agent_metrics"))
        elif name == "get_workflow_settings":
            settings = result.get("settings") if isinstance(result.get("settings"), dict) else result
            cards.append(_agent_card("工作流设置", [
                {"title": _agent_card_text(key, 80), "detail": _agent_card_text(value, 120), "status": "只读"}
                for key, value in settings.items()
                if not isinstance(value, (dict, list))
            ][:12], None, "workflow_settings"))
        elif name == "list_short_video_projects":
            cards.append(_agent_card("短视频项目", _agent_card_items(result.get("items"), "topic", ("targetCount", "updatedAt")), len(result.get("items") or []), "short_video_projects"))
        elif name == "get_short_video_project":
            candidates = result.get("candidates") or []
            cards.append(_agent_card("短视频项目详情", [{
                "title": _agent_card_text(result.get("topic") or "未命名项目", 120),
                "detail": _agent_card_text(result.get("message") or result.get("updatedAt"), 160),
                "status": _agent_card_text(result.get("status"), 48),
            }], 1, "short_video_project"))
            if candidates:
                cards.append(_agent_card("候选审核", _agent_card_items(candidates, "title", ("channel", "analysisReason"), "analysisStatus"), len(candidates), "short_video_candidates"))
        elif name == "list_material_records":
            cards.append(_agent_card("素材", _agent_card_items(result.get("items"), "title", ("filename", "duration", "sourceType")), result.get("total", 0), "materials"))
        elif name == "search_youtube_candidates":
            cards.append(_agent_card("YouTube 候选", _agent_card_items(result.get("items"), "title", ("shortCode", "channel", "duration", "publishedAt", "viewCount")), len(result.get("items") or []), "youtube_candidates"))
        elif name == "inspect_youtube_url":
            candidate = result.get("item") if isinstance(result.get("item"), dict) else {}
            cards.append(_agent_card("YouTube 候选", _agent_card_items([candidate], "title", ("channel", "duration")), 1 if candidate else 0, "youtube_candidate"))
        elif name == "generate_pending_publish_plan":
            cards.append(_agent_card("发布建议", _agent_card_items(result.get("items"), "title", ("materialStatus", "requiredAction")), result.get("total", 0), "publish_plan"))
    return cards, actions
