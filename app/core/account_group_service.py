"""Per-user multi-platform publish account groups."""

from flask import g


def _account_group_owner_id():
    user = getattr(g, "current_user", None)
    if not user or not user.get("id"):
        raise PermissionError("登录用户不能为空")
    return int(user["id"])


def _account_group_platforms():
    return (1, 2, 3, 4, 5)


def _account_group_entries(entries):
    if not isinstance(entries, list):
        raise ValueError("accounts must be a list")
    normalized = []
    seen_platforms = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("account group member format is invalid")
        try:
            account_id = int(entry.get("accountId") or entry.get("id") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("accountId must be an integer") from exc
        if account_id <= 0:
            raise ValueError("accountId is required")
        platform_type = int(entry.get("platformType") or entry.get("type") or 0)
        if platform_type in seen_platforms:
            raise ValueError("an account group can contain only one account per platform")
        if platform_type not in _account_group_platforms():
            raise ValueError("platformType is invalid")
        seen_platforms.add(platform_type)
        normalized.append({"accountId": account_id, "platformType": platform_type})
    return normalized


def _account_group_row(cursor, group_id, owner_user_id):
    cursor.execute("SELECT id, name, created_at, updated_at FROM publish_account_groups WHERE id = ? AND owner_user_id = ?", (group_id, owner_user_id))
    return cursor.fetchone()


def _account_group_payload(cursor, row):
    if not row:
        return None
    group_id = int(row["id"])
    cursor.execute(
        """
        SELECT m.platform_type, m.account_id, a.type, a.filePath, a.userName, a.status
        FROM publish_account_group_members m
        LEFT JOIN user_info a ON a.id = m.account_id
        WHERE m.group_id = ? ORDER BY m.platform_type
        """,
        (group_id,),
    )
    accounts = []
    incomplete = []
    for member in cursor.fetchall():
        account_id = member["account_id"]
        valid = bool(member["userName"]) and int(member["status"] or 0) == 1 and int(member["type"] or 0) == int(member["platform_type"])
        item = {
            "accountId": account_id,
            "platformType": int(member["platform_type"]),
            "platform": platform_name(member["platform_type"]),
            "name": member["userName"] or "",
            "filePath": member["filePath"] or "",
            "status": int(member["status"] or 0) if member["status"] is not None else 0,
            "valid": valid,
        }
        accounts.append(item)
        if not valid:
            incomplete.append(item["platform"])
    return {
        "id": group_id,
        "name": row["name"],
        "accounts": accounts,
        "complete": not incomplete,
        "invalidPlatforms": incomplete,
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
    }


def list_publish_account_groups():
    init_database_tables()
    owner_user_id = _account_group_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, created_at, updated_at FROM publish_account_groups WHERE owner_user_id = ? ORDER BY LOWER(name), id", (owner_user_id,))
        return [_account_group_payload(cursor, row) for row in cursor.fetchall()]


def _validate_account_group_entries(cursor, entries, owner_user_id):
    normalized = _account_group_entries(entries)
    accounts = []
    for entry in normalized:
        cursor.execute("SELECT id, type, filePath, userName, status FROM user_info WHERE id = ? AND owner_user_id = ?", (entry["accountId"], owner_user_id))
        account = cursor.fetchone()
        if not account:
            raise ValueError(f"account {entry['accountId']} does not exist")
        if int(account["type"] or 0) != entry["platformType"]:
            raise ValueError(f"account {entry['accountId']} does not belong to the selected platform")
        accounts.append(entry)
    return accounts


def create_publish_account_group(name, entries):
    group_name = str(name or "").strip()
    if not group_name:
        raise ValueError("account group name is required")
    init_database_tables()
    owner_user_id = _account_group_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM publish_account_groups WHERE owner_user_id = ? AND LOWER(name) = LOWER(?)", (owner_user_id, group_name))
        if cursor.fetchone():
            raise WorkflowConflictError("account group name already exists", "VF-ACCOUNT-GROUP-DUPLICATE", "ACCOUNT_GROUP_DUPLICATE", {"name": group_name})
        members = _validate_account_group_entries(cursor, entries, owner_user_id)
        now = _now_iso()
        try:
            cursor.execute("INSERT INTO publish_account_groups (name, owner_user_id, created_at, updated_at) VALUES (?, ?, ?, ?) RETURNING id", (group_name, owner_user_id, now, now))
        except DATABASE_INTEGRITY_ERRORS as exc:
            raise WorkflowConflictError("account group name already exists", "VF-ACCOUNT-GROUP-DUPLICATE", "ACCOUNT_GROUP_DUPLICATE", {"name": group_name}) from exc
        group_id = cursor.fetchone()[0]
        for member in members:
            cursor.execute("INSERT INTO publish_account_group_members (group_id, account_id, platform_type) VALUES (?, ?, ?)", (group_id, member["accountId"], member["platformType"]))
        return _account_group_payload(cursor, _account_group_row(cursor, group_id, owner_user_id))


def update_publish_account_group(group_id, name, entries):
    try:
        group_id = int(group_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("group id is invalid") from exc
    group_name = str(name or "").strip()
    if not group_name:
        raise ValueError("account group name is required")
    init_database_tables()
    owner_user_id = _account_group_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        if not _account_group_row(cursor, group_id, owner_user_id):
            raise LookupError("account group does not exist")
        cursor.execute("SELECT id FROM publish_account_groups WHERE owner_user_id = ? AND LOWER(name) = LOWER(?) AND id != ?", (owner_user_id, group_name, group_id))
        if cursor.fetchone():
            raise WorkflowConflictError("account group name already exists", "VF-ACCOUNT-GROUP-DUPLICATE", "ACCOUNT_GROUP_DUPLICATE", {"name": group_name})
        members = _validate_account_group_entries(cursor, entries, owner_user_id)
        now = _now_iso()
        cursor.execute("UPDATE publish_account_groups SET name = ?, updated_at = ? WHERE id = ?", (group_name, now, group_id))
        cursor.execute("DELETE FROM publish_account_group_members WHERE group_id = ?", (group_id,))
        for member in members:
            cursor.execute("INSERT INTO publish_account_group_members (group_id, account_id, platform_type) VALUES (?, ?, ?)", (group_id, member["accountId"], member["platformType"]))
        return _account_group_payload(cursor, _account_group_row(cursor, group_id, owner_user_id))


def delete_publish_account_group(group_id):
    try:
        group_id = int(group_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("group id is invalid") from exc
    init_database_tables()
    owner_user_id = _account_group_owner_id()
    with _db_connect() as conn:
        cursor = conn.cursor()
        if not _account_group_row(cursor, group_id, owner_user_id):
            raise LookupError("account group does not exist")
        cursor.execute("DELETE FROM publish_account_group_members WHERE group_id = ?", (group_id,))
        cursor.execute("DELETE FROM publish_account_groups WHERE id = ?", (group_id,))
    return {"id": group_id, "deleted": True}


def resolve_publish_account_group(group_id):
    if group_id in (None, "", 0, "0"):
        return None
    init_database_tables()
    owner_user_id = _account_group_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        row = _account_group_row(cursor, group_id, owner_user_id)
        group = _account_group_payload(cursor, row)
        if not group:
            raise LookupError("account group does not exist")
        if not group["complete"]:
            raise WorkflowConflictError("account group is incomplete: " + ", ".join(group["invalidPlatforms"]), "VF-ACCOUNT-GROUP-INCOMPLETE", "ACCOUNT_GROUP_INCOMPLETE", {"groupId": group["id"], "invalidPlatforms": group["invalidPlatforms"]})
        return group
