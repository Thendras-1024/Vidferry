"""后端通用工具:兼容旧入口并汇总跨模块共享状态。"""

import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

from app.config import (
    WORKFLOW_MAX_ANALYSIS_JOBS,
    WORKFLOW_MAX_DOWNLOAD_JOBS,
    WORKFLOW_MAX_PROCESSING_JOBS,
    WORKFLOW_MAX_SEARCH_JOBS,
)
from app.db.base import _connect_database, _db_path
from app.utils.file_util import (
    _safe_child_path,
    _safe_cookie_filename,
    _safe_cookie_path,
    _safe_filename,
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
from app.core.errors import NoSpeechDetectedError, WorkflowConflictError


@contextmanager
def _db_connect(*, row_factory=False):
    conn = _connect_database(_db_path(), row_factory=row_factory)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


_publish_account_locks = {}
_publish_account_locks_guard = threading.Lock()
_workflow_executors = {
    "search": ThreadPoolExecutor(max_workers=WORKFLOW_MAX_SEARCH_JOBS, thread_name_prefix="vidferry-search"),
    "download": ThreadPoolExecutor(max_workers=WORKFLOW_MAX_DOWNLOAD_JOBS, thread_name_prefix="vidferry-download"),
    "processing": ThreadPoolExecutor(max_workers=WORKFLOW_MAX_PROCESSING_JOBS, thread_name_prefix="vidferry-processing"),
    "analysis": ThreadPoolExecutor(max_workers=WORKFLOW_MAX_ANALYSIS_JOBS, thread_name_prefix="vidferry-analysis"),
}


def _run_background_task(target, args):
    try:
        target(*args)
    except Exception as exc:
        print(f"后台任务未捕获异常: {getattr(target, '__name__', target)} {exc}", flush=True)


def _submit_background_task(resource, target, *args):
    executor = _workflow_executors.get(resource) or _workflow_executors["processing"]
    return executor.submit(_run_background_task, target, args)


def _get_publish_account_lock(platform_type, account_file):
    key = f"{int(platform_type or 0)}:{_safe_text(account_file)}"
    with _publish_account_locks_guard:
        lock = _publish_account_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _publish_account_locks[key] = lock
        return lock
