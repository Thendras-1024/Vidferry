@app.route('/agents/status', methods=['GET'])
def agent_status():
    return jsonify({
        "code": 200,
        "msg": "success",
        "data": {
            "enabled": AGENT_ENABLED,
            "chatModel": AGENT_CHAT_MODEL,
            "visionModelConfigured": bool(AGENT_VISION_MODEL),
            "requirePrepublishCheck": AGENT_REQUIRE_PREPUBLISH_CHECK,
            "blockLevel": AGENT_BLOCK_LEVEL,
            "maxToolRows": AGENT_MAX_TOOL_ROWS,
            "maxToolCalls": AGENT_MAX_TOOL_CALLS,
            "chatTemperature": AGENT_CHAT_TEMPERATURE,
            "chatMaxTokens": AGENT_CHAT_MAX_TOKENS,
            "guardTemperature": AGENT_GUARD_TEMPERATURE,
            "guardMaxTokens": AGENT_GUARD_MAX_TOKENS,
            "requireVisionCheck": AGENT_REQUIRE_VISION_CHECK,
            "visionFailClosed": AGENT_VISION_FAIL_CLOSED,
            "frameMaxCount": AGENT_FRAME_MAX_COUNT,
            "frameScaleWidth": AGENT_FRAME_SCALE_WIDTH,
        }
    }), 200


@app.route('/agents/chat', methods=['POST'])
def agent_chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"code": 400, "msg": "请输入要询问 Agent 的内容", "data": None}), 400
    try:
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": run_agent_chat(
                message,
                session_id=payload.get("sessionId") or "",
                context=payload.get("context") or {},
            )
        }), 200
    except Exception as exc:
        return jsonify({"code": 500, "msg": f"Agent 对话失败: {str(exc)}", "data": None}), 500


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
        file_list, publish_materials = _validate_publish_processed_files(data.get("fileList", []))
        _assert_publish_targets_available(publish_materials[0], targets)
        result = run_prepublish_guard(data, file_list, targets, publish_materials, session_id=payload.get("sessionId") or "")
        return jsonify({"code": 200, "msg": "质检完成", "data": result}), 200
    except WorkflowConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc), "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data}}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        return jsonify({"code": 500, "msg": f"发布前质检失败: {str(exc)}", "data": None}), 500
