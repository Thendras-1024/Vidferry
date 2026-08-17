"""通知中心 API。"""


@app.route("/notifications/summary", methods=["GET"])
def notifications_summary():
    try:
        return jsonify({"code": 200, "msg": "success", "data": notification_summary(_current_account_owner_id())})
    except Exception as exc:
        backend_logger.exception("通知摘要读取失败")
        return jsonify({"code": 500, "msg": f"读取通知摘要失败: {exc}", "data": None}), 500


@app.route("/notifications", methods=["GET"])
def notifications_list():
    try:
        state = request.args.get("state", "active")
        if state not in {"active", "history"}:
            raise ValueError("state 仅支持 active 或 history")
        return jsonify({"code": 200, "msg": "success", "data": list_notifications(state, request.args.get("page", 1), request.args.get("pageSize", 50), _current_account_owner_id())})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("通知列表读取失败")
        return jsonify({"code": 500, "msg": f"读取通知列表失败: {exc}", "data": None}), 500


@app.route("/notifications/<int:notification_id>", methods=["PATCH"])
def notifications_update(notification_id):
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify({"code": 200, "msg": "success", "data": update_notification_state(notification_id, payload.get("state"), _current_account_owner_id())})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("通知状态更新失败 : notificationId = %s", notification_id)
        return jsonify({"code": 500, "msg": f"更新通知状态失败: {exc}", "data": None}), 500


@app.route("/notifications/direct-publish-failure", methods=["POST"])
def notifications_direct_publish_failure():
    try:
        return jsonify({"code": 200, "msg": "success", "data": create_direct_publish_failure_notification(request.get_json(silent=True) or {}, _current_account_owner_id())})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        backend_logger.exception("直接发布失败通知写入失败")
        return jsonify({"code": 500, "msg": f"写入直接发布失败通知失败: {exc}", "data": None}), 500
