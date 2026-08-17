"""Flask 认证、CSRF 和角色边界。"""

from __future__ import annotations

import hmac
import datetime as dt
import ipaddress

from flask import g, jsonify, request

from app.auth.service import csrf_token_for, record_audit, resolve_session
from app.auth.phone_service import _consume_rate, _rate_hash
from app.auth.service import AuthError
from app.config import (
    AUTH_ALLOW_COOKIE_EXPORT, AUTH_COOKIE_NAME,
    AUTH_TRUSTED_PROXY_CIDRS,
    USER_TASK_SUBMISSIONS_PER_MINUTE, USER_UPLOADS_PER_MINUTE,
)


_PUBLIC_PATHS = {
    "/", "/favicon.ico", "/vite.svg", "/auth/login", "/auth/public-config",
    "/auth/phone/send-code", "/auth/phone/login",
}
_ADMIN_PATHS = {
    "/login",
}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_UPLOAD_PATHS = {"/upload", "/uploadSave"}
_TASK_SUBMISSION_PATHS = {
    "/youtube/search/jobs", "/youtube/workflow/jobs", "/youtube/download/jobs",
    "/youtube/translate/jobs", "/youtube/analysis/jobs", "/youtube/editing/intro/jobs",
    "/postVideo", "/postVideoBatch", "/publish/scheduled-tasks",
}


def _json_error(status, message, code):
    return jsonify({"code": status, "msg": message, "data": {"errorCode": code}}), status


def _is_public_request():
    return (
        request.method == "OPTIONS"
        or request.path in _PUBLIC_PATHS
        or request.path.startswith("/assets/") and request.path.count("/") == 2
        or request.path == "/vidferry-icon.svg"
    )


def _request_uses_https():
    if request.is_secure:
        return True
    try:
        peer = ipaddress.ip_address(str(request.remote_addr or ""))
        trusted = any(peer in ipaddress.ip_network(cidr, strict=False) for cidr in AUTH_TRUSTED_PROXY_CIDRS)
    except ValueError:
        trusted = False
    return trusted and request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower() == "https"


def _requires_admin():
    if request.path.startswith("/admin/"):
        return True
    if request.path in _ADMIN_PATHS:
        return True
    return request.path == "/youtube/workflow/settings" and request.method in {"PUT", "PATCH"}


def _rate_limit_user_submission(user_id):
    if request.method != "POST":
        return None
    if request.path in _UPLOAD_PATHS:
        scope, limit = "user_upload", USER_UPLOADS_PER_MINUTE
    elif (
        request.path in _TASK_SUBMISSION_PATHS
        or request.path.endswith(("/search", "/review", "/render", "/retry-failed"))
        or request.path.startswith("/agents/execution-proposals/")
    ):
        scope, limit = "user_task_submission", USER_TASK_SUBMISSIONS_PER_MINUTE
    else:
        return None
    try:
        _consume_rate(scope, _rate_hash(str(int(user_id))), limit, dt.timedelta(minutes=1))
    except AuthError as exc:
        return _json_error(exc.status, exc.message, exc.code)
    return None


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
        rate_limited = _rate_limit_user_submission(g.current_user["id"])
        if rate_limited:
            return rate_limited
        return None

    @app.after_request
    def secure_and_audit_response(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
        if _request_uses_https():
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
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
