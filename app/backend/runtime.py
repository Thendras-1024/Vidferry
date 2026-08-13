"""模块化旧后端的运行时加载器。

旧后端曾是单个文件,内部函数大量互相调用。在模块化过渡期间,我们把拆分后的
领域模块执行到同一个命名空间里,使路由和服务保持原有行为,同时源码不再是
单体大文件。
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

MODULE_ORDER = [
    "app/backend/setup.py",
    "app/utils/backend_common.py",
    "app/core/publish_state.py",
    "app/db/schema.py",
    "app/core/notification_service.py",
    "app/core/youtube_group_service.py",
    "app/core/youtube_service.py",
    "app/core/workflow.py",
    "app/core/workflow_usage_service.py",
    "app/core/task_center_service.py",
    "app/core/subtitle_audit_service.py",
    "app/core/youtube_download_service.py",
    "app/core/settings_service.py",
    "app/core/account_group_service.py",
    "app/core/subtitle_service.py",
    "app/core/llm_harness.py",
    "app/core/llm_prompts.py",
    "app/core/content_safety_service.py",
    "app/core/comment_burn_service.py",
    "app/core/editing_service.py",
    "app/core/material_service.py",
    "app/core/agent_memory_base.py",
    "app/core/agent_memory_sessions.py",
    "app/core/agent_memory_summaries.py",
    "app/core/agent_memory_runs.py",
    "app/core/agent_skill_loader.py",
    "app/core/kuaishou_analytics_adapter.py",
    "app/core/kuaishou_analytics_service.py",
    "app/core/agent_kuaishou_analytics.py",
    "app/core/agent_tools.py",
    "app/core/agent_policy.py",
    "app/core/agent_orchestrator.py",
    "app/core/prepublish_guard.py",
    "app/core/publish_execution.py",
    "app/core/publish_dispatch_service.py",
    "app/core/publish_retry_service.py",
    "app/core/scheduled_publish_service.py",
    "app/core/scheduled_publish_scheduler.py",
    "app/core/workflow_runner.py",
    "app/core/youtube_search_service.py",
    "app/core/short_video_service.py",
    "app/api/common.py",
    "app/api/task_center.py",
    "app/api/auth.py",
    "app/api/admin_users.py",
    "app/api/notification.py",
    "app/api/static.py",
    "app/api/upload.py",
    "app/api/youtube_groups.py",
    "app/api/subtitle_audit.py",
    "app/api/youtube.py",
    "app/api/short_video.py",
    "app/api/material.py",
    "app/api/publish_records.py",
    "app/api/agent.py",
    "app/api/account.py",
    "app/api/account_groups.py",
    "app/api/login.py",
    "app/api/publish.py",
    "app/api/cookie.py",
    "app/utils/sse.py",
    "app/backend/shutdown.py",
]


def load_backend_namespace(target_globals: dict, repo_root: Path | None = None) -> dict:
    root = repo_root or Path(__file__).resolve().parents[2]
    target_globals.setdefault("__file__", str(root / "sau_backend.py"))
    target_globals.setdefault("__name__", "sau_backend")
    target_globals.setdefault("__package__", "")
    target_globals.setdefault("__builtins__", __builtins__)

    for relative_path in MODULE_ORDER:
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root.resolve()):
            raise RuntimeError(f"拒绝加载仓库目录外的后端模块: {relative_path}")
        source = path.read_text(encoding="utf-8-sig")
        code = compile(source, str(path), "exec")
        exec(code, target_globals)
    return target_globals


def create_backend_module(name: str = "sau_backend") -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(Path(__file__).resolve().parents[2] / "sau_backend.py")
    load_backend_namespace(module.__dict__)
    return module
