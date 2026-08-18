"""Agent 会话、短期上下文和记忆条目的持久化。"""


from __future__ import annotations

import datetime as _dt
import json as _json
import logging as _logging
import threading as _threading
import time as _time
import uuid as _uuid
import weakref as _weakref
from contextlib import contextmanager as _contextmanager
from contextvars import ContextVar as _ContextVar


_CONTEXT_RECENT_MESSAGES = max(2, int(globals().get("AGENT_CONTEXT_RECENT_MESSAGES", 8) or 8))
_CONTEXT_COMPACT_AFTER_MESSAGES = max(4, int(globals().get("AGENT_CONTEXT_COMPACT_AFTER_MESSAGES", 12) or 12))
_CONTEXT_COMPACT_AFTER_CHARS = max(4000, int(globals().get("AGENT_CONTEXT_COMPACT_AFTER_CHARS", 16000) or 16000))
_CONTEXT_SUMMARY_MAX_CHARS = max(500, int(globals().get("AGENT_CONTEXT_SUMMARY_MAX_CHARS", 4000) or 4000))
_LONGCAT_CONTEXT_WINDOW_TOKENS = 1_048_576
_CONTEXT_COMPACT_USAGE_RATIO = 0.8
_AGENT_SESSION_LOCK_LEASE_SECONDS = max(300, int(globals().get("LLM_TIMEOUT", 180) or 180) * 2 + 60)
_AGENT_SESSION_LOCK_WAIT_SECONDS = 30
_AGENT_SESSION_LOCKS = _weakref.WeakValueDictionary()
_AGENT_SESSION_LOCKS_GUARD = _threading.Lock()
_AGENT_SESSION_GUARD_STATE = _threading.local()
_AGENT_ACTOR_USER_ID = _ContextVar("agent_actor_user_id", default=None)
_AGENT_SOURCE_WEB = "web"
_AGENT_SOURCE_FEISHU = "feishu"


def _agent_now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def _agent_json_default(value):
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _agent_json_dumps(value):
    return _json.dumps(
        value if value is not None else {},
        ensure_ascii=False,
        separators=(",", ":"),
        default=_agent_json_default,
    )


def _agent_json_loads(value, fallback=None):
    try:
        return _json.loads(value or "{}")
    except (TypeError, ValueError, _json.JSONDecodeError):
        return fallback if fallback is not None else {}


def _agent_new_id(prefix="agent"):
    return f"{prefix}_{_uuid.uuid4().hex}"


def _acquire_agent_session_lease(session_id):
    owner_id = _agent_new_id("lease")
    deadline = _time.monotonic() + _AGENT_SESSION_LOCK_WAIT_SECONDS
    while True:
        with _db_connect() as conn:
            now = _time.time()
            conn.execute("DELETE FROM agent_session_locks WHERE expires_at <= %s", (now,))
            cursor = conn.execute(
                """
                INSERT INTO agent_session_locks (session_id, owner_id, expires_at)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (session_id, owner_id, now + _AGENT_SESSION_LOCK_LEASE_SECONDS),
            )
            if cursor.rowcount == 1:
                conn.commit()
                return owner_id
            conn.rollback()
        if _time.monotonic() >= deadline:
            raise TimeoutError("Agent 会话正被另一个请求占用，请稍后重试。")
        _time.sleep(0.05)


def _release_agent_session_lease(session_id, owner_id):
    if not owner_id:
        return
    try:
        with _db_connect() as conn:
            conn.execute(
                "DELETE FROM agent_session_locks WHERE session_id = %s AND owner_id = %s",
                (session_id, owner_id),
            )
            conn.commit()
    except Exception:
        _logging.exception("Agent 会话租约释放失败 session=%s", session_id)


def renew_agent_session_lease(session_id):
    """续期当前线程持有的会话租约，避免长模型调用后并发写入。"""
    key = str(session_id or "").strip()
    active = getattr(_AGENT_SESSION_GUARD_STATE, "active", {})
    state = active.get(key)
    owner_id = state[0] if state else None
    if not owner_id:
        return True
    with _db_connect() as conn:
        cursor = conn.execute(
            "UPDATE agent_session_locks SET expires_at = %s WHERE session_id = %s AND owner_id = %s",
            (_time.time() + _AGENT_SESSION_LOCK_LEASE_SECONDS, key, owner_id),
        )
        conn.commit()
    return cursor.rowcount == 1


@_contextmanager
def agent_session_guard(session_id):
    """单进程 RLock + 跨进程数据库租约，模型调用期间不持有数据库写事务。"""
    key = str(session_id or "").strip() or _agent_new_id("new_session_lock")
    with _AGENT_SESSION_LOCKS_GUARD:
        lock = _AGENT_SESSION_LOCKS.setdefault(key, _threading.RLock())
    with lock:
        active = getattr(_AGENT_SESSION_GUARD_STATE, "active", None)
        if active is None:
            active = {}
            _AGENT_SESSION_GUARD_STATE.active = active
        state = active.get(key)
        if state:
            active[key] = (state[0], state[1] + 1)
            try:
                yield
            finally:
                active[key] = (state[0], state[1])
            return

        owner_id = None if key.startswith("new_session_lock_") else _acquire_agent_session_lease(key)
        active[key] = (owner_id, 1)
        try:
            yield
        finally:
            active.pop(key, None)
            _release_agent_session_lease(key, owner_id)


def _agent_text(value, limit=1200):
    text = str(value or "").strip()
    sanitizer = globals().get("sanitize_agent_output")
    if callable(sanitizer):
        text = sanitizer(text)
    return text[:limit] + ("..." if len(text) > limit else "")


def _estimate_agent_tokens(value):
    """保守估算中文与混合文本的上下文 token，仅用于界面提示。"""
    text = str(value or "")
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk + max(1, (len(text) - cjk + 3) // 4)


def _agent_current_user_id():
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, "current_user", None):
            return int(g.current_user["id"])
    except (KeyError, TypeError, ValueError):
        pass
    return _AGENT_ACTOR_USER_ID.get()


@_contextmanager
def agent_actor(owner_user_id=None):
    """为飞书等非 HTTP 调用提供与网页请求一致的会话归属。"""
    if owner_user_id is None:
        yield
        return
    try:
        value = int(owner_user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Agent 会话归属账号必须是正整数。") from exc
    if value <= 0:
        raise ValueError("Agent 会话归属账号必须是正整数。")
    token = _AGENT_ACTOR_USER_ID.set(value)
    try:
        yield
    finally:
        _AGENT_ACTOR_USER_ID.reset(token)


def _agent_source(value):
    return _AGENT_SOURCE_FEISHU if str(value or "").strip() == _AGENT_SOURCE_FEISHU else _AGENT_SOURCE_WEB


def _agent_source_from_context(context):
    return _agent_source(context.get("source") if isinstance(context, dict) else "")


def _agent_owner_filter(owner_user_id, column="owner_user_id"):
    if owner_user_id is None:
        return "", ()
    return f" AND {column} = %s", (owner_user_id,)


def _active_session_row(cursor, session_id):
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id)
    cursor.execute(
        f"SELECT * FROM agent_sessions WHERE id = %s AND deleted_at IS NULL{owner_filter}",
        (str(session_id or "").strip(),) + owner_values,
    )
    return cursor.fetchone()

