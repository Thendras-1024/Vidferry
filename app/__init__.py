"""Vidferry 后端的 Flask 应用工厂。"""

from __future__ import annotations

from importlib import import_module

from app.config import FEISHU_ROBOT_ENABLED
from app.feishu_robot import start_embedded_feishu_robot
from app.utils.text_util import ensure_utf8_stdio


ensure_utf8_stdio()


def _backend():
    return import_module("sau_backend")


def create_app():
    """返回注册了所有模块化路由的 Flask 应用实例。"""
    return _backend().create_app()


def initialize_runtime() -> None:
    """执行后端启动钩子,与正式入口 ``run.py`` 共用。"""
    backend = _backend()
    backend.init_youtube_video_table()
    recovered_jobs = backend.recover_interrupted_workflow_jobs()
    if recovered_jobs:
        print(f"启动恢复：已标记 {len(recovered_jobs)} 个历史中断任务为异常")
    recovered_search_jobs = backend.recover_interrupted_youtube_search_jobs()
    if recovered_search_jobs:
        print(f"启动恢复：已标记 {len(recovered_search_jobs)} 个历史检索任务为失败")
    reconciled_events = backend.reconcile_finished_workflow_events()
    if reconciled_events:
        print(f"启动修复：已收口 {len(reconciled_events)} 个历史任务的阶段记录")
    backend.normalize_existing_youtube_subscribers()
    backend.start_scheduled_publish_scheduler()
    backend.install_workflow_shutdown_handlers()
    start_embedded_feishu_robot(
        FEISHU_ROBOT_ENABLED,
        backend.run_agent_chat,
        image_roots=(backend.BASE_DIR,),
        sanitize=backend.sanitize_agent_output,
    )
