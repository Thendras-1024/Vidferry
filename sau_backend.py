"""Compatibility entrypoint for the modular Vidferry backend."""

from __future__ import annotations

from app.backend.runtime import load_backend_namespace
from app.config import HOST, PORT

load_backend_namespace(globals())


def create_app():
    """Return the Flask application with all modular routes loaded."""
    return app


if __name__ == "__main__":
    init_youtube_video_table()
    recovered_jobs = recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    normalize_existing_youtube_subscribers()
    install_workflow_shutdown_handlers()
    app.run(host=HOST, port=PORT)
