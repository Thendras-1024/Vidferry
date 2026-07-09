"""子进程命令执行辅助函数。"""

import os
import shlex
import subprocess

from app.config import BASE_DIR


def _run_command(command, cwd=None, timeout=None):
    if isinstance(command, str):
        command = [
            item.strip('"').strip("'")
            for item in shlex.split(command, posix=(os.name != "nt"))
            if item.strip('"').strip("'")
        ]
    if not command:
        raise RuntimeError("命令不能为空")
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    result = subprocess.run(
        command,
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        env=env,
    )
    output = "\n".join(part for part in [(result.stdout or "").strip(), (result.stderr or "").strip()] if part)
    if result.returncode != 0:
        display_command = " ".join(map(str, command))
        raise RuntimeError(output or f"命令执行失败: {display_command}")
    return result
