"""Agent 会话与记忆的兼容入口。

运行时按模块顺序加载拆分文件；直接导入本模块时复用同一命名空间，便于测试
和旧调用继续访问完整的 Agent 会话 API。
"""

from pathlib import Path as _Path

for _module_name in (
    "agent_memory_base.py",
    "agent_memory_sessions.py",
    "agent_memory_summaries.py",
    "agent_memory_runs.py",
):
    _module_path = _Path(__file__).with_name(_module_name)
    exec(compile(_module_path.read_text(encoding="utf-8"), str(_module_path), "exec"), globals())

del _module_name, _module_path