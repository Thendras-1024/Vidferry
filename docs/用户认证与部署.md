# 用户认证与部署

Vidferry 默认强制用户认证，不开放自助注册。系统只有 `admin` 和 `user` 两种固定角色。

## 初始化管理员

安装项目依赖并确保数据库配置正确后执行：

```powershell
python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

命令交互式读取并确认密码。密码至少 12 个字符、最多 128 个字符，且不能包含用户名。系统已有用户时，命令会拒绝继续；后续用户必须由管理员在“用户与安全”页面创建。

## 生产环境配置

在 `.env` 或部署平台的安全环境变量中配置：

```dotenv
VIDFERRY_AUTH_SECRET=<至少 48 字节的随机值>
VIDFERRY_AUTH_COOKIE_SECURE=true
VIDFERRY_AUTH_IDLE_MINUTES=480
VIDFERRY_AUTH_ABSOLUTE_HOURS=24
VIDFERRY_AUTH_MAX_FAILURES=5
VIDFERRY_AUTH_LOCK_MINUTES=15
VIDFERRY_AUTH_ALLOW_COOKIE_EXPORT=false
```

可用以下命令生成认证密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

不要提交 `.env`，不要把认证密钥、用户密码、会话 Cookie 或平台 Cookie 写入日志。

## 网络边界

- 使用 Caddy 或 Nginx 提供 HTTPS，并让前端和 API 使用同一域名。
- 后端只监听 `127.0.0.1`，不要直接暴露 5409 端口。
- 开启 `VIDFERRY_AUTH_COOKIE_SECURE=true` 后，浏览器只会通过 HTTPS 发送 `__Host-vidferry_session` Cookie。
- 根据实际域名设置 `VIDFERRY_CORS_ORIGINS`，不要使用通配符。
- 当前调度器、SSE 和任务执行包含进程内状态，部署时保持单个后端进程。

## 权限说明

普通用户可以检索、处理、管理素材和创建发布任务，但不能管理发布平台账号、Cookie、全局工作流设置或应用用户。管理员可以执行上述管理操作。

平台 Cookie 导出默认对所有角色关闭。确需临时导出时设置 `VIDFERRY_AUTH_ALLOW_COOKIE_EXPORT=true`，完成后立即恢复为 `false` 并检查审计日志。

Agent 历史会话按应用用户隔离。素材、发布任务和平台账号属于当前单组织共享工作区，敏感写操作会记录操作者和结果。

## 会话与应急处理

- 管理员停用用户、重置密码或修改角色后，该用户的现有会话立即失效。
- 用户修改自己的密码后需要重新登录。
- 不能停用或降级最后一个有效管理员。
- 管理员可在“用户与安全”中解锁用户、撤销全部会话并查看审计日志。
- 备份必须同时覆盖数据库、`cookiesFile/` 和本地素材目录，并限制备份文件读取权限。
