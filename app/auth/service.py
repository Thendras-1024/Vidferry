"""用户、会话和审计服务。"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets

from app.auth.passwords import hash_password, validate_password, verify_password
from app.config import (
    AUTH_ABSOLUTE_TIMEOUT_HOURS,
    AUTH_CSRF_SECRET,
    AUTH_IDLE_TIMEOUT_MINUTES,
    AUTH_LOCK_MINUTES,
    AUTH_MAX_LOGIN_FAILURES,
    AUTH_REMEMBER_TIMEOUT_HOURS,
)
from app.db.base import DATABASE_INTEGRITY_ERRORS, _db_connect


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))


class AuthError(Exception):
    def __init__(self, message, status=400, code="AUTH_ERROR"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _timestamp(value=None):
    return (value or _now()).isoformat(timespec="seconds")


def _parse_timestamp(value):
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=value.tzinfo or dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc)
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _row_dict(row):
    return {key: row[key] for key in row.keys()} if row else None


def normalize_username(username):
    value = str(username or "").strip().lower()
    if not _USERNAME_PATTERN.fullmatch(value):
        raise AuthError("用户名须为 3 到 64 位字母、数字、点、下划线或连字符")
    return value


def public_user(row):
    item = _row_dict(row) if not isinstance(row, dict) else row
    if not item:
        return None
    return {
        "id": int(item["id"]),
        "username": item["username"],
        "displayName": item["display_name"],
        "role": item["role"],
        "status": item["status"],
        "mustChangePassword": bool(item["must_change_password"]),
        "lockedUntil": str(item.get("locked_until") or ""),
        "lastLoginAt": str(item.get("last_login_at") or ""),
        "createdAt": str(item.get("created_at") or ""),
        "updatedAt": str(item.get("updated_at") or ""),
    }


def record_audit(action, result, *, actor_user_id=None, target_type="", target_id="", details=None, ip_address="", user_agent=""):
    safe_details = json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))
    with _db_connect() as conn:
        conn.execute(
            """INSERT INTO auth_audit_logs
               (actor_user_id, action, target_type, target_id, result, ip_address, user_agent, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (actor_user_id, action, target_type, str(target_id or ""), result,
             str(ip_address or "")[:128], str(user_agent or "")[:512], safe_details[:4000], _timestamp()),
        )


def count_users():
    with _db_connect(row_factory=True) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])


def create_user(username, display_name, password, role="user", *, created_by=None, must_change_password=True):
    username = normalize_username(username)
    role = str(role or "user").strip().lower()
    if role not in {"admin", "user"}:
        raise AuthError("角色无效")
    display_name = str(display_name or username).strip()[:80]
    password_hash = hash_password(password, username)
    now = _timestamp()
    try:
        with _db_connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO auth_users
                   (username, display_name, password_hash, role, status, must_change_password,
                    password_changed_at, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (username, display_name, password_hash, role, int(bool(must_change_password)),
                 now, created_by, now, now),
            )
            user_id = cursor.lastrowid
            row = cursor.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
    except DATABASE_INTEGRITY_ERRORS as exc:
        raise AuthError("用户名已存在", 409, "USERNAME_EXISTS") from exc
    return public_user(row)


def get_user(user_id):
    with _db_connect(row_factory=True) as conn:
        return public_user(conn.execute("SELECT * FROM auth_users WHERE id = ?", (int(user_id),)).fetchone())


def authenticate(username, password, ip_address="", user_agent="", *, remember=False):
    try:
        username = normalize_username(username)
    except AuthError:
        username = str(username or "").strip().lower()[:64]
    failed = False
    item = None
    with _db_connect(row_factory=True) as conn:
        row = conn.execute("SELECT * FROM auth_users WHERE username = ?", (username,)).fetchone()
        item = _row_dict(row)
        now = _now()
        locked = item and _parse_timestamp(item.get("locked_until")) > now
        valid, rehash = verify_password(item.get("password_hash") if item else _DUMMY_PASSWORD_HASH, password)
        if not item or item["status"] != "active" or locked or not valid:
            if item and not locked:
                failures = int(item.get("failed_login_count") or 0) + 1
                locked_until = _timestamp(now + dt.timedelta(minutes=AUTH_LOCK_MINUTES)) if failures >= AUTH_MAX_LOGIN_FAILURES else None
                conn.execute(
                    "UPDATE auth_users SET failed_login_count = ?, locked_until = ?, updated_at = ? WHERE id = ?",
                    (failures, locked_until, _timestamp(now), item["id"]),
                )
            failed = True
        else:
            new_hash = hash_password(password, username) if rehash else item["password_hash"]
            conn.execute(
                """UPDATE auth_users SET password_hash = ?, failed_login_count = 0, locked_until = NULL,
                   last_login_at = ?, updated_at = ? WHERE id = ?""",
                (new_hash, _timestamp(now), _timestamp(now), item["id"]),
            )
    if failed:
        record_audit("AUTH_LOGIN", "failure", target_type="user", target_id=username,
                     ip_address=ip_address, user_agent=user_agent)
        raise AuthError("用户名或密码错误", 401, "INVALID_CREDENTIALS")
    token, csrf_token = create_session(item["id"], ip_address, user_agent, remember=remember)
    record_audit("AUTH_LOGIN", "success", actor_user_id=item["id"], target_type="user",
                 target_id=item["id"], ip_address=ip_address, user_agent=user_agent)
    return get_user(item["id"]), token, csrf_token


