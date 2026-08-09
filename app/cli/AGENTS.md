# CLI 模块约束

- `sau_cli.py` 只负责兼容转发，参数解析和平台动作分别放入 `app/cli`。
- 平台账号使用用户定义的账号名和 `cookiesFile` 下的相对文件名。
- CLI 输出可操作的状态和错误，但不得打印 Cookie、密码、Token 或完整连接字符串。
