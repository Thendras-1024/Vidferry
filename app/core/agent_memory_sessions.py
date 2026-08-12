def ensure_agent_session(session_id="", title="", context=None, source=""):
    session_id = str(session_id or "").strip() or _agent_new_id("session")
    now = _agent_now_iso()
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            cursor.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row and owner_user_id is not None and row["owner_user_id"] != owner_user_id:
                session_id = _agent_new_id("session")
                row = None
            if row and row["deleted_at"]:
                session_id = _agent_new_id("session")
                row = None
            if row:
                existing_context = _agent_json_loads(row["context"])
                merged_context = dict(existing_context) if isinstance(existing_context, dict) else {}
                if isinstance(context, dict):
                    merged_context.update(context)
                merged_context_text = _agent_json_dumps(merged_context)
                if merged_context_text != (row["context"] or "{}"):
                    cursor.execute(
                        """
                        UPDATE agent_sessions
                        SET context = ?, updated_at = ?
                        WHERE id = ? AND deleted_at IS NULL
                        """,
                        (merged_context_text, now, session_id),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Agent 会话不存在或已删除。")
            else:
                cursor.execute(
                    """
                    INSERT INTO agent_sessions (
                        id, owner_user_id, source, title, context, summary, summary_through_id,
                        message_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, '{}', 0, 0, ?, ?)
                    """,
                    (
                        session_id,
                        owner_user_id,
                        _agent_source(source or _agent_source_from_context(context)),
                        title or "Vidferry Agent",
                        _agent_json_dumps(context),
                        now,
                        now,
                    ),
                )
            conn.commit()
    return session_id


def _insert_agent_message(cursor, session_id, role, content, context=None):
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id)
    cursor.execute(
        f"""
        INSERT INTO agent_messages (session_id, role, content, context, created_at)
        SELECT ?, ?, ?, ?, ?
        WHERE EXISTS (
            SELECT 1 FROM agent_sessions WHERE id = ? AND deleted_at IS NULL{owner_filter}
        )
        RETURNING id
        """,
        (
            session_id,
            role,
            str(content or ""),
            _agent_json_dumps(context),
            _agent_now_iso(),
            session_id,
        ) + owner_values,
    )
    message_row = cursor.fetchone()
    if not message_row:
        raise ValueError("Agent 会话不存在或已删除。")
    message_id = message_row[0]
    cursor.execute(
        f"""
        UPDATE agent_sessions
        SET title = CASE
                WHEN COALESCE(message_count, 0) = 0 AND ? = 'user' THEN substr(?, 1, 64)
                ELSE title
            END,
            message_count = COALESCE(message_count, 0) + 1,
            updated_at = ?
        WHERE id = ? AND deleted_at IS NULL{owner_filter}
        """,
        (role, _agent_text(content, 64) or "Vidferry Agent", _agent_now_iso(), session_id) + owner_values,
    )
    if cursor.rowcount != 1:
        raise ValueError("Agent 会话在消息保存期间被删除。")
    return message_id


def save_agent_message(session_id, role, content, context=None):
    session_id = str(session_id or "").strip()
    with agent_session_guard(session_id):
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            message_id = _insert_agent_message(conn.cursor(), session_id, role, content, context)
            conn.commit()
            return message_id


