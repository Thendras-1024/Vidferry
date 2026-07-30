"""模块化 Vidferry 后端的兼容入口。"""

from __future__ import annotations

from app.utils.text_util import ensure_utf8_stdio


ensure_utf8_stdio()

from app.backend.runtime import load_backend_namespace
from app.config import HOST, PORT

load_backend_namespace(globals())


def create_app():
    """返回加载了所有模块化路由的 Flask 应用。"""
    init_youtube_workflow_table()
    return app


if __name__ == "__main__":
    init_youtube_video_table()
    recovered_jobs = recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    recovered_search_jobs = recover_interrupted_youtube_search_jobs()
    if recovered_search_jobs:
        print(f"启动恢复：已标记 {len(recovered_search_jobs)} 个历史检索任务为失败")
    normalize_existing_youtube_subscribers()
    start_scheduled_publish_scheduler()
    install_workflow_shutdown_handlers()
    app.run(host=HOST, port=PORT)
