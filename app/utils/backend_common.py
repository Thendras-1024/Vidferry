"""后端通用工具:兼容旧入口并汇总跨模块共享状态。"""

import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import (
    WORKFLOW_MAX_ANALYSIS_JOBS,
    WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS,
    WORKFLOW_MAX_COMMENT_JOBS,
    WORKFLOW_MAX_COMMENT_QUEUED_JOBS,
    WORKFLOW_MAX_DOWNLOAD_JOBS,
    WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS,
    WORKFLOW_MAX_PROCESSING_JOBS,
    WORKFLOW_MAX_PROCESSING_QUEUED_JOBS,
    WORKFLOW_MAX_PUBLISH_JOBS,
    WORKFLOW_MAX_PUBLISH_QUEUED_JOBS,
    WORKFLOW_MAX_SEARCH_JOBS,
    WORKFLOW_MAX_SEARCH_QUEUED_JOBS,
)
from app.db.base import (
    DATABASE_INTEGRITY_ERRORS,
    _db_connect,
    close_database_pool,
)
from app.utils.file_util import (
    _safe_child_path,
    _safe_cookie_filename,
    _safe_cookie_path,
    _safe_filename,
    safe_rmtree,
    safe_unlink,
)
from app.utils.format_util import (
    _build_default_publish_draft,
    _clean_topic_list,
    _clean_unique_list,
    _format_count,
    _format_iso_date,
    _format_subscribers_w,
    _normalize_publish_tags,
    _now_iso,
    _parse_json_object,
    _parse_publish_draft,
    _parse_upload_date,
    _safe_text,
)
from app.utils.request_util import (
    _error_response,
    _json_response,
    _parse_positive_int,
    _split_request_values,
    _sql_placeholders,
)
from app.utils.render_layout import _render_layout_scales
from app.core.errors import NoSpeechDetectedError, WorkflowConflictError


_publish_account_locks = {}
_publish_account_locks_guard = threading.Lock()
_workflow_executor_limits = {
    "search": (WORKFLOW_MAX_SEARCH_JOBS, WORKFLOW_MAX_SEARCH_QUEUED_JOBS),
    "download": (WORKFLOW_MAX_DOWNLOAD_JOBS, WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS),
    "processing": (WORKFLOW_MAX_PROCESSING_JOBS, WORKFLOW_MAX_PROCESSING_QUEUED_JOBS),
    "publish": (WORKFLOW_MAX_PUBLISH_JOBS, WORKFLOW_MAX_PUBLISH_QUEUED_JOBS),
    "analysis": (WORKFLOW_MAX_ANALYSIS_JOBS, WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS),
    "comment": (WORKFLOW_MAX_COMMENT_JOBS, WORKFLOW_MAX_COMMENT_QUEUED_JOBS),
}
_workflow_executors = {
    resource: ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"vidferry-{resource}")
    for resource, (workers, _queued) in _workflow_executor_limits.items()
}
_workflow_submit_slots = {
    resource: threading.BoundedSemaphore(workers + queued)
    for resource, (workers, queued) in _workflow_executor_limits.items()
}


def _run_background_task(resource, target, args):
    try:
        # 必须返回 target 的结果：analysis 等任务靠 future.result() 把成果交回主流程，
        # 不 return 会导致剪辑阶段拿到空结果、高光片段无法拼接。
        return target(*args)
    except Exception as exc:
        print(
            f"background task failed : target = {getattr(target, '__name__', target)} | error = {exc}",
            flush=True,
        )
        raise
    finally:
        _workflow_submit_slots[resource].release()


def _submit_background_task(resource, target, *args):
    if resource not in _workflow_executors:
        raise ValueError(f"未知后台任务资源 : {resource}")
    slots = _workflow_submit_slots[resource]
    if not slots.acquire(blocking=False):
        workers, queued = _workflow_executor_limits[resource]
        raise RuntimeError(f"{resource} 任务已满（运行 {workers}，排队 {queued}），请稍后重试")
    try:
        return _workflow_executors[resource].submit(_run_background_task, resource, target, args)
    except Exception:
        slots.release()
        raise


def _get_publish_account_lock(platform_type, account_file, account_id=None, owner_user_id=None):
    if account_id is not None:
        key = f"{int(owner_user_id or 0)}:{int(platform_type or 0)}:{int(account_id)}"
    else:
        key = f"legacy:{int(platform_type or 0)}:{_safe_text(account_file)}"
    with _publish_account_locks_guard:
        lock = _publish_account_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _publish_account_locks[key] = lock
        return lock
