"""Flask 认证、CSRF 和角色边界。"""

from __future__ import annotations

import hmac

from flask import g, jsonify, request

from app.auth.service import csrf_token_for, record_audit, resolve_session
from app.config import AUTH_ALLOW_COOKIE_EXPORT, AUTH_COOKIE_NAME


_PUBLIC_PATHS = {"/", "/favicon.ico", "/vite.svg", "/auth/login"}
_ADMIN_PATHS = {
    "/account", "/accounts/check-cookies", "/deleteAccount", "/downloadCookie",
    "/getValidAccounts", "/updateUserinfo", "/uploadCookie", "/login",
}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _json_error(status, message, code):
    return jsonify({"code": status, "msg": message, "data": {"errorCode": code}}), status


def _is_public_request():
    return request.method == "OPTIONS" or request.path in _PUBLIC_PATHS or request.path.startswith("/assets/")


def _requires_admin():
    if request.path.startswith(("/admin/users", "/admin/audit-logs")):
        return True
    if request.path in _ADMIN_PATHS:
        return True
    return request.path == "/youtube/workflow/settings" and request.method in {"PUT", "PATCH"}


def register_auth_middleware(app):
    @app.before_request
    def authenticate_application_request():
        g.current_user = None
        g.auth_token = ""
        if app.config.get("AUTH_TEST_BYPASS"):
            return None
        if _is_public_request():
            return None
        token = request.cookies.get(AUTH_COOKIE_NAME, "")
        session = resolve_session(token)
        if not session:
            return _json_error(401, "登录状态已失效，请重新登录", "AUTH_REQUIRED")
        g.current_user = session["user"]
        g.auth_token = token
        if _requires_admin() and g.current_user["role"] != "admin":
            return _json_error(403, "当前用户没有管理员权限", "ADMIN_REQUIRED")
        if request.path == "/downloadCookie" and not AUTH_ALLOW_COOKIE_EXPORT:
            return _json_error(403, "部署配置已禁用 Cookie 导出", "COOKIE_EXPORT_DISABLED")
        requires_csrf = request.method in _UNSAFE_METHODS or request.path == "/login"
        if requires_csrf:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, csrf_token_for(token)):
                return _json_error(403, "CSRF 校验失败，请刷新页面后重试", "CSRF_INVALID")
        if g.current_user["mustChangePassword"] and request.path not in {"/auth/me", "/auth/change-password", "/auth/logout"}:
            return _json_error(403, "首次登录必须先修改密码", "PASSWORD_CHANGE_REQUIRED")
        return None

    @app.after_request
    def secure_and_audit_response(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        user = getattr(g, "current_user", None)
        if user and (request.method in _UNSAFE_METHODS or request.path == "/login") and not request.path.startswith("/auth/"):
            try:
                record_audit(
                    "HTTP_MUTATION", "success" if response.status_code < 400 else "failure",
                    actor_user_id=user["id"], target_type="http", target_id=request.path,
                    details={"method": request.method, "status": response.status_code},
                    ip_address=request.remote_addr, user_agent=request.user_agent.string,
                )
            except Exception:
                app.logger.exception("auth audit write failed : path = %s | method = %s", request.path, request.method)
        return response