def update_agent_proposal_state(
    session_id,
    proposal_id,
    proposal_key,
    status,
    *,
    selected_ids=None,
    selected_account_ids=None,
    scheduled_at="",
    result_message="",
    workflow_jobs=None,
    analysis_jobs=None,
    processing_options=None,
):
    """Persist a confirmation result on the assistant message that created the proposal."""
    session_id = str(session_id or "").strip()
    proposal_id = str(proposal_id or "").strip()
    proposal_key = str(proposal_key or "").strip()
    if not session_id or not proposal_id or not proposal_key:
        return False
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id, "s.owner_user_id")
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT m.id, m.context
                FROM agent_messages AS m
                JOIN agent_sessions AS s ON s.id = m.session_id
                WHERE m.session_id = ? AND m.role = 'assistant' AND s.deleted_at IS NULL
                  {owner_filter}
                ORDER BY m.id DESC
                """,
                (session_id, *owner_values),
            )
            for row in cursor.fetchall():
                context = _agent_json_loads(row["context"], {})
                context = dict(context) if isinstance(context, dict) else {}
                proposal = context.get(proposal_key)
                if not isinstance(proposal, dict) or proposal.get("proposalId") != proposal_id:
                    continue
                proposal = dict(proposal)
                proposal["status"] = str(status or "confirmed")
                proposal["selectedIds"] = [str(value) for value in (selected_ids or []) if str(value)]
                proposal["selectedAccountIds"] = [int(value) for value in (selected_account_ids or []) if str(value).strip()]
                proposal["scheduledAt"] = str(scheduled_at or proposal.get("scheduledAt") or "")
                proposal["resultMessage"] = str(result_message or "")
                if processing_options is not None:
                    proposal["processingOptions"] = {
                        "watermarkEnabled": bool(processing_options.get("watermarkEnabled")),
                        "commentBurnEnabled": bool(processing_options.get("commentBurnEnabled")),
                    }
                proposal["workflowJobs"] = [
                    {
                        "id": str(item.get("id") or ""),
                        "videoId": str(item.get("videoId") or ""),
                        "title": str(item.get("title") or ""),
                    }
                    for item in (workflow_jobs or [])
                    if isinstance(item, dict) and item.get("id")
                ]
                if analysis_jobs is not None:
                    proposal["analysisJobs"] = [
                        {
                            "id": str(item.get("id") or ""),
                            "videoId": str(item.get("videoId") or ""),
                            "title": str(item.get("title") or ""),
                            "status": str(item.get("status") or "queued"),
                        }
                        for item in analysis_jobs
                        if isinstance(item, dict) and item.get("id")
                    ]
                context[proposal_key] = proposal
                cursor.execute(
                    "UPDATE agent_messages SET context = ? WHERE id = ?",
                    (_agent_json_dumps(context), row["id"]),
                )
                conn.commit()
                return True
    return False


def start_agent_turn(session_id="", message="", context=None):
    """在一个短事务中确保会话并保存本轮用户消息。"""
    session_id = str(session_id or "").strip() or _agent_new_id("session")
    now = _agent_now_iso()
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            cursor.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row and owner_user_id is not None and row["owner_user_id"] != owner_user_id:
                session_id = _agent_new_id("session")
                row = None
            if row and row["deleted_at"]:
                session_id = _agent_new_id("session")
                row = None
            is_first_user_message = not row or int(row["message_count"] or 0) == 0
            if row:
                existing_context = _agent_json_loads(row["context"])
                merged_context = dict(existing_context) if isinstance(existing_context, dict) else {}
                if isinstance(context, dict):
                    merged_context.update(context)
                merged_context_text = _agent_json_dumps(merged_context)
                if merged_context_text != (row["context"] or "{}"):
                    cursor.execute(
                        "UPDATE agent_sessions SET context = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                        (merged_context_text, now, session_id),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO agent_sessions (
                        id, owner_user_id, source, title, context, summary, summary_through_id,
                        message_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, '{}', 0, 0, ?, ?)
                    """,
                    (
                        session_id,
                        owner_user_id,
                        _agent_source_from_context(context),
                        "Vidferry Agent",
                        _agent_json_dumps(context),
                        now,
                        now,
                    ),
                )
            message_id = _insert_agent_message(cursor, session_id, "user", message, context)
            conn.commit()
    if is_first_user_message:
        _schedule_agent_session_title(session_id, message, owner_user_id)
    return {"sessionId": session_id, "messageId": message_id}


def _schedule_agent_session_title(session_id, message, owner_user_id):
    if not all(globals().get(name) for name in ("TEXT_LLM_MODEL", "TEXT_LLM_API_KEY", "TEXT_LLM_BASE_URL")):
        return
    _threading.Thread(
        target=_generate_agent_session_title,
        args=(session_id, message, owner_user_id),
        daemon=True,
        name="agent-session-title",
    ).start()


def _generate_agent_session_title(session_id, message, owner_user_id):
    try:
        with agent_actor(owner_user_id):
            result, _, _ = call_json_contract(
                messages=[
                    {"role": "system", "content": "将用户首条问题概括为12到20字中文会话标题。只返回 JSON：{\"title\": \"...\"}。"},
                    {"role": "user", "content": _agent_text(message, 500)},
                ],
                contract_id="agent_session_title",
                validator=lambda value: {"title": _agent_text((value or {}).get("title"), 20)},
                model=TEXT_LLM_MODEL,
                api_key=TEXT_LLM_API_KEY,
                base_url=TEXT_LLM_BASE_URL,
                timeout=LLM_TIMEOUT,
                temperature=0,
                max_tokens=48,
                prompt_version=globals().get("AGENT_PROMPT_VERSION", "agent-session-title-v1"),
            )
            title = result.get("title")
            if not title:
                return
            with agent_session_guard(session_id):
                with _db_connect() as conn:
                    cursor = conn.execute(
                        "UPDATE agent_sessions SET title = ? WHERE id = ? AND title = ?",
                        (title, session_id, _agent_text(message, 64) or "Vidferry Agent"),
                    )
                    conn.commit()
                    if cursor.rowcount != 1:
                        return
    except Exception:
        _logging.exception("Agent 会话标题生成失败 session=%s", session_id)


