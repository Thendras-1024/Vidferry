def ensure_agent_session(session_id="", title="", context=None, source=""):
    session_id = str(session_id or "").strip() or _agent_new_id("session")
    now = _agent_now_iso()
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            cursor.execute("SELECT * FROM agent_sessions WHERE id = %s", (session_id,))
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
                        SET context = %s, updated_at = %s
                        WHERE id = %s AND deleted_at IS NULL
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
                    VALUES (%s, %s, %s, %s, %s, '{}', 0, 0, %s, %s)
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
        SELECT %s, %s, %s, %s, %s
        WHERE EXISTS (
            SELECT 1 FROM agent_sessions WHERE id = %s AND deleted_at IS NULL{owner_filter}
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
                WHEN COALESCE(message_count, 0) = 0 AND %s = 'user' THEN substr(%s, 1, 64)
                ELSE title
            END,
            message_count = COALESCE(message_count, 0) + 1,
            updated_at = %s
        WHERE id = %s AND deleted_at IS NULL{owner_filter}
        """,
        (role, _agent_text(content, 64) or "Vidferry Agent", _agent_now_iso(), session_id) + owner_values,
    )
    if cursor.rowcount != 1:
        raise ValueError("Agent 会话在消息保存期间被删除。")
    return message_id


def _agent_turn_event_metadata(event_type, payload):
    """事件审计只保留可检索的元数据，不持久化消息、工具参数或结果正文。"""
    payload = payload if isinstance(payload, dict) else {}
    if event_type in {"user_message", "assistant_message"}:
        content = payload.get("content")
        context = payload.get("context")
        return {
            "messageId": payload.get("messageId"),
            "contentChars": len(str(content or "")),
            "contextKeys": sorted(str(key) for key in context)[:40] if isinstance(context, dict) else [],
        }
    if event_type == "tool_call":
        args = payload.get("args")
        return {"argKeys": sorted(str(key) for key in args)[:40] if isinstance(args, dict) else []}
    if event_type == "tool_result":
        result = payload.get("result")
        error = payload.get("error")
        return {
            "resultType": type(result).__name__ if result is not None else "none",
            "resultCount": len(result) if isinstance(result, (dict, list, tuple, set, str)) else 0,
            "errorType": type(error).__name__ if error else "",
        }
    return {
        "keys": sorted(str(key) for key in payload)[:40],
    }


def _insert_agent_turn_event(cursor, session_id, turn_id, sequence, event_type, *, role="", tool_name="", payload=None):
    """追加不含正文的会话事件审计；完整消息仍保留在会话消息表中。"""
    cursor.execute(
        """
        INSERT INTO agent_turn_events (session_id, turn_id, sequence, event_type, role, tool_name, payload, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(session_id or ""), int(turn_id) if turn_id else None, int(sequence or 0), str(event_type or ""),
            str(role or ""), str(tool_name or ""),
            _agent_json_dumps(_agent_turn_event_metadata(str(event_type or ""), payload)), _agent_now_iso(),
        ),
    )


def _backfill_legacy_agent_turn_events(session_id):
    """为升级前无事件流的会话建立一次兼容视图，不修改原始消息。"""
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM agent_turn_events WHERE session_id = %s LIMIT 1", (session_id,))
            if cursor.fetchone():
                return
            owner_filter, owner_values = _agent_owner_filter(_agent_current_user_id(), "s.owner_user_id")
            cursor.execute(
                f"""
                SELECT m.id, m.role, m.content, m.context
                FROM agent_messages AS m
                JOIN agent_sessions AS s ON s.id = m.session_id
                WHERE m.session_id = %s AND s.deleted_at IS NULL{owner_filter}
                ORDER BY m.id ASC
                """,
                (session_id, *owner_values),
            )
            current_turn_id = None
            for message in cursor.fetchall():
                message_id = int(message["id"] or 0)
                role = message["role"]
                context = _agent_json_loads(message["context"], {})
                if role == "user":
                    current_turn_id = message_id
                    _insert_agent_turn_event(
                        cursor, session_id, current_turn_id, 0, "user_message", role="user",
                        payload={"messageId": message_id, "content": message["content"], "context": context},
                    )
                    continue
                turn_id = current_turn_id or message_id
                for sequence, item in enumerate(context.get("toolResults") or [], start=1):
                    if not isinstance(item, dict):
                        continue
                    _insert_agent_turn_event(
                        cursor, session_id, turn_id, sequence * 2 - 1, "tool_call",
                        tool_name=item.get("tool") or "", payload={"args": item.get("args") or {}},
                    )
                    _insert_agent_turn_event(
                        cursor, session_id, turn_id, sequence * 2, "tool_result",
                        tool_name=item.get("tool") or "", payload={
                            "result": item.get("result"), "error": item.get("error") or "",
                        },
                    )
                _insert_agent_turn_event(
                    cursor, session_id, turn_id, 10_000, "assistant_message", role="assistant",
                    payload={"messageId": message_id, "content": message["content"], "context": context},
                )
            conn.commit()


