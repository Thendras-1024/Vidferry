"""Agent 会话、消息、运行记录与记忆条目的持久化(agent_* 表)。"""


from __future__ import annotations

import datetime as _dt
import json as _json
import time as _time
import uuid as _uuid


def _agent_now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def _agent_json_dumps(value):
    return _json.dumps(value or {}, ensure_ascii=False)


def _agent_json_loads(value, fallback=None):
    try:
        return _json.loads(value or "{}")
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}


def _agent_new_id(prefix="agent"):
    return f"{prefix}_{_uuid.uuid4().hex}"


def ensure_agent_session(session_id="", title="", context=None):
    init_database_tables()
    session_id = str(session_id or "").strip() or _agent_new_id("session")
    now = _agent_now_iso()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM agent_sessions WHERE id = ?", (session_id,))
        if cursor.fetchone():
            cursor.execute(
                "UPDATE agent_sessions SET context = ?, updated_at = ? WHERE id = ?",
                (_agent_json_dumps(context), now, session_id),
            )
        else:
            cursor.execute(
                "INSERT INTO agent_sessions (id, title, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title or "Vidferry Agent", _agent_json_dumps(context), now, now),
            )
        conn.commit()
    return session_id


def save_agent_message(session_id, role, content, context=None):
    init_database_tables()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agent_messages (session_id, role, content, context, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, str(content or ""), _agent_json_dumps(context), _agent_now_iso()),
        )
        cursor.execute("UPDATE agent_sessions SET updated_at = ? WHERE id = ?", (_agent_now_iso(), session_id))
        conn.commit()
        return cursor.lastrowid


def list_agent_messages(session_id, limit=12):
    init_database_tables()
    limit = max(1, min(int(limit or 12), 30))
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM agent_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = list(reversed(cursor.fetchall()))
        return [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "context": _agent_json_loads(row["context"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


def save_agent_run(
    run_type,
    *,
    session_id="",
    status="success",
    decision="",
    severity="",
    content_hash="",
    input_summary=None,
    output=None,
    model="",
    started_at=None,
):
    init_database_tables()
    run_id = _agent_new_id("run")
    duration_ms = int((_time.time() - started_at) * 1000) if started_at else 0
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO agent_runs (
                id, session_id, run_type, status, decision, severity, content_hash,
                input_summary, output, model, duration_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                session_id or "",
                run_type,
                status,
                decision or "",
                severity or "",
                content_hash or "",
                _agent_json_dumps(input_summary),
                _agent_json_dumps(output),
                model or "",
                duration_ms,
                _agent_now_iso(),
            ),
        )
        conn.commit()
    return run_id


def get_agent_run(run_id):
    init_database_tables()
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "sessionId": row["session_id"] or "",
            "type": row["run_type"],
            "status": row["status"],
            "decision": row["decision"] or "",
            "severity": row["severity"] or "",
            "contentHash": row["content_hash"] or "",
            "inputSummary": _agent_json_loads(row["input_summary"]),
            "output": _agent_json_loads(row["output"]),
            "model": row["model"] or "",
            "durationMs": int(row["duration_ms"] or 0),
            "createdAt": row["created_at"] or "",
        }


def list_agent_memory(memory_type="", limit=8):
    init_database_tables()
    limit = max(1, min(int(limit or 8), 20))
    where = ""
    values = []
    if memory_type:
        where = "WHERE memory_type = ?"
        values.append(memory_type)
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT * FROM agent_memory_items
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            values + [limit],
        )
        return [
            {
                "id": row["id"],
                "type": row["memory_type"],
                "title": row["title"] or "",
                "content": row["content"] or "",
                "metadata": _agent_json_loads(row["metadata"]),
                "updatedAt": row["updated_at"] or row["created_at"] or "",
            }
            for row in cursor.fetchall()
        ]

