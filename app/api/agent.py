from flask import redirect, send_file


@app.route('/agents/status', methods=['GET'])
def agent_status():
    return jsonify({
        "code": 200,
        "msg": "success",
        "data": _agent_status_payload()
    }), 200


@app.route('/agents/chat', methods=['POST'])
def agent_chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"code": 400, "msg": "请输入要询问 Agent 的内容", "data": None}), 400
    try:
        backend_logger.info("Agent 对话开始 session_id=%s", payload.get("sessionId") or "new")
        result = run_agent_chat(
            message,
            session_id=payload.get("sessionId") or "",
            context=payload.get("context") or {},
        )
        backend_logger.info("Agent 对话完成 session_id=%s", result.get("sessionId") or "new")
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": result
        }), 200
    except Exception as exc:
        backend_logger.exception("Agent 对话失败 session_id=%s", payload.get("sessionId") or "new")
        return jsonify({"code": 500, "msg": "Agent 对话失败，请稍后重试", "data": None}), 500


@app.route('/agents/chat/stream', methods=['POST'])
def agent_chat_stream():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"code": 400, "msg": "请输入要询问 Agent 的内容", "data": None}), 400
    backend_logger.info("Agent 流式对话开始 session_id=%s", payload.get("sessionId") or "new")
    response = Response(stream_with_context(run_agent_chat_stream(
        message,
        session_id=payload.get("sessionId") or "",
        context=payload.get("context") or {},
    )), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route('/agents/import-proposals/<proposal_id>/confirm', methods=['POST'])
def confirm_agent_import_proposal_route(proposal_id):
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("sessionId") or "").strip()
    selected_ids = payload.get("selectedIds")
    targets = payload.get("targets")
    scheduled_at = str(payload.get("scheduledAt") or "").strip()
    if not session_id:
        return jsonify({"code": 400, "msg": "缺少 Agent 会话标识", "data": None}), 400
    if selected_ids is not None and not isinstance(selected_ids, list):
        return jsonify({"code": 400, "msg": "候选视频格式不正确", "data": None}), 400
    if targets is not None and not isinstance(targets, list):
        return jsonify({"code": 400, "msg": "发布目标格式不正确", "data": None}), 400
    try:
        result = confirm_agent_import_proposal(proposal_id, session_id, selected_ids, targets, scheduled_at)
        backend_logger.info(
            "Agent 线索导入完成 proposal_id=%s session_id=%s created=%s duplicate=%s failed=%s",
            proposal_id, session_id, result.get("createdCount"), result.get("duplicateCount"), result.get("failedCount"),
        )
        return jsonify({"code": 200, "msg": "线索导入完成", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("Agent 线索导入失败 proposal_id=%s", proposal_id)
        return jsonify({"code": 500, "msg": "线索导入失败，请稍后重试", "data": None}), 500


@app.route('/agents/execution-proposals/<proposal_id>/confirm', methods=['POST'])
def confirm_agent_execution_proposal_route(proposal_id):
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("sessionId") or "").strip()
    targets = payload.get("targets")
    video_ids = payload.get("videoIds")
    scheduled_at = str(payload.get("scheduledAt") or "").strip()
    if not session_id:
        return jsonify({"code": 400, "msg": "缺少 Agent 会话标识", "data": None}), 400
    if targets is not None and not isinstance(targets, list):
        return jsonify({"code": 400, "msg": "发布目标格式不正确", "data": None}), 400
    if video_ids is not None and not isinstance(video_ids, list):
        return jsonify({"code": 400, "msg": "视频选择格式不正确", "data": None}), 400
    try:
        result = confirm_agent_execution_proposal(proposal_id, session_id, targets, scheduled_at, video_ids)
        backend_logger.info(
            "Agent 执行提案已确认 proposal_id=%s session_id=%s action=%s",
            proposal_id, session_id, result.get("action"),
        )
        return jsonify({"code": 200, "msg": result.get("message") or "任务已创建", "data": result}), 200
    except (ValueError, WorkflowConflictError, AgentGuardError) as exc:
        status = 409 if isinstance(exc, WorkflowConflictError) else getattr(exc, "status_code", 400)
        return jsonify({"code": status, "msg": str(exc), "data": None}), status
    except Exception as exc:
        backend_logger.exception("Agent 执行提案确认失败 proposal_id=%s", proposal_id)
        return jsonify({"code": 500, "msg": "执行提案确认失败，请稍后重试", "data": None}), 500


@app.route('/agents/copywriting-proposals/<proposal_id>/generate', methods=['POST'])
def generate_agent_copywriting_proposal_route(proposal_id):
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("sessionId") or "").strip()
    video_id = str(payload.get("videoId") or "").strip()
    if not session_id or not video_id:
        return jsonify({"code": 400, "msg": "缺少 Agent 会话或视频标识", "data": None}), 400
    try:
        result = generate_agent_copywriting_candidates(
            proposal_id,
            session_id,
            video_id,
            payload.get("request"),
        )
        backend_logger.info(
            "Agent 文案候选生成完成 : proposal_id = %s | session_id = %s | video_id = %s",
            proposal_id,
            session_id,
            video_id,
        )
        return jsonify({"code": 200, "msg": "文案候选已生成", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except (LLMContractError, LLMRequestError) as exc:
        backend_logger.warning("Agent 文案候选生成失败 : proposal_id = %s | error_type = %s", proposal_id, type(exc).__name__)
        return jsonify({"code": 502, "msg": str(exc), "data": None}), 502
    except Exception:
        backend_logger.exception("Agent 文案候选生成异常 : proposal_id = %s", proposal_id)
        return jsonify({"code": 500, "msg": "文案候选生成失败", "data": None}), 500


@app.route('/agents/copywriting-proposals/<proposal_id>/apply', methods=['POST'])
def apply_agent_copywriting_proposal_route(proposal_id):
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        return jsonify({"code": 400, "msg": "缺少 Agent 会话标识", "data": None}), 400
    try:
        result = apply_agent_copywriting_proposal(
            proposal_id,
            session_id,
            payload.get("draftIndex"),
            payload,
            payload.get("draftKind"),
        )
        backend_logger.info(
            "Agent 待发布稿已保存 : proposal_id = %s | session_id = %s | video_id = %s",
            proposal_id,
            session_id,
            result.get("videoId") or "",
        )
        return jsonify({"code": 200, "msg": result.get("message") or "待发布稿已保存", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception:
        backend_logger.exception("Agent 待发布稿保存失败 : proposal_id = %s", proposal_id)
        return jsonify({"code": 500, "msg": "待发布稿保存失败", "data": None}), 500


@app.route('/agents/video-status-cards/<card_id>/page', methods=['POST'])
def agent_video_status_card_page(card_id):
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        return jsonify({"code": 400, "msg": "缺少 Agent 会话标识", "data": None}), 400
    try:
        result = get_agent_video_status_card_page(card_id, session_id, payload.get("page", 1))
        backend_logger.info(
            "Agent 视频状态卡翻页 : card_id = %s | session_id = %s | page = %s",
            card_id,
            session_id,
            result.get("page"),
        )
        return jsonify({"code": 200, "msg": "success", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400


@app.route('/agents/sessions/<session_id>/video-selection', methods=['PUT'])
def update_agent_video_selection_route(session_id):
    payload = request.get_json(silent=True) or {}
    try:
        result = update_agent_video_selection(session_id, payload.get("videoIds"), payload.get("cardId"))
        backend_logger.info(
            "Agent 视频选择已更新 : session_id = %s | count = %s",
            session_id,
            len(result.get("videoIds") or []),
        )
        return jsonify({"code": 200, "msg": "视频选择已更新", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400


@app.route('/agents/videos/<video_id>/thumbnail', methods=['GET'])
def agent_video_thumbnail(video_id):
    session_id = str(request.args.get("sessionId") or "").strip()
    if not session_id or not get_agent_session(session_id):
        return jsonify({"code": 403, "msg": "Agent 会话无权读取视频缩略图", "data": None}), 403
    thumbnail_path = agent_video_processed_thumbnail_path(video_id)
    if thumbnail_path:
        return send_file(thumbnail_path, conditional=True, max_age=300)
    source_thumbnail = agent_video_source_thumbnail(video_id)
    if source_thumbnail:
        return redirect(source_thumbnail, code=302)
    return jsonify({"code": 404, "msg": "视频缩略图不存在", "data": None}), 404


@app.route('/agents/sessions', methods=['GET'])
def agent_sessions():
    try:
        data = list_agent_sessions(
            from_date=request.args.get("from", ""),
            to_date=request.args.get("to", ""),
            source=request.args.get("source", ""),
            q=request.args.get("q", ""),
            page=request.args.get("page", 1),
            page_size=request.args.get("pageSize", 20),
        )
        return jsonify({"code": 200, "msg": "success", "data": data}), 200
    except (TypeError, ValueError) as exc:
        return jsonify({"code": 400, "msg": f"读取 Agent 会话列表失败: {str(exc)}", "data": None}), 400
    except Exception as exc:
        return jsonify({"code": 500, "msg": "读取 Agent 会话列表失败，请稍后重试", "data": None}), 500


@app.route('/agents/sessions/<session_id>', methods=['GET'])
def agent_session_detail(session_id):
    session = get_agent_session(session_id)
    if not session:
        return jsonify({"code": 404, "msg": "Agent 会话不存在或已删除", "data": None}), 404
    return jsonify({"code": 200, "msg": "success", "data": session}), 200


@app.route('/agents/sessions/<session_id>', methods=['DELETE'])
def delete_agent_session_route(session_id):
    try:
        deleted = delete_agent_session(session_id)
        if not deleted:
            return jsonify({"code": 404, "msg": "Agent 会话不存在", "data": None}), 404
        return jsonify({"code": 200, "msg": "Agent 会话已删除", "data": {"sessionId": session_id, "deleted": True}}), 200
    except Exception as exc:
        return jsonify({"code": 500, "msg": "删除 Agent 会话失败，请稍后重试", "data": None}), 500


@app.route('/agents/sessions/<session_id>/compact', methods=['POST'])
def compact_agent_session_route(session_id):
    try:
        result = compact_agent_session(session_id, force=True)
        if not result:
            return jsonify({"code": 404, "msg": "Agent 会话不存在或已删除", "data": None}), 404
        return jsonify({"code": 200, "msg": "Agent 会话已压缩", "data": result}), 200
    except Exception as exc:
        return jsonify({"code": 500, "msg": "压缩 Agent 会话失败，请稍后重试", "data": None}), 500


@app.route('/agents/sessions/<session_id>/context', methods=['GET'])
def agent_session_context(session_id):
    session = get_agent_session(session_id)
    if not session:
        return jsonify({"code": 404, "msg": "Agent 会话不存在或已删除", "data": None}), 404
    return jsonify({"code": 200, "msg": "success", "data": session.get("contextStats") or {}}), 200


@app.route('/agents/sessions/<session_id>/compact/stream', methods=['POST'])
def compact_agent_session_stream_route(session_id):
    response = Response(stream_with_context(run_agent_session_compaction_stream(session_id)), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route('/agents/sessions/<session_id>/messages', methods=['GET'])
def agent_session_messages(session_id):
    try:
        limit = max(1, min(int(request.args.get("limit", 12) or 12), 99))
        items = list_agent_messages(
            session_id,
            limit + 1,
            request.args.get("beforeId"),
        )
        has_more = len(items) > limit
        if has_more:
            items = items[-limit:]
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "items": items,
                "hasMore": has_more,
                "nextBeforeId": items[0]["id"] if has_more and items else None,
            },
        }), 200
    except (TypeError, ValueError) as exc:
        return jsonify({"code": 400, "msg": f"读取 Agent 会话失败: {str(exc)}", "data": None}), 400
    except Exception as exc:
        return jsonify({"code": 500, "msg": "读取 Agent 会话失败，请稍后重试", "data": None}), 500


@app.route('/agents/runs/<run_id>', methods=['GET'])
def agent_run_detail(run_id):
    run = get_agent_run(run_id)
    if not run:
        return jsonify({"code": 404, "msg": "Agent 运行记录不存在", "data": None}), 404
    return jsonify({"code": 200, "msg": "success", "data": run}), 200


@app.route('/agents/prepublish-check', methods=['POST'])
def agent_prepublish_check():
    payload = request.get_json(silent=True) or {}
    try:
        data = payload.get("publishData") if "publishData" in payload else payload
        targets = normalize_publish_targets(data)
        file_list, publish_materials = _validate_publish_processed_files(data.get("fileList", []), _current_account_owner_id())
        _assert_publish_targets_available(publish_materials[0], targets)
        result = run_prepublish_guard(data, file_list, targets, publish_materials, session_id=payload.get("sessionId") or "")
        result = agent_guard_run_payload(get_agent_run(result.get("runId")), agent_content_hash(data, file_list, targets)) or result
        return jsonify({"code": 200, "msg": "质检完成", "data": result}), 200
    except WorkflowConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc), "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data}}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        return jsonify({"code": 500, "msg": "发布前质检失败，请稍后重试", "data": None}), 500


@app.route('/agents/prepublish-check/latest', methods=['POST'])
def latest_agent_prepublish_check():
    payload = request.get_json(silent=True) or {}
    try:
        data = payload.get("publishData") if "publishData" in payload else payload
        targets = normalize_publish_targets(data)
        file_list, publish_materials = _validate_publish_processed_files(data.get("fileList", []), _current_account_owner_id())
        material_id = str(publish_materials[0].get("id") or "")
        run = get_latest_agent_run(
            "prepublish_check",
            subject_type="material",
            subject_id=material_id,
            legacy_file_path=file_list[0],
        )
        result = agent_guard_run_payload(run, agent_content_hash(data, file_list, targets))
        if result:
            result["materialId"] = material_id
        return jsonify({"code": 200, "msg": "success", "data": result}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        return jsonify({"code": 500, "msg": "读取发布前质检记录失败，请稍后重试", "data": None}), 500
