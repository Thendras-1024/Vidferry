"""任务中心 API。"""

from flask import g
from app.auth.service import record_audit


_ADMIN_REDACTED_FIELDS = {
    "accountFile", "filePath", "inputFilePath", "outputFilePath", "sourceFilePath",
    "processedFilePath", "downloadedFilePath", "transcriptFilePath", "rawOutput", "llmOutput",
}


def _redact_admin_task_data(value):
    if isinstance(value, list):
        return [_redact_admin_task_data(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_admin_task_data(item)
            for key, item in value.items()
            if key not in _ADMIN_REDACTED_FIELDS
        }
    return value


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
                _task_center_user_id(), is_admin=False,
                task_type=request.args.get("type", "all"), status=request.args.get("status", "all"),
                keyword=request.args.get("keyword", ""), owner=request.args.get("owner", "all"),
                updated_from=request.args.get("updatedFrom", ""), updated_to=request.args.get("updatedTo", ""),
                sort=request.args.get("sort", "updated_desc"), page=request.args.get("page", 1),
                page_size=request.args.get("pageSize", 20),
            )})
        active_only = request.args.get("activeOnly") == "1"
        return jsonify({"code": 200, "msg": "success", "data": list_task_center(
            _task_center_user_id(), is_admin=False, history=history, active_only=active_only,
            result=request.args.get("result", "all"), scope=request.args.get("scope", "all"),
            page=request.args.get("page", 1), page_size=request.args.get("pageSize", 20),
        )})
    except Exception:
        backend_logger.exception("任务中心列表读取失败")
        return jsonify({"code": 500, "msg": "读取任务中心失败，请稍后重试。", "data": None}), 500


@app.route("/admin/task-center", methods=["GET"])
def admin_task_center_list():
    try:
        data = list_all_task_center(
            _task_center_user_id(), is_admin=True,
            task_type=request.args.get("type", "all"), status=request.args.get("status", "all"),
            keyword=request.args.get("keyword", ""), owner=request.args.get("owner", "all"),
            updated_from=request.args.get("updatedFrom", ""), updated_to=request.args.get("updatedTo", ""),
            sort=request.args.get("sort", "updated_desc"), page=request.args.get("page", 1),
            page_size=request.args.get("pageSize", 20),
        )
        record_audit(
            "ADMIN_BUSINESS_READ", "success", actor_user_id=_task_center_user_id(),
            target_type="task_center", target_id=str(request.args.get("owner", "all")),
            details={"page": request.args.get("page", 1)},
            ip_address=request.remote_addr, user_agent=request.user_agent.string,
        )
        return jsonify({"code": 200, "msg": "success", "data": _redact_admin_task_data(data)})
    except Exception:
        backend_logger.exception("管理员任务中心列表读取失败")
        return jsonify({"code": 500, "msg": "读取管理员任务中心失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>", methods=["GET"])
def task_center_detail(task_key):
    try:
        return jsonify({"code": 200, "msg": "success", "data": get_task_center_detail(
            task_key, _task_center_user_id(), is_admin=False,
        )})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心详情读取失败")
        return jsonify({"code": 500, "msg": "读取任务详情失败，请稍后重试。", "data": None}), 500


@app.route("/task-center/<path:task_key>/acknowledge", methods=["POST"])
def task_center_acknowledge(task_key):
    try:
        item = acknowledge_task_center_task(task_key, _task_center_user_id(), is_admin=False)
        return jsonify({"code": 200, "msg": "已记录知晓状态", "data": item})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc), "data": None}), 404
    except Exception:
        backend_logger.exception("任务中心知晓状态写入失败")
        return jsonify({"code": 500, "msg": "记录任务知晓状态失败，请稍后重试。", "data": None}), 500
