"""管理员用户管理服务。"""

from __future__ import annotations

from app.auth.passwords import hash_password
from app.auth.service import AuthError, _timestamp, create_user, public_user, revoke_user_sessions
from app.db.base import _db_connect


def list_users(page=1, page_size=50, keyword=""):
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 50)))
    keyword = str(keyword or "").strip().lower()
    where = "WHERE lower(username) ILIKE %s OR lower(display_name) ILIKE %s" if keyword else ""
    params = (f"%{keyword}%", f"%{keyword}%") if keyword else ()
    with _db_connect(row_factory=True) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM auth_users {where}", params).fetchone()[0])
        rows = conn.execute(
            f"""SELECT u.*, COALESCE((
                    SELECT string_agg(i.provider, ',' ORDER BY i.provider)
                    FROM auth_identities i WHERE i.user_id = u.id
                ), 'password') AS login_provider
                FROM auth_users u {where.replace('username', 'u.username').replace('display_name', 'u.display_name')}
                ORDER BY u.created_at DESC, u.id DESC LIMIT %s OFFSET %s""",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
    items = []
    for row in rows:
        user = public_user(row)
        user["loginProvider"] = row["login_provider"] or "password"
        items.append(user)
    return {"items": items, "total": total, "page": page, "pageSize": page_size}


def _active_admin_count(conn):
    return int(conn.execute("SELECT COUNT(*) FROM auth_users WHERE role = 'admin' AND status = 'active'").fetchone()[0])


def update_user(user_id, payload, actor_user_id):
    user_id = int(user_id)
    display_name = payload.get("displayName")
    role = payload.get("role")
    status = payload.get("status")
    if role is not None and role not in {"admin", "user"}:
        raise AuthError("角色无效")
    if status is not None and status not in {"active", "disabled"}:
        raise AuthError("用户状态无效")
    with _db_connect(row_factory=True) as conn:
        row = conn.execute("SELECT * FROM auth_users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise AuthError("用户不存在", 404, "USER_NOT_FOUND")
        current = public_user(row)
        next_role = role or current["role"]
        next_status = status or current["status"]
        removes_admin = current["role"] == "admin" and current["status"] == "active" and (next_role != "admin" or next_status != "active")
        if removes_admin and _active_admin_count(conn) <= 1:
            raise AuthError("不能停用或降级最后一个有效管理员", 409, "LAST_ADMIN")
        if user_id == int(actor_user_id) and next_status != "active":
            raise AuthError("不能停用当前登录用户", 409, "CURRENT_USER")
        conn.execute(
            "UPDATE auth_users SET display_name = %s, role = %s, status = %s, updated_at = %s WHERE id = %s",
            (str(display_name or current["displayName"]).strip()[:80], next_role, next_status, _timestamp(), user_id),
        )
        updated = conn.execute("SELECT * FROM auth_users WHERE id = %s", (user_id,)).fetchone()
    if next_status != "active" or next_role != current["role"]:
        revoke_user_sessions(user_id)
    return public_user(updated)


def reset_password(user_id, password):
    user_id = int(user_id)
    with _db_connect(row_factory=True) as conn:
        row = conn.execute("SELECT username FROM auth_users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise AuthError("用户不存在", 404, "USER_NOT_FOUND")
        now = _timestamp()
        conn.execute(
            """UPDATE auth_users SET password_hash = %s, must_change_password = 1,
               failed_login_count = 0, locked_until = NULL, password_changed_at = %s, updated_at = %s WHERE id = %s""",
            (hash_password(password, row["username"]), now, now, user_id),
        )
    revoke_user_sessions(user_id)


def unlock_user(user_id):
    with _db_connect() as conn:
        cursor = conn.execute(
            "UPDATE auth_users SET failed_login_count = 0, locked_until = NULL, updated_at = %s WHERE id = %s",
            (_timestamp(), int(user_id)),
        )
        if not cursor.rowcount:
            raise AuthError("用户不存在", 404, "USER_NOT_FOUND")


def list_audit_logs(page=1, page_size=50, action=""):
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 50)))
    action = str(action or "").strip()
    where, params = ("WHERE a.action = %s", (action,)) if action else ("", ())
    with _db_connect(row_factory=True) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM auth_audit_logs a {where}", params).fetchone()[0])
        rows = conn.execute(
            f"""SELECT a.*, u.username AS actor_username FROM auth_audit_logs a
                LEFT JOIN auth_users u ON u.id = a.actor_user_id {where}
                ORDER BY a.created_at DESC, a.id DESC LIMIT %s OFFSET %s""",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
    items = [{
        "id": int(row["id"]), "actorUsername": row["actor_username"] or "", "action": row["action"],
        "targetType": row["target_type"] or "", "targetId": row["target_id"] or "",
        "result": row["result"], "ipAddress": row["ip_address"] or "",
        "details": row["details"] or "{}", "createdAt": str(row["created_at"] or ""),
    } for row in rows]
    return {"items": items, "total": total, "page": page, "pageSize": page_size}