def _token_hash(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def csrf_token_for(token):
    return hmac.new(AUTH_CSRF_SECRET.encode("utf-8"), str(token or "").encode("utf-8"), hashlib.sha256).hexdigest()


def create_session(user_id, ip_address="", user_agent="", *, remember=False):
    token = secrets.token_urlsafe(32)
    now = _now()
    if remember:
        idle_expiry = absolute_expiry = now + dt.timedelta(hours=AUTH_REMEMBER_TIMEOUT_HOURS)
    else:
        idle_expiry = now + dt.timedelta(minutes=AUTH_IDLE_TIMEOUT_MINUTES)
        absolute_expiry = now + dt.timedelta(hours=AUTH_ABSOLUTE_TIMEOUT_HOURS)
    with _db_connect() as conn:
        conn.execute(
            """INSERT INTO auth_sessions
               (token_hash, user_id, created_at, last_seen_at, idle_expires_at, absolute_expires_at,
                ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_token_hash(token), user_id, _timestamp(now), _timestamp(now), _timestamp(idle_expiry),
             _timestamp(absolute_expiry), str(ip_address or "")[:128], str(user_agent or "")[:512]),
        )
    return token, csrf_token_for(token)


def resolve_session(token):
    if not token:
        return None
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            """SELECT s.*, u.username, u.display_name, u.role, u.status, u.must_change_password,
                      u.locked_until, u.last_login_at, u.created_at AS user_created_at,
                      u.updated_at AS user_updated_at
               FROM auth_sessions s JOIN auth_users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.revoked_at IS NULL""",
            (_token_hash(token),),
        ).fetchone()
        item = _row_dict(row)
        now = _now()
        if not item or item["status"] != "active" or _parse_timestamp(item["idle_expires_at"]) <= now or _parse_timestamp(item["absolute_expires_at"]) <= now:
            return None
        last_seen = _parse_timestamp(item["last_seen_at"])
        if now - last_seen >= dt.timedelta(minutes=5):
            absolute_expiry = _parse_timestamp(item["absolute_expires_at"])
            remembered = _parse_timestamp(item["idle_expires_at"]) == absolute_expiry
            idle_expiry = absolute_expiry if remembered else min(
                now + dt.timedelta(minutes=AUTH_IDLE_TIMEOUT_MINUTES),
                absolute_expiry,
            )
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at = ?, idle_expires_at = ? WHERE token_hash = ?",
                (_timestamp(now), _timestamp(idle_expiry), item["token_hash"]),
            )
        user = {
            "id": item["user_id"], "username": item["username"], "display_name": item["display_name"],
            "role": item["role"], "status": item["status"], "must_change_password": item["must_change_password"],
            "locked_until": item["locked_until"], "last_login_at": item["last_login_at"],
            "created_at": item["user_created_at"], "updated_at": item["user_updated_at"],
        }
        return {"user": public_user(user), "tokenHash": item["token_hash"]}


def revoke_session(token):
    if not token:
        return
    with _db_connect() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (_timestamp(), _token_hash(token)))


def revoke_user_sessions(user_id):
    with _db_connect() as conn:
        cursor = conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (_timestamp(), int(user_id)))
        return max(0, int(cursor.rowcount or 0))


def change_password(user_id, current_password, new_password):
    with _db_connect(row_factory=True) as conn:
        row = conn.execute("SELECT * FROM auth_users WHERE id = ?", (int(user_id),)).fetchone()
        item = _row_dict(row)
        valid, _ = verify_password(item.get("password_hash") if item else "", current_password)
        if not valid:
            raise AuthError("当前密码错误", 400, "INVALID_CURRENT_PASSWORD")
        validate_password(new_password, item["username"])
        if verify_password(item["password_hash"], new_password)[0]:
            raise AuthError("新密码不能与当前密码相同")
        now = _timestamp()
        conn.execute(
            "UPDATE auth_users SET password_hash = ?, must_change_password = 0, password_changed_at = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password, item["username"]), now, now, item["id"]),
        )
    revoke_user_sessions(user_id)