def list_agent_turn_events(session_id, turn_id=None):
    """按会话或回合读取原始事件，供诊断与后续回放使用。"""
    session_id = str(session_id or "").strip()
    if not session_id:
        return []
    _backfill_legacy_agent_turn_events(session_id)
    owner_filter, owner_values = _agent_owner_filter(_agent_current_user_id(), "s.owner_user_id")
    values = [session_id, *owner_values]
    turn_sql = ""
    if turn_id is not None:
        turn_sql = " AND e.turn_id = %s"
        values.append(int(turn_id))
    with _db_connect(row_factory=True) as conn:
        rows = conn.execute(
            f"""
            SELECT e.* FROM agent_turn_events AS e
            JOIN agent_sessions AS s ON s.id = e.session_id
            WHERE e.session_id = %s AND s.deleted_at IS NULL{owner_filter}{turn_sql}
            ORDER BY e.turn_id, e.sequence, e.id
            """,
            values,
        ).fetchall()
    return [{
        "id": row["id"], "turnId": row["turn_id"], "sequence": int(row["sequence"] or 0),
        "type": row["event_type"], "role": row["role"] or "", "toolName": row["tool_name"] or "",
        "payload": _agent_turn_event_metadata(row["event_type"], _agent_json_loads(row["payload"], {})),
        "createdAt": row["created_at"],
    } for row in rows]


def save_agent_turn_event(session_id, event_type, *, turn_id=None, sequence=0, role="", tool_name="", payload=None):
    session_id = str(session_id or "").strip()
    if not session_id:
        return None
    with agent_session_guard(session_id):
        with _db_connect() as conn:
            cursor = conn.cursor()
            _insert_agent_turn_event(
                cursor, session_id, turn_id, sequence, event_type, role=role,
                tool_name=tool_name, payload=payload,
            )
            conn.commit()


def save_agent_message(session_id, role, content, context=None):
    session_id = str(session_id or "").strip()
    with agent_session_guard(session_id):
        with _db_connect() as conn:
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
    proposal_updates=None,
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
                WHERE m.session_id = %s AND m.role = 'assistant' AND s.deleted_at IS NULL
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
                if isinstance(proposal_updates, dict):
                    proposal.update(proposal_updates)
                context[proposal_key] = proposal
                cursor.execute(
                    "UPDATE agent_messages SET context = %s WHERE id = %s",
                    (_agent_json_dumps(context), row["id"]),
                )
                conn.commit()
                return True
    return False


