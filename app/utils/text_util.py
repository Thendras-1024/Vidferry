"""文本输出与展示清理工具。"""

from __future__ import annotations

import os
import re
import sys


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
    text = ANSI_ESCAPE_RE.sub("", text)
    text = text.replace("\r", "")
    text = CONTROL_CHARS_RE.sub("", text)
    return text.strip()
