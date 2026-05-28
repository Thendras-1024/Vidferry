"""Formal backend entrypoint."""

from __future__ import annotations
import logging

from app import create_app, initialize_runtime
from app.config import HOST, PORT

# 关闭 Flask 默认的访问日志
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # 只显示错误，不显示 GET/POST 请求

app = create_app()



if __name__ == "__main__":
    initialize_runtime()
    app.run(host=HOST, port=PORT)
