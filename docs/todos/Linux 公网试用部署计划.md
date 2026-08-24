# Linux 公网试用部署计划

> 状态：规划中，尚未实施。当前开发环境继续使用 Windows 本机；本文不改变现有代码、Dockerfile、`.env.example` 或手机号短信实现。

## 1. 目标与边界

- 正式试用环境目标为腾讯云中国香港 Linux VPS，面向少量受信任朋友开放 Vidferry 完整工作流。
- 首期使用邀请码和密码注册；手机号短信能力保留在代码中但保持关闭，管理员手工创建账号作为兜底。
- 每位用户仅使用自己的平台账号，平台 Cookie、素材、任务和发布记录必须按用户隔离。
- 当前项目定位仍是本机或受控环境工具。公网开放前必须完成本文的隔离、浏览器兼容性和资源限制验收；未通过的发布平台不得开放。

## 2. 目标架构

```text
Internet
  -> Caddy : 80 / 443
  -> Vidferry backend : 127.0.0.1:5409
  -> PostgreSQL : private loopback or container network only
```

- 使用个人实名域名和单一 HTTPS 域名；域名注册默认可购买一年，香港等境外地域的服务器不要求 ICP 备案。
- 反向代理只开放 `80` 和 `443`；后端端口、PostgreSQL、浏览器调试端口和任何远程桌面端口不得暴露公网。
- 管理 SSH 使用密钥认证并限制来源 IP；应用、数据库、素材和 Cookie 使用独立持久化目录与最小权限账户。
- HTTPS 环境启用 `VIDFERRY_AUTH_COOKIE_SECURE=true`，设置精确 `VIDFERRY_CORS_ORIGINS`，并仅在受控反向代理来源读取转发 IP。

## 3. 资源与数据边界

- 首期基线为 `8 vCPU / 16 GB RAM / 500 GB` 磁盘；不配置 GPU，先以 CPU 验证转写和 FFmpeg 流程。
- 下载、处理任务最多两路并发；发布、分析和队列上限应按实际负载配置，避免单个用户耗尽 CPU、磁盘或模型额度。
- 上线前为每个用户落实上传大小、总存储、任务排队数和并发数限制；磁盘达到告警阈值时停止接收新任务。
- PostgreSQL、`cookiesFile/`、素材和部署 `.env` 每日进行加密备份到独立存储，并定期执行恢复演练。Cookie、密钥、密码、会话和邀请码明文不得进入 Git、日志或备份目录名。

## 4. Linux 兼容性门槛

现有 Dockerfile 可作为 Linux 构建起点，但不等同于所有功能已验证。正式镜像需补齐并验证系统 Chrome、Chromium、Firefox、FFmpeg 及 Playwright 浏览器依赖。

以下项目必须逐平台在目标 Linux 主机完成真实烟测后才可开放：

1. 扫码登录或其他交互式登录能在网页流程中完成，且不会泄露 Cookie。
2. Cookie 续期能正确写入所属用户目录。
3. 使用测试素材完成一次发布，并确认失败信息、任务记录和用户边界正确。
4. YouTube 下载、转写、字幕烧制和两路并发处理在磁盘与超时限制内完成。

无法通过 Linux 烟测的平台先在界面和服务端禁用，不以 Windows 本机结果替代 Linux 结果。

## 5. 注册与认证路线

- 首期新增邀请码注册：管理员创建一次性、高熵邀请码，邀请码只保存哈希，默认 7 天过期，兑换后立即失效。
- 邀请码兑换仅创建 `user` 角色账号，要求首次登录修改密码；管理员仍可在“用户与安全”中手工创建、停用、解锁和撤销会话。
- 接入 Cloudflare Turnstile 保护邀请码兑换和密码失败后的挑战；前端 token 必须由后端调用 Siteverify 校验，并验证 hostname、时效和单次使用。验证服务异常时拒绝自助注册，改由管理员手工开通。
- 继续保持 `VIDFERRY_AUTH_PHONE_LOGIN_ENABLED=false`。未来启用手机号注册前，另行完成 Spug 或腾讯云短信供应商、限流、费用告警和真实投递测试。

## 6. 上线验收与回滚

- 使用至少两个普通用户账号验证：用户 A 不能读取、删除、发布、续期或下载用户 B 的素材、任务、Cookie、账号和发布记录。
- 验证邀请码过期、重复兑换、撤销、密码暴力尝试、Turnstile 重放、会话撤销和首次改密。
- 在两路处理任务下观察 CPU、内存、磁盘、任务排队、失败清理和备份恢复。
- 全部已开放平台完成“登录 -> Cookie 续期 -> 测试发布”闭环；任一平台失败则关闭该平台入口，不影响其他平台。
- 出现认证异常、跨用户访问、磁盘告警、异常资源消耗或浏览器自动化失败率激增时，立即关闭邀请码注册和受影响平台入口，保留脱敏审计证据并恢复到管理员手工创建账号模式。

## 7. 参考资料

- [腾讯云域名注册与实名认证](https://cloud.tencent.com/document/product/242/9595)
- [腾讯云地域与 ICP 备案规则](https://cloud.tencent.com/document/faq/213/17276)
- [Cloudflare Turnstile 服务端校验](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)
- [Spug 短信验证码接入说明](https://push.spug.cc/guide/sms-code)
