def _agent_run_from_row(row):
    return {
        "id": row["id"],
        "sessionId": row["session_id"] or "",
        "type": row["run_type"],
        "subjectType": row["subject_type"] or "",
        "subjectId": row["subject_id"] or "",
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


def get_agent_run(run_id):
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        owner_user_id = _agent_current_user_id()
        owner_filter = ""
        owner_values = ()
        if owner_user_id is not None:
            owner_filter = " AND (r.run_type != 'chat' OR s.owner_user_id = %s)"
            owner_values = (owner_user_id,)
        cursor.execute(
            f"""SELECT r.* FROM agent_runs AS r
               LEFT JOIN agent_sessions AS s ON s.id = r.session_id
               WHERE r.id = %s{owner_filter}""",
            (run_id,) + owner_values,
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _agent_run_from_row(row)


def _latest_agent_session_run(session_id, run_type):
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE session_id = %s AND run_type = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (str(session_id or ""), run_type),
        ).fetchone()
    return _agent_run_from_row(row) if row else None


def get_latest_agent_session_compaction(session_id):
    run = _latest_agent_session_run(session_id, "context_compaction")
    if not run:
        return None
    return {"durationMs": run["durationMs"], "createdAt": run["createdAt"], **(run.get("inputSummary") or {}), **(run.get("output") or {})}


def get_latest_agent_session_chat_usage(session_id):
    run = _latest_agent_session_run(session_id, "chat")
    usage = (run or {}).get("output", {}).get("usage", {})
    return int(usage.get("promptTokens") or 0) if isinstance(usage, dict) else 0


def get_latest_agent_run(run_type, subject_type="", subject_id="", legacy_file_path=""):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        if subject_type and subject_id:
            cursor.execute(
                """
                SELECT * FROM agent_runs
                WHERE run_type = %s AND subject_type = %s AND subject_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (run_type, subject_type, subject_id),
            )
            row = cursor.fetchone()
            if row:
                return _agent_run_from_row(row)

        legacy_file_path = str(legacy_file_path or "").strip()
        if not legacy_file_path:
            return None
        cursor.execute(
            """
            SELECT * FROM agent_runs
            WHERE run_type = %s AND COALESCE(subject_id, '') = ''
            ORDER BY created_at DESC, id DESC
            """,
            (run_type,),
        )
        for row in cursor.fetchall():
            summary = _agent_json_loads(row["input_summary"])
            file_list = summary.get("fileList") if isinstance(summary, dict) else []
            if any(str(item or "").strip() == legacy_file_path for item in (file_list or [])):
                return _agent_run_from_row(row)
    return None


def _agent_run_observability_payload(rows, limit):
    """仅保留诊断所需的运行元数据，避免把历史对话正文带回模型上下文。"""
    items = []
    metrics = {
        "total": len(rows),
        "succeeded": 0,
        "failed": 0,
        "blocked": 0,
        "toolErrors": 0,
        "totalDurationMs": 0,
    }
    for row in rows:
        output = _agent_json_loads(row["output"])
        safety = output.get("safetyDecision") if isinstance(output, dict) else {}
        safety = safety if isinstance(safety, dict) else {}
        tool_results = output.get("toolResults") if isinstance(output, dict) else []
        tool_results = tool_results if isinstance(tool_results, list) else []
        tool_names = [str(item.get("tool") or "") for item in tool_results if isinstance(item, dict) and item.get("tool")]
        tool_error_count = sum(1 for item in tool_results if isinstance(item, dict) and item.get("error"))
        duration_ms = int(row["duration_ms"] or 0)
        status = str(row["status"] or "success")
        metrics["succeeded" if status == "success" else "failed"] += 1
        metrics["blocked"] += int(safety.get("allowed") is False)
        metrics["toolErrors"] += tool_error_count
        metrics["totalDurationMs"] += duration_ms
        items.append({
            "id": row["id"],
            "type": row["run_type"],
            "status": status,
            "durationMs": duration_ms,
            "toolNames": tool_names,
            "toolErrorCount": tool_error_count,
            "blocked": safety.get("allowed") is False,
            "createdAt": row["created_at"] or "",
        })
    total = metrics.pop("total")
    total_duration_ms = metrics.pop("totalDurationMs")
    return {
        "sampleSize": total,
        "successRate": round(metrics["succeeded"] / total, 3) if total else None,
        "averageDurationMs": round(total_duration_ms / total) if total else 0,
        "blockedCount": metrics["blocked"],
        "toolErrorCount": metrics["toolErrors"],
        "items": items[:limit],
    }


def get_agent_run_overview(limit=8):
    """查询当前用户可见的 Agent 运行健康度和最近轨迹。"""
    limit = max(1, min(int(limit or 8), 20))
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        owner_user_id = _agent_current_user_id()
        owner_filter = ""
        owner_values = ()
        if owner_user_id is not None:
            owner_filter = "WHERE r.run_type != 'chat' OR s.owner_user_id = %s"
            owner_values = (owner_user_id,)
        cursor.execute(
            f"""
            SELECT r.* FROM agent_runs AS r
            LEFT JOIN agent_sessions AS s ON s.id = r.session_id
            {owner_filter}
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT %s
            """,
            owner_values + (limit,),
        )
        return _agent_run_observability_payload(cursor.fetchall(), limit)


def list_agent_memory(memory_type="", limit=8):
    limit = max(1, min(int(limit or 8), 20))
    where = ""
    values = []
    if memory_type:
        where = "WHERE memory_type = %s"
        values.append(memory_type)
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT * FROM agent_memory_items
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT %s
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
