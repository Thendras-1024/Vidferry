@app.route('/published-materials', methods=['GET'])
def published_materials():
    try:
        limit = int(request.args.get("limit", 50))
        record_scope = request.args.get("recordScope", "active")
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_published_youtube_materials(limit, record_scope)
        }), 200
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e), "data": None}), 400
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取已发布素材失败: {str(e)}", "data": None}), 500


@app.route('/publish/tasks', methods=['GET'])
def publish_tasks():
    try:
        limit = int(request.args.get("limit", 20))
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_publish_tasks(limit)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取发布任务失败: {str(e)}", "data": None}), 500


@app.route('/publish/tasks/<task_id>/retry-failed', methods=['POST'])
def retry_failed_publish(task_id):
    try:
        result = prepare_failed_publish_retry(task_id)
        try:
            _submit_background_task("publish", run_failed_publish_retry, result["tasks"])
        except Exception:
            fail_failed_publish_retry_submission(result["tasks"], "重发任务提交失败")
            raise
        return jsonify({
            "code": 202,
            "msg": "失败平台已开始重发",
            "data": {key: value for key, value in result.items() if key != "tasks"},
        }), 202
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except WorkflowConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc), "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data}}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("publish retry failed : task_id = %s | error_type = %s", task_id, type(exc).__name__)
        return jsonify({"code": 500, "msg": f"重发失败: {exc}", "data": None}), 500


@app.route('/publish/target-records/<int:record_id>', methods=['DELETE'])
def delete_publish_target(record_id):
    try:
        return jsonify({
            "code": 200,
            "msg": "已删除本地发布记录，平台上的已发布视频不会被删除。",
            "data": delete_publish_target_record(record_id)
        }), 200
    except LookupError as e:
        return jsonify({"code": 404, "msg": str(e), "data": None}), 404
    except WorkflowConflictError as e:
        return jsonify({
            "code": 409,
            "msg": str(e),
            "data": {
                "errorCode": e.error_code,
                "errorType": e.error_type,
                **e.data,
            }
        }), 409
    except Exception as e:
        return jsonify({"code": 500, "msg": f"删除发布记录失败: {str(e)}", "data": None}), 500


@app.route('/publish/scheduled-tasks', methods=['POST'])
def create_scheduled_publish():
    try:
        task = create_scheduled_publish_task(request.get_json(silent=True) or {})
        return _json_response(data=task, status=201)
    except AgentGuardError as exc:
        return _json_response(exc.status_code, str(exc), {"errorCode": exc.error_code, "guard": exc.result}, exc.status_code)
    except WorkflowConflictError as exc:
        return _error_response(409, str(exc), exc.error_code, exc.error_type, exc.data)
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception as exc:
        backend_logger.exception("scheduled publish create failed : error_type = %s", type(exc).__name__)
        return _json_response(500, f"创建定时发布任务失败: {exc}", None, 500)


@app.route('/publish/scheduled-tasks', methods=['GET'])
def scheduled_publish_tasks():
    try:
        return _json_response(data=list_scheduled_publish_tasks(request.args))
    except Exception as exc:
        backend_logger.exception("scheduled publish list failed : error_type = %s", type(exc).__name__)
        return _json_response(500, f"获取定时发布任务失败: {exc}", None, 500)


@app.route('/publish/scheduled-tasks/<task_id>/cancel', methods=['POST'])
def cancel_scheduled_publish(task_id):
    try:
        return _json_response(data=cancel_scheduled_publish_task(task_id))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except WorkflowConflictError as exc:
        return _error_response(409, str(exc), exc.error_code, exc.error_type, exc.data)
    except Exception as exc:
        backend_logger.exception("scheduled publish cancel failed : task_id = %s | error_type = %s", task_id, type(exc).__name__)
        return _json_response(500, f"取消定时发布任务失败: {exc}", None, 500)
