@app.route('/publish/tag-presets', methods=['GET'])
def get_publish_tag_presets_route():
    try:
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": get_publish_tag_presets(_current_account_owner_id()),
        }), 200
    except PermissionError as exc:
        return jsonify({"code": 401, "msg": str(exc), "data": None}), 401
    except Exception as exc:
        backend_logger.exception("get publish tag presets failed")
        return jsonify({"code": 500, "msg": "获取平台通用标签失败", "data": None}), 500


@app.route('/publish/tag-presets', methods=['PATCH'])
def update_publish_tag_presets_route():
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify({
            "code": 200,
            "msg": "平台通用标签已保存",
            "data": update_publish_tag_presets(_current_account_owner_id(), payload),
        }), 200
    except PermissionError as exc:
        return jsonify({"code": 401, "msg": str(exc), "data": None}), 401
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("update publish tag presets failed")
        return jsonify({"code": 500, "msg": "保存平台通用标签失败", "data": None}), 500


@app.route('/postVideo', methods=['POST'])
def postVideo():
    data = request.get_json()
    try:
        result = _publish_payload(data)
    except AgentGuardError as exc:
        return jsonify({"code": exc.status_code, "msg": str(exc), "data": {"errorCode": exc.error_code, "guard": exc.result}}), exc.status_code
    except WorkflowConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc), "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data}}), 409
    except PublishQueueFullError as exc:
        return jsonify({"code": 429, "msg": str(exc), "data": {"errorCode": exc.error_code}}), 429
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as e:
        backend_logger.exception("publish video failed")
        return jsonify({
            "code": 500,
            "msg": "发布失败，请稍后重试",
            "data": None,
        }), 500
    return jsonify({
        "code": 202,
        "msg": "发布任务已进入队列",
        "data": result,
    }), 202


@app.route('/updateUserinfo', methods=['POST'])
def updateUserinfo():
    # 获取JSON数据
    data = request.get_json()

    # 从JSON数据中提取 type 和 userName
    user_id = data.get('id')
    type = data.get('type')
    userName = data.get('userName')
    try:
        owner_user_id = _current_account_owner_id()
        # 获取数据库连接
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()

            # 更新数据库记录
            cursor.execute('''
                           UPDATE user_info
                           SET type     = %s,
                               userName = %s
                           WHERE id = %s AND owner_user_id = %s;
                           ''', (type, userName, user_id, owner_user_id))
            if cursor.rowcount != 1:
                return jsonify({"code": 404, "msg": "账号不存在", "data": None}), 404
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account update successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("update failed!"),
            "data": None
        }), 500

@app.route('/postVideoBatch', methods=['POST'])
def postVideoBatch():
    data_list = request.get_json()

    if not isinstance(data_list, list):
        return jsonify({"code": 400, "msg": "Expected a JSON array", "data": None}), 400
    batch_results = []
    for index, data in enumerate(data_list):
        try:
            batch_results.append({
                "index": index,
                "status": "accepted",
                "data": _publish_payload(data),
            })
        except AgentGuardError as exc:
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": str(exc),
                "data": {"errorCode": exc.error_code, "guard": exc.result},
            })
        except WorkflowConflictError as exc:
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": str(exc),
                "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data},
            })
        except PublishQueueFullError as exc:
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": str(exc),
                "data": {"errorCode": exc.error_code},
            })
        except Exception as exc:
            backend_logger.exception("publish batch item failed : index = %s", index)
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": "发布失败，请稍后重试",
                "data": None,
            })
    failed_count = sum(
        1
        for item in batch_results
        if item["status"] != "accepted"
        or (isinstance(item.get("data"), dict) and item["data"].get("hasFailures"))
    )
    return jsonify({
        "code": 202,
        "msg": "部分批次发布失败" if failed_count else "发布任务已提交",
        "data": {
            "items": batch_results,
            "hasFailures": failed_count > 0,
        }
    }), 202


@app.route('/bilibili/categories', methods=['GET'])
def get_bilibili_categories():
    return jsonify({
        "code": 200,
        "msg": "success",
        "data": {
            "items": bilibili_categories(),
            "defaultTid": BILIBILI_DEFAULT_TID,
        },
    }), 200

# Cookie文件上传API
