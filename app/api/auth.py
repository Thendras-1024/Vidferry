"""应用用户认证 API。"""

from flask import g

from app.auth.service import (
    AuthError, authenticate, change_password, csrf_token_for, record_audit,
    revoke_session, revoke_user_sessions,
)
from app.config import AUTH_COOKIE_NAME, AUTH_COOKIE_SECURE, AUTH_REMEMBER_TIMEOUT_HOURS


def _auth_error_response(exc):
    return jsonify({"code": exc.status, "msg": exc.message, "data": {"errorCode": exc.code}}), exc.status


def _set_auth_cookie(response, token, *, remember=False):
    response.set_cookie(
        AUTH_COOKIE_NAME, token, secure=AUTH_COOKIE_SECURE, httponly=True,
        samesite="Lax", path="/",
        max_age=AUTH_REMEMBER_TIMEOUT_HOURS * 3600 if remember else None,
    )


def _clear_auth_cookie(response):
    response.delete_cookie(AUTH_COOKIE_NAME, secure=AUTH_COOKIE_SECURE, httponly=True, samesite="Lax", path="/")


@app.route("/auth/login", methods=["POST"])
def auth_login():
    payload = request.get_json(silent=True) or {}
    remember = payload.get("remember") is True
    try:
        user, token, csrf_token = authenticate(
            payload.get("username"), payload.get("password"), request.remote_addr, request.user_agent.string,
            remember=remember,
        )
    except AuthError as exc:
        return _auth_error_response(exc)
    response = jsonify({"code": 200, "msg": "登录成功", "data": {"user": user, "csrfToken": csrf_token}})
    _set_auth_cookie(response, token, remember=remember)
    return response


@app.route("/auth/me", methods=["GET"])
def auth_me():
    return jsonify({"code": 200, "msg": "success", "data": {
        "user": g.current_user, "csrfToken": csrf_token_for(g.auth_token),
    }})


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    user = g.current_user
    revoke_session(g.auth_token)
    record_audit("AUTH_LOGOUT", "success", actor_user_id=user["id"], target_type="user",
                 target_id=user["id"], ip_address=request.remote_addr, user_agent=request.user_agent.string)
    response = jsonify({"code": 200, "msg": "已退出登录", "data": None})
    _clear_auth_cookie(response)
    return response


@app.route("/auth/change-password", methods=["POST"])
def auth_change_password():
    payload = request.get_json(silent=True) or {}
    try:
        change_password(g.current_user["id"], payload.get("currentPassword"), payload.get("newPassword"))
    except (AuthError, ValueError) as exc:
        error = exc if isinstance(exc, AuthError) else AuthError(str(exc))
        return _auth_error_response(error)
    record_audit("AUTH_PASSWORD_CHANGE", "success", actor_user_id=g.current_user["id"],
                 target_type="user", target_id=g.current_user["id"], ip_address=request.remote_addr,
                 user_agent=request.user_agent.string)
    response = jsonify({"code": 200, "msg": "密码已修改，请重新登录", "data": None})
    _clear_auth_cookie(response)
    return response


@app.route("/auth/logout-all", methods=["POST"])
def auth_logout_all():
    count = revoke_user_sessions(g.current_user["id"])
    response = jsonify({"code": 200, "msg": "所有会话已注销", "data": {"revoked": count}})
    _clear_auth_cookie(response)
    return response
