"""Flask application factory for the Vidferry backend."""

from __future__ import annotations

from importlib import import_module


def _backend():
    return import_module("sau_backend")


def create_app():
    """Return the Flask app instance with all modular routes registered."""
    return _backend().create_app()


def initialize_runtime() -> None:
    """Run backend startup hooks shared by the formal ``run.py`` entry."""
    backend = _backend()
    backend.init_youtube_video_table()
    recovered_jobs = backend.recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    backend.normalize_existing_youtube_subscribers()
    backend.install_workflow_shutdown_handlers()
