"""Human-readable Feishu card formatting for Vidferry Agent results."""

from __future__ import annotations

from app.config import FEISHU_BUTLER_CONSOLE_URL


TOOL_LABELS = {
    "explain_vidferry_pipeline": "工作流说明",
    "get_account_status": "账号状态",
    "get_publish_platforms": "发布平台",
    "get_video_detail": "视频详情",
    "get_workflow_overview": "工作流概览",
    "list_failed_jobs": "异常任务",
    "list_publish_tasks": "发布任务",
    "list_videos_by_status": "视频列表",
    "waiting_confirmation": "待发布确认",
}
DETAIL_KEYS = ("title", "name", "platform", "channel", "status", "step", "message", "publishedAt", "updatedAt")


def _text(value, sanitize):
    return sanitize(str(value or "")).strip()


def _item_line(item, sanitize):
    if not isinstance(item, dict):
        return _text(item, sanitize)
    values = [_text(item.get(key), sanitize) for key in DETAIL_KEYS if item.get(key)]
    return " | ".join(values) or "无可显示字段"


def _summary(payload, sanitize):
    if not isinstance(payload, dict):
        return _text(payload, sanitize) or "无结果"
    if payload.get("found") is False:
        return _text(payload.get("message") or "未找到匹配结果", sanitize)
    if isinstance(payload.get("counts"), dict):
        return "\n".join(f"{key}：{value}" for key, value in payload["counts"].items())
    if isinstance(payload.get("pipeline"), list):
        return "\n".join(f"{index + 1}. {_text(item.get('label'), sanitize)}" for index, item in enumerate(payload["pipeline"]))
    if isinstance(payload.get("items"), list):
        total = payload.get("total", len(payload["items"]))
        lines = [f"共 {total} 项"]
        lines.extend(f"{index + 1}. {_item_line(item, sanitize)}" for index, item in enumerate(payload["items"][:5]))
        if total > 5:
            lines.append("其余结果请在 Web 控制台查看")
        return "\n".join(lines)
    values = [_item_line(payload, sanitize)]
    if payload.get("platforms"):
        values.append(_summary(payload["platforms"], sanitize))
    return "\n".join(item for item in values if item)


def tool_sections(tool_results, sanitize=str):
    sections = []
    for item in tool_results or []:
        name = str(item.get("tool") or "unknown")
        title = TOOL_LABELS.get(name, name)
        if item.get("error"):
            content = f"调用失败：{_text(item['error'], sanitize)}"
        else:
            content = _summary(item.get("result"), sanitize)
        sections.append({"title": title, "content": content[:1800]})
    return sections


def _action_buttons():
    buttons = (
        ("查看异常", "failed"),
        ("待确认", "waiting"),
        ("项目概览", "overview"),
        ("账号状态", "accounts"),
    )
    actions = [
        {
            "tag": "button",
            "type": "default",
            "text": {"tag": "plain_text", "content": label},
            "value": {"butlerAction": action},
        }
        for label, action in buttons
    ] + [{
        "tag": "button",
        "type": "primary",
        "text": {"tag": "plain_text", "content": "打开控制台"},
        "url": FEISHU_BUTLER_CONSOLE_URL,
    }]
    return {
        "tag": "column_set",
        "columns": [{"tag": "column", "elements": [button]} for button in actions],
    }


def result_card(answer, tool_results, sanitize=str, *, title="Vidferry 项目管家", template="blue", actions=True):
    elements = [{"tag": "markdown", "content": _text(answer, sanitize)[:3000] or "我暂时没有查到结果。"}]
    for section in tool_sections(tool_results, sanitize):
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"**{section['title']}**\n{section['content']}"})
    if actions:
        elements.append({"tag": "hr"})
        elements.append(_action_buttons())
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "body": {"elements": elements},
    }
