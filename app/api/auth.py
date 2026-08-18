"""应用用户认证 API。"""

import ipaddress

from flask import g

from app.auth.phone_service import (
    audit_hash, authenticate_phone, captcha_is_configured, clear_password_login_failures,
    check_password_login_rate, password_captcha_required, phone_login_is_configured, record_password_login_failure,
    send_phone_code, verify_tencent_captcha,
)
from app.auth.service import (
    AuthError, authenticate, change_password, csrf_token_for, record_audit,
    revoke_session, revoke_user_sessions,
)
from app.config import (
    AUTH_COOKIE_NAME, AUTH_COOKIE_SECURE, AUTH_REMEMBER_TIMEOUT_HOURS,
    AUTH_TENCENT_CAPTCHA_APP_ID, AUTH_TRUSTED_PROXY_CIDRS,
)


def _auth_error_response(exc):
    return jsonify({"code": exc.status, "msg": exc.message, "data": {"errorCode": exc.code, **exc.data}}), exc.status


def _set_auth_cookie(response, token, *, remember=False):
    response.set_cookie(
        AUTH_COOKIE_NAME, token, secure=AUTH_COOKIE_SECURE, httponly=True,
        samesite="Lax", path="/",
        max_age=AUTH_REMEMBER_TIMEOUT_HOURS * 3600 if remember else None,
    )


def _clear_auth_cookie(response):
    response.delete_cookie(AUTH_COOKIE_NAME, secure=AUTH_COOKIE_SECURE, httponly=True, samesite="Lax", path="/")


def _client_ip():
    remote = str(request.remote_addr or "")[:128]
    try:
        peer = ipaddress.ip_address(remote)
        trusted = any(peer in ipaddress.ip_network(cidr, strict=False) for cidr in AUTH_TRUSTED_PROXY_CIDRS)
    except ValueError:
        trusted = False
    if trusted:
        forwarded = str(request.headers.get("X-Forwarded-For", "")).split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return remote


@app.route("/auth/public-config", methods=["GET"])
def auth_public_config():
    return jsonify({"code": 200, "msg": "success", "data": {
        "phoneLoginEnabled": phone_login_is_configured(),
        "captchaAppId": AUTH_TENCENT_CAPTCHA_APP_ID if captcha_is_configured() else "",
    }})


@app.route("/auth/login", methods=["POST"])
def auth_login():
    payload = request.get_json(silent=True) or {}
    remember = payload.get("remember") is True
    username = payload.get("username")
    client_ip = _client_ip()
    identity_hash = audit_hash(str(username or "").strip().lower()[:128])
    try:
        check_password_login_rate(username, client_ip)
        if password_captcha_required(username):
            verify_tencent_captcha(payload.get("captchaTicket"), payload.get("captchaRandstr"), client_ip)
        user, token, csrf_token = authenticate(
            username, payload.get("password"), client_ip, request.user_agent.string, remember=remember,
            audit_identity=identity_hash, audit_ip_address=audit_hash(client_ip),
        )
    except AuthError as exc:
        if exc.code == "INVALID_CREDENTIALS":
            record_password_login_failure(username, client_ip)
            exc.data["captchaRequired"] = password_captcha_required(username)
        return _auth_error_response(exc)
    clear_password_login_failures(username, client_ip)
    response = jsonify({"code": 200, "msg": "登录成功", "data": {"user": user, "csrfToken": csrf_token}})
    _set_auth_cookie(response, token, remember=remember)
    return response


@app.route("/auth/phone/send-code", methods=["POST"])
def auth_phone_send_code():
    payload = request.get_json(silent=True) or {}
    try:
        data = send_phone_code(
            payload.get("phone"), payload.get("captchaTicket"), payload.get("captchaRandstr"),
            _client_ip(), request.user_agent.string,
        )
    except AuthError as exc:
        return _auth_error_response(exc)
    return jsonify({"code": 200, "msg": "验证码已发送", "data": data})


@app.route("/auth/phone/login", methods=["POST"])
def auth_phone_login():
    payload = request.get_json(silent=True) or {}
    remember = payload.get("remember") is True
    try:
        user, token, csrf_token = authenticate_phone(
            payload.get("phone"), payload.get("challengeId"), payload.get("code"), _client_ip(),
            request.user_agent.string, remember=remember, captcha_ticket=payload.get("captchaTicket"),
            captcha_randstr=payload.get("captchaRandstr"),
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
