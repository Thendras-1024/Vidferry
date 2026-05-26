"""Flask application factory for the modular backend transition.

Routes and services are still provided by ``sau_backend`` during the first
migration phase. New modules should move business code out of that file
domain by domain while keeping this factory stable.
"""

from __future__ import annotations

from importlib import import_module


def _legacy_backend():
    return import_module("sau_backend")


def create_app():
    """Return the Flask app instance with all current routes registered."""
    return _legacy_backend().app


def initialize_runtime() -> None:
    """Run backend startup hooks shared by the formal ``run.py`` entry."""
    backend = _legacy_backend()
    backend.init_youtube_video_table()
    recovered_jobs = backend.recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    backend.normalize_existing_youtube_subscribers()
    backend.install_workflow_shutdown_handlers()
