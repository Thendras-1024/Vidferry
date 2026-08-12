"""任务中心 API。"""

from flask import g


def _task_center_user_id():
    user = getattr(g, "current_user", None) or {}
    return int(user.get("id"))


def _task_center_is_admin():
    user = getattr(g, "current_user", None) or {}
    return user.get("role") == "admin"


@app.route("/task-center", methods=["GET"])
def task_center_list():
    try:
        history = request.args.get("view") == "history"
        if request.args.get("view") == "all":
            return jsonify({"code": 200, "msg": "success", "data": list_all_task_center(
                _task_center_user_id(), is_admin=_task_center_is_admin(),
                task_type=request.args.get("type", "all"), status=request.args.get("status", "all"),
                keyword=request.args.get("keyword", ""), owner=request.args.get("owner", "all"),
                updated_from=request.args.get("updatedFrom", ""), updated_to=request.args.get("updatedTo", ""),
                sort=request.args.get("sort", "updated_desc"), page=request.args.get("page", 1),
                page_size=request.args.get("pageSize", 20),
            )})
        active_only = request.args.get("activeOnly") == "1"
        return jsonify({"code": 200, "msg": "success", "data": list_task_center(
            _task_center_user_id(), is_admin=_task_center_is_admin(), history=history, active_only=active_only,
            result=request.args.get("result", "all"), scope=request.args.get("scope", "all"),
            page=request.args.get("page", 1), page_size=request.args.get("pageSize", 20),
        )})
    except Exception:
        backend_logger.exception("任务中心列表读取失败")
        return jsonify({"code": 500, "msg": "读取任务中心失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>", methods=["GET"])
def task_center_detail(task_key):
    try:
        return jsonify({"code": 200, "msg": "success", "data": get_task_center_detail(
            task_key, _task_center_user_id(), is_admin=_task_center_is_admin(),
        )})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心详情读取失败")
        return jsonify({"code": 500, "msg": "读取任务详情失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>/acknowledge", methods=["POST"])
def task_center_acknowledge(task_key):
    try:
        item = acknowledge_task_center_task(task_key, _task_center_user_id(), is_admin=_task_center_is_admin())
        return jsonify({"code": 200, "msg": "已记录知晓状态", "data": item})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心知晓状态写入失败")
        return jsonify({"code": 500, "msg": "记录任务知晓状态失败，请稍后重试。", "data": None}), 500
