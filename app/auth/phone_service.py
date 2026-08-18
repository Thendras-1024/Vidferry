"""手机号认证、人机验证和认证限流服务。"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.error
import urllib.request

from app.auth.passwords import hash_password
from app.auth.service import AuthError, _now, _parse_timestamp, _timestamp, create_session, public_user, record_audit
from app.config import (
    AUTH_PHONE_AUTO_REGISTER_ENABLED,
    AUTH_PHONE_HMAC_SECRET,
    AUTH_PHONE_LOGIN_ENABLED,
    AUTH_RATE_LIMIT_HMAC_SECRET,
    AUTH_TENCENT_CAPTCHA_APP_ID,
    AUTH_TENCENT_CAPTCHA_APP_SECRET_KEY,
    AUTH_TENCENT_REGION,
    AUTH_TENCENT_SECRET_ID,
    AUTH_TENCENT_SECRET_KEY,
    AUTH_TENCENT_SMS_APP_ID,
    AUTH_TENCENT_SMS_SIGN,
    AUTH_TENCENT_SMS_TEMPLATE_ID,
)
from app.db.base import _db_connect


_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_PASSWORD_CAPTCHA_WINDOW = dt.timedelta(minutes=15)
_PHONE_CODE_WINDOW = dt.timedelta(minutes=5)


def normalize_mainland_phone(value):
    number = re.sub(r"[\s-]", "", str(value or ""))
    if number.startswith("+86"):
        number = number[3:]
    elif number.startswith("86") and len(number) == 13:
        number = number[2:]
    if not _PHONE_PATTERN.fullmatch(number):
        raise AuthError("请输入中国大陆手机号", 400, "INVALID_PHONE")
    return number


def _hash(value, secret):
    key = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
    return hmac.new(key, str(value or "").encode("utf-8"), hashlib.sha256).hexdigest()


def _phone_hash(phone):
    if not AUTH_PHONE_HMAC_SECRET:
        raise AuthError("手机号登录未配置", 503, "PHONE_LOGIN_DISABLED")
    return _hash(phone, AUTH_PHONE_HMAC_SECRET)


def _rate_hash(value):
    return _hash(value, AUTH_RATE_LIMIT_HMAC_SECRET)


def audit_hash(value):
    return _rate_hash(value)


def _code_hash(challenge_id, code):
    return _hash(f"{challenge_id}:{code}", AUTH_PHONE_HMAC_SECRET)


def _idempotency_key_hash(phone_hash, value):
    key = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
        raise AuthError("请求标识无效，请刷新页面后重试", 400, "INVALID_IDEMPOTENCY_KEY")
    return _hash(f"{phone_hash}:{key}", AUTH_RATE_LIMIT_HMAC_SECRET)


def captcha_is_configured():
    return bool(
        AUTH_TENCENT_SECRET_ID and AUTH_TENCENT_SECRET_KEY
        and AUTH_TENCENT_CAPTCHA_APP_ID and AUTH_TENCENT_CAPTCHA_APP_SECRET_KEY
    )


def phone_login_is_configured():
    return bool(
        AUTH_PHONE_LOGIN_ENABLED and AUTH_PHONE_HMAC_SECRET and captcha_is_configured()
        and AUTH_TENCENT_SMS_APP_ID and AUTH_TENCENT_SMS_SIGN and AUTH_TENCENT_SMS_TEMPLATE_ID
    )


def _tencent_request(host, action, version, payload):
    if not AUTH_TENCENT_SECRET_ID or not AUTH_TENCENT_SECRET_KEY:
        raise AuthError("验证服务未配置", 503, "CAPTCHA_UNAVAILABLE")
    timestamp = int(time.time())
    date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join((
        "POST", "/", "", canonical_headers, signed_headers, hashlib.sha256(body).hexdigest(),
    ))
    credential_scope = f"{date}/tc3_request"
    string_to_sign = "\n".join((
        "TC3-HMAC-SHA256", str(timestamp), credential_scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ))
    secret_date = hmac.new(("TC3" + AUTH_TENCENT_SECRET_KEY).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_date, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={AUTH_TENCENT_SECRET_ID}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }
    if AUTH_TENCENT_REGION:
        headers["X-TC-Region"] = AUTH_TENCENT_REGION
    request = urllib.request.Request(f"https://{host}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise AuthError("验证服务暂不可用", 503, "CAPTCHA_UNAVAILABLE") from exc


def verify_tencent_captcha(ticket, randstr, client_ip):
    if not captcha_is_configured():
        raise AuthError("验证服务未配置", 503, "CAPTCHA_UNAVAILABLE")
    if not ticket or not randstr or len(str(ticket)) > 4096 or len(str(randstr)) > 256:
        raise AuthError("请先完成人机验证", 403, "CAPTCHA_REQUIRED")
    try:
        app_id = int(AUTH_TENCENT_CAPTCHA_APP_ID)
    except (TypeError, ValueError) as exc:
        raise AuthError("验证服务未配置", 503, "CAPTCHA_UNAVAILABLE") from exc
    payload = {
        "CaptchaType": 9,
        "Ticket": str(ticket),
        "Randstr": str(randstr),
        "UserIp": str(client_ip or "")[:128],
        "CaptchaAppId": app_id,
        "AppSecretKey": AUTH_TENCENT_CAPTCHA_APP_SECRET_KEY,
    }
    response = _tencent_request("captcha.tencentcloudapi.com", "DescribeCaptchaResult", "2019-07-22", payload)
    result = response.get("Response") or {}
    if int(result.get("CaptchaCode", -1)) != 1 or int(result.get("EvilLevel", 0) or 0) >= 100:
        raise AuthError("人机验证未通过", 403, "CAPTCHA_INVALID")
    return True


def send_tencent_sms(phone, code):
    if not phone_login_is_configured():
        raise AuthError("手机号登录未配置", 503, "PHONE_LOGIN_DISABLED")
    payload = {
        "PhoneNumberSet": [f"+86{phone}"],
        "SmsSdkAppId": AUTH_TENCENT_SMS_APP_ID,
        "Sign": AUTH_TENCENT_SMS_SIGN,
        "TemplateId": AUTH_TENCENT_SMS_TEMPLATE_ID,
        "TemplateParamSet": [code, "5"],
    }
    response = _tencent_request("sms.tencentcloudapi.com", "SendSms", "2021-01-11", payload)
    status = ((response.get("Response") or {}).get("SendStatusSet") or [{}])[0]
    if status.get("Code") != "Ok":
        raise AuthError("短信发送失败，请稍后再试", 503, "SMS_SEND_FAILED")
    return str((response.get("Response") or {}).get("RequestId") or "")


def _require_captcha(ticket, randstr, client_ip):
    return verify_tencent_captcha(ticket, randstr, client_ip)


def _rate_count(scope, key_hash, since, conn=None):
    if conn is None:
        with _db_connect(row_factory=True) as active_conn:
            return _rate_count(scope, key_hash, since, active_conn)
    return int(conn.execute(
        "SELECT COUNT(*) FROM auth_rate_limit_events WHERE scope = %s AND key_hash = %s AND created_at >= %s",
        (scope, key_hash, _timestamp(since)),
    ).fetchone()[0])


def _rate_lock_key(scope, key_hash):
    digest = hashlib.sha256(f"{scope}\x00{key_hash}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _consume_rate(scope, key_hash, limit, window):
    now = _now()

    def consume(conn):
        if _rate_count(scope, key_hash, now - window, conn) >= limit:
            raise AuthError("操作过于频繁，请稍后再试", 429, "AUTH_RATE_LIMITED")
        conn.execute(
            "INSERT INTO auth_rate_limit_events (scope, key_hash, created_at) VALUES (%s, %s, %s)",
            (scope, key_hash, _timestamp(now)),
        )

    with _db_connect(row_factory=True) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_rate_lock_key(scope, key_hash),))
        consume(conn)


def password_captcha_required(username):
    if not captcha_is_configured():
        return False
    identity_hash = _rate_hash(str(username or "").strip().lower()[:128])
    return _rate_count("password_login_failure", identity_hash, _now() - _PASSWORD_CAPTCHA_WINDOW) >= 3


def check_password_login_rate(username, client_ip):
    identity = str(username or "").strip().lower()[:128]
    now = _now()
    if _rate_count("password_login_identity_ip", _rate_hash(f"{identity}|{client_ip}"), now - _PASSWORD_CAPTCHA_WINDOW) >= 10:
        raise AuthError("登录尝试过于频繁，请稍后再试", 429, "AUTH_RATE_LIMITED")
    if _rate_count("password_login_ip", _rate_hash(client_ip), now - _PASSWORD_CAPTCHA_WINDOW) >= 30:
        raise AuthError("登录尝试过于频繁，请稍后再试", 429, "AUTH_RATE_LIMITED")


def record_password_login_failure(username, client_ip):
    identity = str(username or "").strip().lower()[:128]
    identity_hash = _rate_hash(identity)
    now = _timestamp()
    with _db_connect() as conn:
        conn.cursor().executemany(
            "INSERT INTO auth_rate_limit_events (scope, key_hash, created_at) VALUES (%s, %s, %s)",
            (
                ("password_login_failure", identity_hash, now),
                ("password_login_identity_ip", _rate_hash(f"{identity}|{client_ip}"), now),
                ("password_login_ip", _rate_hash(client_ip), now),
            ),
        )


def clear_password_login_failures(username, client_ip=""):
    identity = str(username or "").strip().lower()[:128]
    keys = [("password_login_failure", _rate_hash(identity))]
    if client_ip:
        keys.append(("password_login_identity_ip", _rate_hash(f"{identity}|{client_ip}")))
    with _db_connect() as conn:
        conn.cursor().executemany("DELETE FROM auth_rate_limit_events WHERE scope = %s AND key_hash = %s", keys)


def _active_challenge_for_idempotency(conn, idempotency_hash):
    row = conn.execute(
        "SELECT id, status, expires_at FROM auth_phone_challenges WHERE idempotency_key_hash = %s",
        (idempotency_hash,),
    ).fetchone()
    if row and row["status"] == "active" and _parse_timestamp(row["expires_at"]) > _now():
        return {"challengeId": row["id"], "expiresIn": max(1, int((_parse_timestamp(row["expires_at"]) - _now()).total_seconds()))}
    if row and row["status"] == "pending":
        raise AuthError("验证码发送处理中，请稍后重试", 409, "PHONE_CODE_PENDING")
    if row:
        raise AuthError("验证码发送失败，请重新获取", 503, "PHONE_CODE_SEND_FAILED")
    return None


def _consume_phone_code(conn, challenge_id, phone_hash, code):
    challenge_id = str(challenge_id or "")[:128]
    now = _timestamp()
    expected_hash = _code_hash(challenge_id, str(code or ""))
    cursor = conn.execute(
        """UPDATE auth_phone_challenges SET consumed_at = %s, status = 'consumed'
           WHERE id = %s AND phone_hash = %s AND status = 'active' AND consumed_at IS NULL
             AND expires_at > %s AND attempts < max_attempts AND code_hash = %s""",
        (now, challenge_id, phone_hash, now, expected_hash),
    )
    if cursor.rowcount:
        return True
    conn.execute(
        """UPDATE auth_phone_challenges SET attempts = attempts + 1
           WHERE id = %s AND phone_hash = %s AND status = 'active' AND consumed_at IS NULL
             AND expires_at > %s AND attempts < max_attempts""",
        (challenge_id, phone_hash, now),
    )
    return False


def _lock_phone_identity(conn, phone_hash):
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_rate_lock_key("phone_identity", phone_hash),))


def _create_phone_user(conn, phone_hash):
    username = f"phone-{secrets.token_urlsafe(24).lower()}"
    password_hash = hash_password(secrets.token_urlsafe(32), username)
    now = _timestamp()
    cursor = conn.execute(
        """INSERT INTO auth_users
           (username, display_name, password_hash, role, status, must_change_password,
            password_changed_at, created_at, updated_at)
           VALUES (%s, '', %s, 'user', 'active', 0, %s, %s, %s) RETURNING id""",
        (username, password_hash, now, now, now),
    )
    user_id = int(cursor.fetchone()[0])
    display_name = f"Vidferry 用户 {user_id:06d}"
    conn.execute("UPDATE auth_users SET display_name = %s WHERE id = %s", (display_name, user_id))
    conn.execute(
        """INSERT INTO auth_identities (user_id, provider, subject_hash, verified_at, created_at)
           VALUES (%s, 'phone', %s, %s, %s)""",
        (user_id, phone_hash, now, now),
    )
    return conn.execute("SELECT * FROM auth_users WHERE id = %s", (user_id,)).fetchone()


def send_phone_code(phone, captcha_ticket, captcha_randstr, client_ip, user_agent="", *, idempotency_key=""):
    if not phone_login_is_configured():
        raise AuthError("手机号登录未配置", 503, "PHONE_LOGIN_DISABLED")
    normalized_phone = normalize_mainland_phone(phone)
    phone_hash = _phone_hash(normalized_phone)
    ip_hash = _rate_hash(client_ip)
    idempotency_hash = _idempotency_key_hash(phone_hash, idempotency_key)
    _require_captcha(captcha_ticket, captcha_randstr, client_ip)
    with _db_connect(row_factory=True) as conn:
        previous = _active_challenge_for_idempotency(conn, idempotency_hash)
        if previous:
            return previous
    _consume_rate("phone_send_phone_minute", phone_hash, 1, dt.timedelta(minutes=1))
    _consume_rate("phone_send_phone_day", phone_hash, 5, dt.timedelta(days=1))
    _consume_rate("phone_send_ip_hour", ip_hash, 10, dt.timedelta(hours=1))
    _consume_rate("phone_send_ip_day", ip_hash, 30, dt.timedelta(days=1))
    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = _now()
    with _db_connect(row_factory=True) as conn:
        previous = _active_challenge_for_idempotency(conn, idempotency_hash)
        if previous:
            return previous
        conn.execute(
            """INSERT INTO auth_phone_challenges
               (id, phone_hash, code_hash, idempotency_key_hash, status, attempts, max_attempts, expires_at, created_at)
               VALUES (%s, %s, %s, %s, 'pending', 0, 5, %s, %s)""",
            (challenge_id, phone_hash, _code_hash(challenge_id, code), idempotency_hash,
             _timestamp(now + _PHONE_CODE_WINDOW), _timestamp(now)),
        )
    try:
        send_tencent_sms(normalized_phone, code)
    except AuthError:
        with _db_connect() as conn:
            conn.execute("UPDATE auth_phone_challenges SET status = 'failed', failed_at = %s WHERE id = %s", (_timestamp(), challenge_id))
            record_audit("AUTH_PHONE_CODE_SEND", "failure", target_type="phone", target_id=phone_hash,
                         details={"ipHash": ip_hash}, ip_address=ip_hash, conn=conn)
        raise
    with _db_connect() as conn:
        conn.execute(
            "UPDATE auth_phone_challenges SET status = 'expired' WHERE phone_hash = %s AND status = 'active'",
            (phone_hash,),
        )
        conn.execute(
            "UPDATE auth_phone_challenges SET status = 'active', activated_at = %s WHERE id = %s AND status = 'pending'",
            (_timestamp(), challenge_id),
        )
        record_audit("AUTH_PHONE_CODE_SEND", "success", target_type="phone", target_id=phone_hash,
                     details={"ipHash": ip_hash}, ip_address=ip_hash, conn=conn)
    return {"challengeId": challenge_id, "expiresIn": int(_PHONE_CODE_WINDOW.total_seconds())}


def authenticate_phone(phone, challenge_id, code, client_ip, user_agent="", *, remember=False, captcha_ticket="", captcha_randstr=""):
    if not phone_login_is_configured():
        raise AuthError("手机号登录未配置", 503, "PHONE_LOGIN_DISABLED")
    normalized_phone = normalize_mainland_phone(phone)
    phone_hash = _phone_hash(normalized_phone)
    ip_hash = _rate_hash(client_ip)
    failure = None
    result = None

    def authenticate_in_transaction(conn):
        nonlocal failure, result
        _lock_phone_identity(conn, phone_hash)
        if not _consume_phone_code(conn, challenge_id, phone_hash, code):
            failure = AuthError("验证码无效或已过期", 400, "PHONE_CODE_INVALID")
            return
        identity = conn.execute(
            "SELECT user_id FROM auth_identities WHERE provider = 'phone' AND subject_hash = %s", (phone_hash,)
        ).fetchone()
        is_new_user = identity is None
        if is_new_user and not AUTH_PHONE_AUTO_REGISTER_ENABLED:
            record_audit("AUTH_PHONE_LOGIN", "failure", target_type="phone", target_id=phone_hash,
                         details={"ipHash": ip_hash}, ip_address=ip_hash, user_agent=user_agent, conn=conn)
            failure = AuthError("手机号未绑定账号", 403, "PHONE_NOT_LINKED")
            return
        user_row = _create_phone_user(conn, phone_hash) if is_new_user else conn.execute(
            "SELECT * FROM auth_users WHERE id = %s", (int(identity["user_id"]),)
        ).fetchone()
        if not user_row or user_row["status"] != "active":
            record_audit("AUTH_PHONE_LOGIN", "failure", target_type="phone", target_id=phone_hash,
                         details={"ipHash": ip_hash}, ip_address=ip_hash, user_agent=user_agent, conn=conn)
            failure = AuthError("登录不可用，请联系管理员", 403, "PHONE_LOGIN_UNAVAILABLE")
            return
        token, csrf_token = create_session(user_row["id"], client_ip, user_agent, remember=remember, conn=conn)
        record_audit("AUTH_PHONE_REGISTER" if is_new_user else "AUTH_PHONE_LOGIN", "success",
                     actor_user_id=user_row["id"], target_type="phone", target_id=phone_hash,
                     details={"ipHash": ip_hash}, ip_address=ip_hash, user_agent=user_agent, conn=conn)
        result = (public_user(user_row), token, csrf_token, is_new_user)

    with _db_connect(row_factory=True) as conn:
        authenticate_in_transaction(conn)
    if failure:
        raise failure
    return result
