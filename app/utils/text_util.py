"""文本输出与展示清理工具。"""

from __future__ import annotations

import os
import re
import sys


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Older releases contained a few publish-state strings that had already been
# saved as mojibake literals. Repair those exact fragments at the shared display
# boundary so existing database records are readable as well as new ones.
KNOWN_MOJIBAKE_FRAGMENTS = {
    "璇ヨ棰戝凡鍙戝竷鎴栨鍦ㄥ彂甯冨埌": "该视频已发布或正在发布到",
    "涓嶈兘閲嶅鍙戝竷": "不能重复发布",
}


def ensure_utf8_stdio() -> None:
    """让项目入口和子进程默认使用 UTF-8 输出，避免 Windows 控制台乱码。"""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def clean_display_text(value) -> str:
    """清理适合写入数据库或返回前端展示的文本。"""
    if value is None:
        return ""
    text = str(value)
    for garbled, readable in KNOWN_MOJIBAKE_FRAGMENTS.items():
        text = text.replace(garbled, readable)
    text = ANSI_ESCAPE_RE.sub("", text)
    text = text.replace("\r", "")
    text = CONTROL_CHARS_RE.sub("", text)
    return text.strip()
