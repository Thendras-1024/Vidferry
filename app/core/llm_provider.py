"""OpenAI Chat Completions 兼容服务商的请求字段与能力探测。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


SUPPORTED_PROVIDERS = {
    "auto", "openai_compatible", "dashscope", "longcat",
    "zhipu", "kimi", "deepseek", "volcengine_ark",
}

_DATA_URL_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAAARn"
    "QU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAATSURBVDhPYxgFo2AUjAIw"
    "YGAAAAQQAAGnRHxjAAAAAElFTkSuQmCC"
)


def normalize_provider(value, base_url=""):
    provider = str(value or "").strip().lower().replace("-", "_")
    if provider in SUPPORTED_PROVIDERS - {"auto"}:
        return provider
    host = str(base_url or "").lower()
    if "dashscope" in host:
        return "dashscope"
    if "longcat.chat" in host:
        return "longcat"
    if "bigmodel.cn" in host:
        return "zhipu"
    if "moonshot" in host or "kimi.com" in host:
        return "kimi"
    if "deepseek.com" in host:
        return "deepseek"
    if "volces.com" in host or "volcengine" in host:
        return "volcengine_ark"
    return "openai_compatible"


def chat_completion_url(base_url):
    value = str(base_url or "").rstrip("/")
    return value if value.endswith("/chat/completions") else f"{value}/chat/completions"


def provider_optional_fields(provider, disable_thinking=True, structured=True):
    provider = normalize_provider(provider)
    fields = {}
    if structured and provider != "longcat":
        fields["response_format"] = {"type": "json_object"}
    if provider == "deepseek":
        fields["thinking"] = {"type": "disabled" if disable_thinking else "enabled"}
        return fields
    if not disable_thinking:
        return fields
    if provider == "dashscope":
        fields["enable_thinking"] = False
    elif provider in {"longcat", "zhipu", "kimi", "deepseek", "volcengine_ark"}:
        fields["thinking"] = {"type": "disabled"}
    return fields


def provider_probe_payload(model, provider, multimodal=False, disable_thinking=True):
    content = [{"type": "text", "text": "请只返回 JSON：{\"ok\":true}"}]
    if multimodal:
        content.append({"type": "image_url", "image_url": {"url": _DATA_URL_PNG}})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 64,
    }
    payload.update(provider_optional_fields(provider, disable_thinking, structured=True))
    return payload


def fallback_payloads(payload):
    """按累计移除顺序生成可选字段降级请求，避免单字段重试遗漏组合冲突。"""
    current = dict(payload)
    yield current, []
    removed = []
    for key in ("enable_thinking", "thinking", "response_format"):
        if key not in current:
            continue
        current = {name: value for name, value in current.items() if name != key}
        removed.append(key)
        yield current, list(removed)


def request_chat_completion(base_url, api_key, timeout, payload):
    request = urllib.request.Request(
        chat_completion_url(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def response_content(data):
    choice = ((data or {}).get("choices") or [{}])[0] or {}
    return str((choice.get("message") or {}).get("content") or "")


def probe_provider(model, api_key, base_url, provider, timeout, multimodal=False, disable_thinking=True):
    """探测当前模型的业务请求格式，返回不暴露密钥的能力档案。"""
    provider = normalize_provider(provider, base_url)
    profile = {
        "provider": provider,
        "model": str(model or ""),
        "multimodal": bool(multimodal),
        "ready": False,
        "visionReady": not multimodal,
        "thinkingRequested": bool(disable_thinking),
        "thinkingDisabled": not disable_thinking,
        "removedOptionalFields": [],
        "message": "",
    }
    last_error = None
    for payload, removed in fallback_payloads(provider_probe_payload(model, provider, multimodal, disable_thinking)):
        try:
            data = request_chat_completion(base_url, api_key, timeout, payload)
        except Exception as exc:
            last_error = exc
            continue
        profile["ready"] = True
        profile["visionReady"] = bool(multimodal)
        profile["removedOptionalFields"] = removed
        profile["thinkingDisabled"] = not disable_thinking or not ({"thinking", "enable_thinking"} & set(removed))
        profile["responseContent"] = response_content(data)
        try:
            parsed = json.loads(profile["responseContent"])
            if not isinstance(parsed, dict):
                raise ValueError("模型未返回 JSON 对象")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
        profile["message"] = ""
        return profile
    profile["message"] = str(last_error or "模型接口未返回有效响应")[:300]
    return profile
