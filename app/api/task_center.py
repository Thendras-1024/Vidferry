"""任务中心 API。"""

from flask import g


def _task_center_user_id():
    user = getattr(g, "current_user", None) or {}
    return int(user.get("id"))


@app.route("/task-center", methods=["GET"])
def task_center_list():
    try:
        history = request.args.get("view") == "history"
        active_only = request.args.get("activeOnly") == "1"
        return jsonify({"code": 200, "msg": "success", "data": list_task_center(_task_center_user_id(), history=history, active_only=active_only)})
    except Exception:
        backend_logger.exception("任务中心列表读取失败")
        return jsonify({"code": 500, "msg": "读取任务中心失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>", methods=["GET"])
def task_center_detail(task_key):
    try:
        return jsonify({"code": 200, "msg": "success", "data": get_task_center_detail(task_key, _task_center_user_id())})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心详情读取失败")
        return jsonify({"code": 500, "msg": "读取任务详情失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>/acknowledge", methods=["POST"])
def task_center_acknowledge(task_key):
    try:
        item = acknowledge_task_center_task(task_key, _task_center_user_id())
        return jsonify({"code": 200, "msg": "已记录知晓状态", "data": item})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心知晓状态写入失败")
        return jsonify({"code": 500, "msg": "记录任务知晓状态失败，请稍后重试。", "data": None}), 500
