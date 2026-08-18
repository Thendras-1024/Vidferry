"""后端通用工具:兼容旧入口并汇总跨模块共享状态。"""

import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

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
    CANDIDATE_ANALYSIS_MAX_JOBS,
    CANDIDATE_ANALYSIS_MAX_QUEUED_JOBS,
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
from app.core.errors import BackgroundQueueFullError, NoSpeechDetectedError, WorkflowConflictError


_publish_account_locks = {}
_publish_account_locks_guard = threading.Lock()
_workflow_executor_limits = {
    "search": (WORKFLOW_MAX_SEARCH_JOBS, WORKFLOW_MAX_SEARCH_QUEUED_JOBS),
    "download": (WORKFLOW_MAX_DOWNLOAD_JOBS, WORKFLOW_MAX_DOWNLOAD_QUEUED_JOBS),
    "processing": (WORKFLOW_MAX_PROCESSING_JOBS, WORKFLOW_MAX_PROCESSING_QUEUED_JOBS),
    "publish": (WORKFLOW_MAX_PUBLISH_JOBS, WORKFLOW_MAX_PUBLISH_QUEUED_JOBS),
    "analysis": (WORKFLOW_MAX_ANALYSIS_JOBS, WORKFLOW_MAX_ANALYSIS_QUEUED_JOBS),
    "comment": (WORKFLOW_MAX_COMMENT_JOBS, WORKFLOW_MAX_COMMENT_QUEUED_JOBS),
    "candidate_analysis": (CANDIDATE_ANALYSIS_MAX_JOBS, CANDIDATE_ANALYSIS_MAX_QUEUED_JOBS),
}
_workflow_executors = {
    resource: ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"vidferry-{resource}")
    for resource, (workers, _queued) in _workflow_executor_limits.items()
}
_workflow_submit_slots = {
    resource: threading.BoundedSemaphore(workers + queued)
    for resource, (workers, queued) in _workflow_executor_limits.items()
}
_workflow_owner_pending = {resource: {} for resource in _workflow_executors}
_workflow_owner_queues = {resource: {} for resource in _workflow_executors}
_workflow_owner_order = {resource: deque() for resource in _workflow_executors}
_workflow_active_counts = {resource: 0 for resource in _workflow_executors}
_workflow_last_owner = {resource: None for resource in _workflow_executors}
_workflow_owner_pending_guard = threading.Lock()


def _dispatch_background_tasks_locked(resource):
    workers, _queued = _workflow_executor_limits[resource]
    owner_queues = _workflow_owner_queues[resource]
    owner_order = _workflow_owner_order[resource]
    while _workflow_active_counts[resource] < workers and owner_order:
        if len(owner_order) > 1 and owner_order[0] == _workflow_last_owner[resource]:
            owner_order.rotate(-1)
        owner_user_id = owner_order.popleft()
        owner_queue = owner_queues.get(owner_user_id)
        if not owner_queue:
            owner_queues.pop(owner_user_id, None)
            continue
        future, target, args = owner_queue.popleft()
        if owner_queue:
            owner_order.append(owner_user_id)
        else:
            owner_queues.pop(owner_user_id, None)
        _workflow_active_counts[resource] += 1
        _workflow_last_owner[resource] = owner_user_id
        _workflow_executors[resource].submit(
            _run_background_task, resource, owner_user_id, target, args, future
        )


def _run_background_task(resource, owner_user_id, target, args, future):
    try:
        if not future.set_running_or_notify_cancel():
            return None
        # 必须返回 target 的结果：analysis 等任务靠 future.result() 把成果交回主流程，
        # 不 return 会导致剪辑阶段拿到空结果、高光片段无法拼接。
        result = target(*args)
        future.set_result(result)
        return result
    except Exception as exc:
        print(
            f"background task failed : target = {getattr(target, '__name__', target)} | error_type = {type(exc).__name__}",
            flush=True,
        )
        future.set_exception(exc)
        return None
    finally:
        _workflow_submit_slots[resource].release()
        with _workflow_owner_pending_guard:
            pending = _workflow_owner_pending[resource]
            pending[owner_user_id] = max(0, pending.get(owner_user_id, 1) - 1)
            if not pending[owner_user_id]:
                pending.pop(owner_user_id, None)
            _workflow_active_counts[resource] = max(0, _workflow_active_counts[resource] - 1)
            _dispatch_background_tasks_locked(resource)


def _submit_background_task(resource, target, *args, owner_user_id=None):
    if resource not in _workflow_executors:
        raise ValueError(f"未知后台任务资源 : {resource}")
    slots = _workflow_submit_slots[resource]
    if owner_user_id is None:
        raise ValueError(f"后台任务必须传入 owner : resource = {resource}")
    workers, queued = _workflow_executor_limits[resource]
    owner_pending_limit = workers + max(1, queued // 2)
    if not slots.acquire(blocking=False):
        raise BackgroundQueueFullError(resource, "global")
    owner_user_id = int(owner_user_id)
    future = Future()
    try:
        with _workflow_owner_pending_guard:
            pending = _workflow_owner_pending[resource]
            if pending.get(owner_user_id, 0) >= owner_pending_limit:
                raise BackgroundQueueFullError(resource, "owner")
            pending[owner_user_id] = pending.get(owner_user_id, 0) + 1
            owner_queues = _workflow_owner_queues[resource]
            if owner_user_id not in owner_queues:
                owner_queues[owner_user_id] = deque()
                _workflow_owner_order[resource].append(owner_user_id)
            owner_queues[owner_user_id].append((future, target, args))
            _dispatch_background_tasks_locked(resource)
        return future
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
