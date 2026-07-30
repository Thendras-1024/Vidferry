"""管理员用户与审计 API。"""

from flask import g

from app.auth.admin_service import list_audit_logs, list_users, reset_password, unlock_user, update_user
from app.auth.service import AuthError, create_user, record_audit, revoke_user_sessions


def _admin_error(exc):
    error = exc if isinstance(exc, AuthError) else AuthError(str(exc))
    return jsonify({"code": error.status, "msg": error.message, "data": {"errorCode": error.code}}), error.status


@app.route("/admin/users", methods=["GET"])
def admin_users_list():
    try:
        data = list_users(request.args.get("page", 1), request.args.get("pageSize", 50), request.args.get("keyword", ""))
        return jsonify({"code": 200, "msg": "success", "data": data})
    except (AuthError, ValueError) as exc:
        return _admin_error(exc)


@app.route("/admin/users", methods=["POST"])
def admin_users_create():
    payload = request.get_json(silent=True) or {}
    try:
        user = create_user(
            payload.get("username"), payload.get("displayName"), payload.get("password"),
            payload.get("role", "user"), created_by=g.current_user["id"], must_change_password=True,
        )
    except (AuthError, ValueError) as exc:
        return _admin_error(exc)
    record_audit("USER_CREATE", "success", actor_user_id=g.current_user["id"], target_type="user",
                 target_id=user["id"], details={"role": user["role"]}, ip_address=request.remote_addr,
                 user_agent=request.user_agent.string)
    return jsonify({"code": 201, "msg": "用户已创建", "data": user}), 201


@app.route("/admin/users/<int:user_id>", methods=["PATCH"])
def admin_users_update(user_id):
    payload = request.get_json(silent=True) or {}
    try:
        user = update_user(user_id, payload, g.current_user["id"])
    except (AuthError, ValueError) as exc:
        return _admin_error(exc)
    record_audit("USER_UPDATE", "success", actor_user_id=g.current_user["id"], target_type="user",
                 target_id=user_id, details={"role": user["role"], "status": user["status"]},
                 ip_address=request.remote_addr, user_agent=request.user_agent.string)
    return jsonify({"code": 200, "msg": "用户已更新", "data": user})


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
def admin_users_reset_password(user_id):
    try:
        reset_password(user_id, (request.get_json(silent=True) or {}).get("password"))
    except (AuthError, ValueError) as exc:
        return _admin_error(exc)
    record_audit("USER_PASSWORD_RESET", "success", actor_user_id=g.current_user["id"],
                 target_type="user", target_id=user_id, ip_address=request.remote_addr,
                 user_agent=request.user_agent.string)
    return jsonify({"code": 200, "msg": "密码已重置", "data": None})


@app.route("/admin/users/<int:user_id>/unlock", methods=["POST"])
def admin_users_unlock(user_id):
    try:
        unlock_user(user_id)
    except AuthError as exc:
        return _admin_error(exc)
    return jsonify({"code": 200, "msg": "用户已解锁", "data": None})


@app.route("/admin/users/<int:user_id>/revoke-sessions", methods=["POST"])
def admin_users_revoke_sessions(user_id):
    count = revoke_user_sessions(user_id)
    return jsonify({"code": 200, "msg": "用户会话已撤销", "data": {"revoked": count}})


@app.route("/admin/audit-logs", methods=["GET"])
def admin_audit_logs():
    try:
        data = list_audit_logs(request.args.get("page", 1), request.args.get("pageSize", 50), request.args.get("action", ""))
        return jsonify({"code": 200, "msg": "success", "data": data})
    except ValueError as exc:
        return _admin_error(exc)