def list_agent_messages(session_id, limit=12, before_id=None, after_id=None):
    limit = max(1, min(int(limit or 12), 100))
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id, "s.owner_user_id")
    values = [str(session_id or "").strip(), *owner_values]
    before_sql = ""
    after_sql = ""
    if before_id:
        try:
            before_sql = "AND m.id < ?"
            values.append(int(before_id))
        except (TypeError, ValueError):
            before_sql = ""
    if after_id:
        try:
            after_sql = "AND m.id > ?"
            values.append(int(after_id))
        except (TypeError, ValueError):
            after_sql = ""
    values.append(limit)
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT m.*
            FROM agent_messages AS m
            JOIN agent_sessions AS s ON s.id = m.session_id
            WHERE m.session_id = ? AND s.deleted_at IS NULL
              {owner_filter} {before_sql} {after_sql}
            ORDER BY m.id DESC
            LIMIT ?
            """,
            values,
        )
        rows = list(reversed(cursor.fetchall()))
        return [_agent_message_payload(row) for row in rows]


def _agent_message_payload(row):
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "context": _agent_json_loads(row["context"]),
        "createdAt": row["created_at"],
    }


def get_agent_session(session_id):
    with _db_connect(row_factory=True) as conn:
        row = _active_session_row(conn.cursor(), session_id)
        if not row:
            return None
        return _agent_session_payload(row)


def _agent_session_payload(row):
    summary = _agent_json_loads(row["summary"], {})
    payload = {
        "id": row["id"],
        "title": row["title"] or "Vidferry Agent",
        "source": _agent_source(row["source"]),
        "context": _agent_json_loads(row["context"], {}),
        "summary": summary if isinstance(summary, dict) else {},
        "summaryThroughId": int(row["summary_through_id"] or 0),
        "messageCount": int(row["message_count"] or 0),
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or row["created_at"] or "",
    }
    context_stats = globals().get("get_agent_session_context_stats")
    if callable(context_stats):
        payload["contextStats"] = context_stats(payload)
    return payload


def list_agent_sessions(*, from_date="", to_date="", source="", q="", page=1, page_size=20):
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 50))
    owner_user_id = _agent_current_user_id()
    where = ["s.deleted_at IS NULL"]
    values = []
    if owner_user_id is not None:
        where.append("s.owner_user_id = ?")
        values.append(owner_user_id)
    if source:
        normalized_source = _agent_source(source)
        if str(source).strip() != normalized_source:
            raise ValueError("不支持的 Agent 会话来源。")
        where.append("s.source = ?")
        values.append(normalized_source)
    if q:
        keyword = str(q).strip()
        if keyword:
            where.append("(s.title LIKE ? OR EXISTS (SELECT 1 FROM agent_messages AS qm WHERE qm.session_id = s.id AND qm.content LIKE ?))")
            values.extend([f"%{keyword}%", f"%{keyword}%"])
    if from_date:
        value = str(from_date).strip()
        where.append("s.updated_at >= ?")
        values.append(value if "T" in value else f"{value}T00:00:00")
    if to_date:
        value = str(to_date).strip()
        where.append("s.updated_at <= ?")
        values.append(value if "T" in value else f"{value}T23:59:59")
    where_sql = " AND ".join(where)
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) AS total FROM agent_sessions AS s WHERE {where_sql}", values)
        total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            f"""
            SELECT
                s.*,
                (
                    SELECT m.content
                    FROM agent_messages AS m
                    WHERE m.session_id = s.id AND m.role = 'user'
                    ORDER BY m.id DESC
                    LIMIT 1
                ) AS last_user_message
            FROM agent_sessions AS s
            WHERE {where_sql}
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT ? OFFSET ?
            """,
            values + [page_size, (page - 1) * page_size],
        )
        items = []
        for row in cursor.fetchall():
            item = _agent_session_payload(row)
            item["preview"] = _agent_text(row["last_user_message"], 140)
            items.append(item)
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "hasMore": page * page_size < total,
    }


def _external_session_key(source, source_key):
    normalized_source = _agent_source(source)
    key = str(source_key or "").strip()
    if normalized_source != _AGENT_SOURCE_FEISHU or not key:
        raise ValueError("外部 Agent 会话来源无效。")
    return normalized_source, key[:128]


def _upsert_agent_session_binding(cursor, source, source_key, session_id, owner_user_id, now):
    cursor.execute(
        "DELETE FROM agent_session_bindings WHERE source = ? AND source_key = ?",
        (source, source_key),
    )
    cursor.execute(
        """
        INSERT INTO agent_session_bindings (source, source_key, session_id, owner_user_id, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source, source_key, session_id, owner_user_id, now),
    )


