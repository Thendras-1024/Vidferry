"""Production launcher: one Waitress process behind an HTTPS reverse proxy."""

from __future__ import annotations

import os
import ipaddress
from pathlib import Path

from app import create_app, initialize_runtime
from app.config import (
    AUTH_ALLOW_COOKIE_EXPORT, AUTH_COOKIE_SECURE, AUTH_CSRF_SECRET,
    AUTH_TRUSTED_PROXY_CIDRS, CORS_ORIGINS, PORT,
)


def _validate_production_config():
    frontend_index = Path(__file__).resolve().parent / "sau_frontend" / "dist" / "index.html"
    if not frontend_index.is_file():
        raise RuntimeError("生产环境缺少前端构建产物 sau_frontend/dist/index.html，请先执行 sau_frontend 的 npm run build")
    if not AUTH_COOKIE_SECURE:
        raise RuntimeError("生产环境必须启用 VIDFERRY_AUTH_COOKIE_SECURE=true")
    if not os.environ.get("VIDFERRY_AUTH_SECRET"):
        raise RuntimeError("生产环境必须显式设置 VIDFERRY_AUTH_SECRET")
    if len(AUTH_CSRF_SECRET) < 32:
        raise RuntimeError("VIDFERRY_AUTH_SECRET 长度不足")
    if not CORS_ORIGINS or any("*" in origin for origin in CORS_ORIGINS):
        raise RuntimeError("生产环境必须配置精确 VIDFERRY_CORS_ORIGINS")
    if any(not origin.lower().startswith("https://") for origin in CORS_ORIGINS):
        raise RuntimeError("生产环境 VIDFERRY_CORS_ORIGINS 必须全部使用 HTTPS")
    if not AUTH_TRUSTED_PROXY_CIDRS:
        raise RuntimeError("生产环境必须配置 VIDFERRY_AUTH_TRUSTED_PROXY_CIDRS")
    try:
        for cidr in AUTH_TRUSTED_PROXY_CIDRS:
            ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise RuntimeError("VIDFERRY_AUTH_TRUSTED_PROXY_CIDRS 包含无效网段") from exc
    if AUTH_ALLOW_COOKIE_EXPORT:
        raise RuntimeError("生产环境必须保持 Cookie 导出关闭")


def main():
    from waitress import serve

    _validate_production_config()
    app = create_app()
    initialize_runtime()
    listen_host = "127.0.0.1"
    listen_port = int(os.environ.get("VIDFERRY_PRODUCTION_PORT", PORT))
    serve(app, host=listen_host, port=listen_port, threads=8, asyncore_use_poll=True)


if __name__ == "__main__":
    main()