def get_agent_proposal_state(session_id, proposal_key, proposal_id):
    """读取当前账号会话中已保存的交互提案，用于进程重启后的恢复。"""
    session_id = str(session_id or "").strip()
    proposal_key = str(proposal_key or "").strip()
    proposal_id = str(proposal_id or "").strip()
    if not session_id or not proposal_key or not proposal_id:
        return None
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id, "s.owner_user_id")
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT m.context
            FROM agent_messages AS m
            JOIN agent_sessions AS s ON s.id = m.session_id
            WHERE m.session_id = %s AND m.role = 'assistant' AND s.deleted_at IS NULL
              {owner_filter}
            ORDER BY m.id DESC
            """,
            (session_id, *owner_values),
        )
        for row in cursor.fetchall():
            context = _agent_json_loads(row["context"], {})
            proposal = context.get(proposal_key) if isinstance(context, dict) else None
            if isinstance(proposal, dict) and str(proposal.get("proposalId") or "") == proposal_id:
                return dict(proposal)
    return None


def update_agent_session_context(session_id, changes):
    """在当前账号和会话范围内原子更新临时 Agent 上下文。"""
    session_id = str(session_id or "").strip()
    if not session_id or not isinstance(changes, dict):
        return None
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id, "owner_user_id")
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            row = conn.execute(
                f"SELECT context FROM agent_sessions WHERE id = %s AND deleted_at IS NULL{owner_filter}",
                (session_id, *owner_values),
            ).fetchone()
            if not row:
                return None
            context = _agent_json_loads(row["context"], {})
            context = dict(context) if isinstance(context, dict) else {}
            context.update(changes)
            now = _agent_now_iso()
            conn.execute(
                "UPDATE agent_sessions SET context = %s, updated_at = %s WHERE id = %s",
                (_agent_json_dumps(context), now, session_id),
            )
            conn.commit()
            return context


def start_agent_turn(session_id="", message="", context=None):
    """在一个短事务中确保会话并保存本轮用户消息。"""
    session_id = str(session_id or "").strip() or _agent_new_id("session")
    now = _agent_now_iso()
    with agent_session_guard(session_id):
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            cursor.execute("SELECT * FROM agent_sessions WHERE id = %s", (session_id,))
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
                        "UPDATE agent_sessions SET context = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL",
                        (merged_context_text, now, session_id),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO agent_sessions (
                        id, owner_user_id, source, title, context, summary, summary_through_id,
                        message_count, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, '{}', 0, 0, %s, %s)
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
            _insert_agent_turn_event(
                cursor, session_id, message_id, 0, "user_message", role="user",
                payload={
                    "messageId": message_id, "content": str(message or ""),
                    "context": context if isinstance(context, dict) else {},
                },
            )
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
                        "UPDATE agent_sessions SET title = %s WHERE id = %s AND title = %s",
                        (title, session_id, _agent_text(message, 64) or "Vidferry Agent"),
                    )
                    conn.commit()
                    if cursor.rowcount != 1:
                        return
    except Exception:
        _logging.exception("Agent 会话标题生成失败 session=%s", session_id)


def list_agent_messages(session_id, limit=12, before_id=None, after_id=None):
    limit = max(1, min(int(limit or 12), 2000))
    owner_user_id = _agent_current_user_id()
    owner_filter, owner_values = _agent_owner_filter(owner_user_id, "s.owner_user_id")
    values = [str(session_id or "").strip(), *owner_values]
    before_sql = ""
    after_sql = ""
    if before_id:
        try:
            before_sql = "AND m.id < %s"
            values.append(int(before_id))
        except (TypeError, ValueError):
            before_sql = ""
    if after_id:
        try:
            after_sql = "AND m.id > %s"
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
            WHERE m.session_id = %s AND s.deleted_at IS NULL
              {owner_filter} {before_sql} {after_sql}
            ORDER BY m.id DESC
            LIMIT %s
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
        "summaryVersion": int(row.get("summary_version") or 1),
        "summaryUpdatedAt": row.get("summary_updated_at") or "",
        "contextPolicyVersion": row.get("context_policy_version") or _CONTEXT_POLICY_VERSION,
        "lastCompactionRunId": row.get("last_compaction_run_id") or "",
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
        where.append("s.owner_user_id = %s")
        values.append(owner_user_id)
    if source:
        normalized_source = _agent_source(source)
        if str(source).strip() != normalized_source:
            raise ValueError("不支持的 Agent 会话来源。")
        where.append("s.source = %s")
        values.append(normalized_source)
    if q:
        keyword = str(q).strip()
        if keyword:
            where.append("(s.title ILIKE %s OR EXISTS (SELECT 1 FROM agent_messages AS qm WHERE qm.session_id = s.id AND qm.content ILIKE %s))")
            values.extend([f"%{keyword}%", f"%{keyword}%"])
    if from_date:
        value = str(from_date).strip()
        where.append("s.updated_at >= %s")
        values.append(value if "T" in value else f"{value}T00:00:00")
    if to_date:
        value = str(to_date).strip()
        where.append("s.updated_at <= %s")
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
            LIMIT %s OFFSET %s
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
        "DELETE FROM agent_session_bindings WHERE source = %s AND source_key = %s",
        (source, source_key),
    )
    cursor.execute(
        """
        INSERT INTO agent_session_bindings (source, source_key, session_id, owner_user_id, updated_at)
        VALUES (%s, %s, %s, %s, %s)
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
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.id
                FROM agent_session_bindings AS b
                JOIN agent_sessions AS s ON s.id = b.session_id
                WHERE b.source = %s AND b.source_key = %s AND b.owner_user_id = %s
                  AND s.deleted_at IS NULL AND s.owner_user_id = %s
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
                VALUES (%s, %s, %s, %s, %s, '{}', '{}', 0, 0, %s, %s)
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
            cursor = conn.cursor()
            session_id = _agent_new_id("session")
            now = _agent_now_iso()
            cursor.execute(
                """
                INSERT INTO agent_sessions (
                    id, owner_user_id, source, source_key, title, context, summary,
                    summary_through_id, message_count, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, '{}', '{}', 0, 0, %s, %s)
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
            WHERE s.source = %s AND s.source_key = %s AND s.owner_user_id = %s
              AND s.deleted_at IS NULL
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT %s
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
            cursor = conn.cursor()
            owner_user_id = _agent_current_user_id()
            if owner_user_id is None:
                return False
            owner_filter, owner_values = _agent_owner_filter(owner_user_id)
            cursor.execute(
                f"SELECT id FROM agent_sessions WHERE id = %s{owner_filter}",
                (session_id,) + owner_values,
            )
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM agent_session_bindings WHERE session_id = %s", (session_id,))
            cursor.execute("DELETE FROM agent_messages WHERE session_id = %s", (session_id,))
            cursor.execute("DELETE FROM agent_runs WHERE session_id = %s AND owner_user_id = %s", (session_id, owner_user_id))
            cursor.execute(
                """
                UPDATE agent_sessions
                SET title = '已删除会话', context = '{}', summary = '{}',
                    summary_through_id = 0, message_count = 0, deleted_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (now, now, session_id),
            )
            conn.commit()
    return True
