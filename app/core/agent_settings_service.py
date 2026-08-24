"""用户级 Agent 设置。"""

import json


AGENT_SOUL_KEY_PREFIX = "agent_soul:"
AGENT_SOUL_MAX_BYTES = 128 * 1024


def _agent_soul_key(owner_user_id):
    owner_user_id = int(owner_user_id)
    if owner_user_id <= 0:
        raise ValueError("Agent 设置归属账号必须是正整数")
    return f"{AGENT_SOUL_KEY_PREFIX}{owner_user_id}"


def get_agent_soul(owner_user_id):
    key = _agent_soul_key(owner_user_id)
    init_database_tables()
    with _db_connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    if not row:
        return ""
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        value = row[0]
    return str(value or "")


def update_agent_soul(owner_user_id, content):
    key = _agent_soul_key(owner_user_id)
    content = str(content if content is not None else "")
    if len(content.encode("utf-8")) > AGENT_SOUL_MAX_BYTES:
        raise ValueError("Agent Soul 不能超过 128 KB")
    init_database_tables()
    with _db_connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, json.dumps(content, ensure_ascii=False)),
        )
        conn.commit()
    return content
