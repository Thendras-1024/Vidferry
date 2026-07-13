"""Agent 对话安全策略:拒绝违法、越权、泄密与 prompt injection 请求。"""

from __future__ import annotations

import os as _os
import re as _re


_AGENT_SECRET_PATTERNS = [
    _re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    _re.compile(r"(?i)(api[_-]?key|token|cookie|secret|authorization)\s*[:=]\s*[^\s,;]+"),
    _re.compile(r"(?i)(LLM_API_KEY|OPENAI_API_KEY|AGENT_[A-Z0-9_]*KEY)\s*[:=]\s*[^\s,;]+"),
]

_AGENT_ABSOLUTE_PATH_PATTERN = _re.compile(r"(?i)\b[A-Z]:\\[^\s\"'，。；;]+")

_AGENT_POLICY_RULES = [
    (
        "secret_exfiltration",
        ["api key", "apikey", "密钥", "token", "cookie", "凭证", "authorization", "环境变量", ".env"],
        ["输出", "显示", "打印", "泄露", "给我", "查看", "读取", "导出", "完整"],
        "我不能帮助读取、输出或导出 API Key、Cookie、Token、环境变量等敏感凭证。",
    ),
    (
        "prompt_injection",
        ["忽略", "无视", "覆盖", "绕过", "system prompt", "系统提示词", "开发者指令", "上面的规则", "之前的指令"],
        ["执行", "照做", "输出", "泄露", "改成", "不要遵守", "解除限制"],
        "我不能执行要求忽略系统规则、覆盖安全边界或泄露内部指令的请求。",
    ),
    (
        "illegal_or_abuse",
        ["诈骗", "盗号", "撞库", "洗钱", "赌博", "毒品", "木马", "钓鱼", "后门", "爆破", "绕过风控", "规避风控", "封号检测"],
        ["教我", "怎么", "帮我", "实现", "生成", "编写", "自动化", "绕过", "攻击", "破解"],
        "我不能帮助实施违法、侵害账号安全、绕过平台风控或恶意自动化的行为。",
    ),
    (
        "unauthorized_action",
        ["发布", "删除", "登录", "改数据库", "修改数据库", "写库", "删库", "上传", "发出去", "重启后端", "启动服务"],
        ["直接", "现在", "替我", "帮我执行", "自动执行", "立即执行"],
        "当前 Agent 是只读运营助手，不能直接发布、删除、登录、修改数据库或启动/重启服务。",
    ),
]


def _contains_any(text, words):
    return any(word and word.lower() in text for word in words)


def agent_policy_check(message, context=None):
    text = str(message or "").strip()
    lowered = text.lower()
    if not text:
        return {
            "allowed": False,
            "category": "empty",
            "reason": "用户问题为空。",
            "message": "请输入要询问 Agent 的内容。",
        }

    for category, intent_words, action_words, message_text in _AGENT_POLICY_RULES:
        if _contains_any(lowered, intent_words) and _contains_any(lowered, action_words):
            return {
                "allowed": False,
                "category": category,
                "reason": message_text,
                "message": f"{message_text}我可以提供合规的查询、解释或风险排查建议。",
            }

    return {
        "allowed": True,
        "category": "normal",
        "reason": "",
        "message": "",
    }


def sanitize_agent_output(value):
    text = str(value or "")
    for pattern in _AGENT_SECRET_PATTERNS:
        text = pattern.sub("[已隐藏敏感凭证]", text)
    text = _AGENT_ABSOLUTE_PATH_PATTERN.sub(lambda match: _os.path.basename(match.group(0).replace("\\", "/")) or "[已隐藏本机路径]", text)
    return text