def get_or_create_external_agent_session(source, source_key, title=""):
    source, source_key = _external_session_key(source, source_key)
    owner_user_id = _agent_current_user_id()
    if owner_user_id is None:
        raise ValueError("外部 Agent 会话必须配置归属账号。")
    lock_id = f"external-{source}-{source_key}"
    with agent_session_guard(lock_id):
        with _db_connect(row_factory=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.id
                FROM agent_session_bindings AS b
                JOIN agent_sessions AS s ON s.id = b.session_id
                WHERE b.source = ? AND b.source_key = ? AND b.owner_user_id = ?
                  AND s.deleted_at IS NULL AND s.owner_user_id = ?
                """,
                (source, source_key, owner_user_id, owner_user_id),
            )
            row = cursor.fetchone()
            if row:
                conn.commit()
                return row["id"]

            session_id = _agent_new_id("session")
            now = _agent_now_iso()
            cursor.execute(
                """
                INSERT INTO agent_sessions (
                    id, owner_user_id, source, source_key, title, context, summary,
                    summary_through_id, message_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, '{}', '{}', 0, 0, ?, ?)
                """,
                (session_id, owner_user_id, source, source_key, title or "手机端会话", now, now),
            )
            _upsert_agent_session_binding(cursor, source, source_key, session_id, owner_user_id, now)
            conn.commit()
            return session_id


def create_external_agent_session(source, source_key, title=""):
    source, source_key = _external_session_key(source, source_key)
    owner_user_id = _agent_current_user_id()
    if owner_user_id is None:
        raise ValueError("外部 Agent 会话必须配置归属账号。")
    lock_id = f"external-{source}-{source_key}"
    with agent_session_guard(lock_id):
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            session_id = _agent_new_id("session")
            now = _agent_now_iso()
            cursor.execute(
                """
                INSERT INTO agent_sessions (
                    id, owner_user_id, source, source_key, title, context, summary,
                    summary_through_id, message_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, '{}', '{}', 0, 0, ?, ?)
                """,
                (session_id, owner_user_id, source, source_key, title or "手机端会话", now, now),
            )
            _upsert_agent_session_binding(cursor, source, source_key, session_id, owner_user_id, now)
            conn.commit()
    return session_id


def list_external_agent_sessions(source, source_key, limit=10):
    source, source_key = _external_session_key(source, source_key)
    limit = max(1, min(int(limit or 10), 20))
    owner_user_id = _agent_current_user_id()
    if owner_user_id is None:
        raise ValueError("外部 Agent 会话必须配置归属账号。")
    with _db_connect(row_factory=True) as conn:
        rows = conn.execute(
            """
            SELECT s.*
            FROM agent_sessions AS s
            WHERE s.source = ? AND s.source_key = ? AND s.owner_user_id = ?
              AND s.deleted_at IS NULL
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT ?
            """,
            (source, source_key, owner_user_id, limit),
        ).fetchall()
    return [_agent_session_payload(row) for row in rows]


def switch_external_agent_session(source, source_key, position):
    source, source_key = _external_session_key(source, source_key)
    try:
        position = int(position)
    except (TypeError, ValueError) as exc:
        raise ValueError("会话编号必须是正整数。") from exc
    sessions = list_external_agent_sessions(source, source_key)
    if position < 1 or position > len(sessions):
        raise ValueError("会话编号不存在，请先使用 /sessions 查看列表。")
    owner_user_id = _agent_current_user_id()
    session_id = sessions[position - 1]["id"]
    with agent_session_guard(f"external-{source}-{source_key}"):
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _upsert_agent_session_binding(conn.cursor(), source, source_key, session_id, owner_user_id, _agent_now_iso())
            conn.commit()
    return sessions[position - 1]


def delete_agent_session(session_id):
    session_id = str(session_id or "").strip()
    if not session_id:
        return False
    now = _agent_now_iso()
    with agent_session_guard(session_id):
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            owner_filter, owner_values = _agent_owner_filter(owner_user_id)
            cursor.execute(
                f"SELECT id FROM agent_sessions WHERE id = ?{owner_filter}",
                (session_id,) + owner_values,
            )
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM agent_session_bindings WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM agent_runs WHERE session_id = ?", (session_id,))
            cursor.execute(
                """
                UPDATE agent_sessions
                SET title = '已删除会话', context = '{}', summary = '{}',
                    summary_through_id = 0, message_count = 0, deleted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, session_id),
            )
            conn.commit()
    return True
