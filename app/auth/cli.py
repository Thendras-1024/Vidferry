"""认证管理员初始化命令。"""

from __future__ import annotations

import argparse
import getpass


def _create_admin(args):
    import sau_backend as backend
    from app.auth.service import AuthError, count_users, create_user

    backend.init_database_tables()
    if count_users():
        raise RuntimeError("系统已存在用户；如需新增管理员，请登录后台操作")
    password = getpass.getpass("管理员密码: ")
    confirm = getpass.getpass("再次输入密码: ")
    if password != confirm:
        raise RuntimeError("两次输入的密码不一致")
    try:
        user = create_user(
            args.username, args.display_name or args.username, password, "admin",
            must_change_password=False,
        )
    except (AuthError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    with backend._db_connect() as conn:
        conn.execute("UPDATE agent_sessions SET owner_user_id = %s WHERE owner_user_id IS NULL", (user["id"],))
    print(f"admin created : username = {user['username']}")


def main():
    parser = argparse.ArgumentParser(description="Vidferry 认证管理")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create-admin", help="交互式创建首个管理员")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--display-name", default="")
    args = parser.parse_args()
    if args.command == "create-admin":
        _create_admin(args)


if __name__ == "__main__":
    main()
