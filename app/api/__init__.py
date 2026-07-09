"""按业务域分组的 HTTP API 路由模块。

这些路由在模块化过渡期间由 ``app.backend.runtime`` 加载,使旧版装饰器保持
原有行为,同时每个业务域各自落在独立文件中。
"""


def register_blueprints(app):
    """预留给未来 Flask 蓝图注册的集成点。"""
    return app
