"""为本地 PostgreSQL 部署补齐必需的非公开配置。"""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def _read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _set_env_value(lines, key, value):
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"{key}={value}"
            return
    lines.append(f"{key}={value}")


def _database_url(user, password, database):
    return "postgresql://{}:{}@127.0.0.1:5432/{}".format(
        quote(user, safe=""), quote(password, safe=""), quote(database, safe=""),
    )


def main():
    if not ENV_PATH.exists():
        ENV_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    values = _read_env(ENV_PATH)
    database = values.get("POSTGRES_DB") or "vidferry"
    user = values.get("POSTGRES_USER") or "vidferry"
    password = values.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(32)
    updates = {
        "POSTGRES_DB": database,
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "DATABASE_URL": values.get("DATABASE_URL") or _database_url(user, password, database),
        "VIDFERRY_AUTH_SECRET": values.get("VIDFERRY_AUTH_SECRET") or secrets.token_urlsafe(64),
    }
    for key, value in updates.items():
        _set_env_value(lines, key, value)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("prepared local .env: " + ", ".join(updates))


if __name__ == "__main__":
    main()
