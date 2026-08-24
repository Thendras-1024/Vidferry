# Vidferry 配置参考

所有运行时配置从项目根目录 `.env` 读取；同名系统环境变量优先。以 `.env.example` 为起点，修改后重启后端才会生效。不要提交 `.env`，也不要把其中的密码、API Key、Cookie 或连接串写入日志。

首次本地部署可执行 `python scripts/prepare_local_env.py`，它会补齐 PostgreSQL 密码、`DATABASE_URL` 和认证密钥，但不会填写 LLM 或平台登录凭据。

## 配置边界

`.env.example` 是 Windows 本地部署的完整配置样例。下文覆盖其中全部配置项，并补充代码支持但默认未写入样例的常用覆盖项。基础下载、转写与素材管理不依赖 LLM；数据库、认证和目录配置则是启动所必需的。

当前不支持 Linux 域名部署。`VIDFERRY_HOST`、`VIDFERRY_CORS_ORIGINS`、HTTPS Cookie 和受信任代理相关配置只应作为未来方案的约束预先理解，不应据此自行拼装公网部署。

## 路径、服务与数据库

| 配置 | 说明 |
| --- | --- |
| `YOUTUBE_DOWNLOAD_DIR` | 原视频下载目录。相对路径以从项目根目录启动后端为准。 |
| `YOUTUBE_PROCESSED_DIR` | 处理后成片目录。 |
| `YOUTUBE_TRANSCRIPT_DIR` | 转写、翻译等文本目录。 |
| `VIDFERRY_HOST` / `VIDFERRY_PORT` | 后端监听地址和端口，默认 `127.0.0.1` / `5409`。Windows 本地部署通常不需要填写。 |
| `VIDFERRY_CORS_ORIGINS` | 允许的浏览器来源，逗号分隔；默认包含本地前端 `55173`。未来域名部署必须填写精确 HTTPS 来源，不能使用通配符。 |
| `DATABASE_URL` | 必填。PostgreSQL 连接串；本地 Docker 部署由准备脚本生成。 |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `docker-compose.postgres.yml` 使用的本地数据库信息。 |
| `DATABASE_POOL_MIN_SIZE` / `DATABASE_POOL_MAX_SIZE` / `DATABASE_POOL_TIMEOUT_SECONDS` | 可选连接池下限、上限和取连接超时，默认 `1` / `8` / `30` 秒。 |

首次 Windows 本地部署执行 `python scripts/prepare_local_env.py` 后，会补齐 `POSTGRES_*`、`DATABASE_URL` 和 `VIDFERRY_AUTH_SECRET`，不会填写模型或平台凭据。

## YouTube、代理与媒体处理

| 配置 | 说明 |
| --- | --- |
| `YTDLP_PROXY` | YouTube 下载代理。留空时后端会清除继承的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`，确保 yt-dlp 不意外使用系统代理。 |
| `HF_PROXY` | Whisper 首次下载模型时使用的代理，可与 `YTDLP_PROXY` 相同。 |
| `YTDLP_JS_RUNTIME` | yt-dlp 使用的 JS runtime，例如 `node`。未填写时自动查找 Deno 或 Node。 |
| `YTDLP_JS_RUNTIME_PATH` | JS runtime 不在 `PATH` 时填写其绝对路径。 |
| `YTDLP_REMOTE_COMPONENTS` | yt-dlp 远程组件，默认 `ejs:github`；首次下载需要可访问 GitHub。 |
| `YOUTUBE_COOKIE_FILE` | 可选 Netscape Cookie 文件；相对路径必须位于项目目录内。该文件是登录凭据，不提交、不记录路径到日志。 |
| `YOUTUBE_COOKIES_FROM_BROWSER` | 可选浏览器名：`brave`、`chrome`、`chromium`、`edge`、`firefox`、`opera`、`vivaldi` 或 `whale`。 |
| `YOUTUBE_COOKIES_BROWSER_PROFILE` | 可选浏览器 Profile 名称，与上一项配套使用。 |
| `YTDLP_DOWNLOAD_RETRIES` / `YTDLP_FRAGMENT_RETRIES` / `YTDLP_DOWNLOAD_ATTEMPTS` / `YTDLP_SOCKET_TIMEOUT_SECONDS` | 可选下载重试、分片重试、完整下载尝试次数和 socket 超时；默认 `10` / `10` / `3` / `30` 秒。 |
| `WHISPER_MODEL_SIZE` | Whisper 模型，例如 `small`、`medium`、`large-v3`。模型越大，质量、显存和耗时要求越高。 |
| `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | 默认 `cpu` / `int8`。GPU 通常使用 `cuda` 与 `float16` 或 `int8_float16`，需先安装匹配的 CUDA 运行库。 |
| `VIDEO_ENCODER` | `libx264` 或 `h264_nvenc`。后者要求当前 FFmpeg 和 NVIDIA 驱动实际支持 NVENC。 |
| `VIDEO_NVENC_PRESET` / `VIDEO_NVENC_CQ` | 仅 `h264_nvenc` 生效；默认 `p5` / `23`。 |

Whisper 使用 `faster-whisper` 与 CTranslate2。GPU 转写需要安装 CUDA 运行库；CPU 模式使用默认的 `WHISPER_DEVICE=cpu` 与 `WHISPER_COMPUTE_TYPE=int8` 即可。

评论烧制没有独立环境变量：它是处理版本二的界面开关。启用后通过 yt-dlp 请求最多 100 条热门顶层评论，严格正则过滤后每 20 条分批进行 LLM 筛选。评论翻译可在界面选择 `Google 初译 + LLM 修订`（默认）或仅 `Google 初译`；单批失败会保留其他可用评论与 Google 初译结果。

## 文本、Agent 与视觉模型

文本模型用于内容分析、字幕修订、发布文案、Agent 和评论筛选。视觉模型用于关键帧审核。缺少对应模型配置时，依赖该模型的功能会不可用或降级，但基础下载、转写和素材管理仍可用。

```dotenv
TEXT_LLM_PROVIDER=dashscope
TEXT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TEXT_LLM_API_KEY=replace-with-local-secret
TEXT_LLM_MODEL=qwen-plus

MULTIMODAL_LLM_PROVIDER=dashscope
MULTIMODAL_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MULTIMODAL_LLM_API_KEY=replace-with-local-secret
MULTIMODAL_LLM_MODEL=qwen-vl-max
```

`TEXT_LLM_PROVIDER` 和 `MULTIMODAL_LLM_PROVIDER` 支持 `zhipu`、`kimi`、`deepseek`、`volcengine_ark`、`dashscope`、`longcat`、`openai_compatible` 及自动识别。模型不支持的可选字段会由兼容层移除。`AGENT_LLM_PROVIDER`、`AGENT_LLM_BASE_URL`、`AGENT_LLM_API_KEY` 和 `AGENT_LLM_MODEL` 可选；未填写时 Agent 复用 `TEXT_LLM_*`。

常用可选项：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_TIMEOUT` | `180` | 单次 LLM 请求超时秒数。评论筛选或长字幕请求超时时可适当增大。 |
| `LLM_DISABLE_THINKING` | `true` | 请求模型关闭推理输出，以降低延迟和 token 消耗。 |
| `LLM_MAX_TRANSCRIPT_CHARS` | `28000` | 单次分析允许读取的最大转写字符数。 |
| `SUBTITLE_LLM_REVIEW_ENABLED` | `true` | 是否在初译后执行字幕 LLM 修订。 |
| `SUBTITLE_REVIEW_BATCH_MAX_CHARS` / `SUBTITLE_REVIEW_CONCURRENCY` / `SUBTITLE_REVIEW_MAX_TOKENS` | `800` / `4` / `4000` | 可选字幕修订批量控制。 |
| `TRANSLATION_BATCH_MAX_CHARS` / `TRANSLATION_REQUEST_TIMEOUT` / `TRANSLATION_FALLBACK_LINE_LIMIT` | `1200` / `10` / `5` | 可选翻译批量、请求超时与回退行数控制。 |
| `AGENT_LLM_ENABLE_THINKING` | `true` | Agent 复用文本模型时是否保留推理。 |
| `AGENT_OUTPUT_MAX_TOKENS` | `65536` | Agent 输出上限。 |
| `AGENT_CONTEXT_MODEL_WINDOW_TOKENS` | `1000000` | Agent 模型上下文窗口预算。 |
| `AGENT_CONTEXT_COMPACTION_TRIGGER_TOKENS` / `AGENT_CONTEXT_COMPACTION_RECOVERY_TOKENS` | `850000` / `650000` | Agent 对话压缩触发与恢复阈值。 |
| `AGENT_CONTEXT_TOOL_RESULT_MAX_CHARS` / `AGENT_CONTEXT_TOOL_TOTAL_MAX_CHARS` | `16000` / `64000` | Agent 单次工具结果和全部工具结果的字符预算。 |
| `AGENT_REQUIRE_VISION_CHECK` / `AGENT_VISION_FAIL_CLOSED` | `true` / `true` | 是否要求视觉审核，以及视觉不可用时是否阻断。 |
| `AGENT_FRAME_MAX_COUNT` / `AGENT_FRAME_SCALE_WIDTH` | `8` / `640` | 审核关键帧数量和缩放宽度。 |

## 工作流与服务

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `WORKFLOW_MAX_*_JOBS` | 见代码默认 | 下载、处理、发布、分析、评论和检索的并发上限。 |
| `WORKFLOW_MAX_*_QUEUED_JOBS` | 见代码默认 | 各类工作流可排队任务上限。 |
| `CANDIDATE_ANALYSIS_MAX_JOBS` / `CANDIDATE_ANALYSIS_MAX_QUEUED_JOBS` / `CANDIDATE_ANALYSIS_MAX_ITEMS` / `CANDIDATE_ANALYSIS_MAX_DURATION_SECONDS` | `1` / `2` / `3` / `1800` | 候选视频分析的并发、排队、数量和最长运行时间。 |
| `VIDFERRY_USER_STORAGE_QUOTA_MB` | `20480` | 单个用户累计素材空间上限，单位 MB。 |
| `VIDFERRY_USER_UPLOAD_MAX_MB` | `160` | 单次上传体积上限，单位 MB。 |
| `VIDFERRY_USER_UPLOADS_PER_MINUTE` / `VIDFERRY_USER_TASK_SUBMISSIONS_PER_MINUTE` | `10` / `30` | 单用户上传和任务提交频率上限。 |
| `VIDEO_LOCAL_RETENTION_SUCCESS_DAYS` | `3` | 所有发布目标成功后，本地媒体保留天数。 |
| `VIDEO_LOCAL_RETENTION_DAYS` | `7` | 部分成功发布后，本地媒体保留天数。 |
| `VIDEO_LOCAL_CLEANUP_INTERVAL_HOURS` / `VIDEO_LOCAL_CLEANUP_BATCH_SIZE` | `24` / `50` | 本地清理扫描间隔与每轮上限。 |
| `VIDEO_LOCAL_CLEANUP_MODE` | `delete` | `off` 不扫描，`report` 只记录候选，`delete` 删除符合条件的本地媒体并归档线索。 |

并发值过高会同时占用网络、GPU/CPU、FFmpeg 和 LLM 配额；普通本机建议保留默认值。启用 `delete` 前应确认 PostgreSQL、`cookiesFile/` 和本地素材已有受限访问的备份。

## 飞书与快手开放平台

| 配置 | 说明 |
| --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用凭据，仅在本机 `.env` 保存。 |
| `FEISHU_ALLOWED_OPEN_IDS` | 允许使用机器人的飞书 open ID，逗号分隔。 |
| `FEISHU_AGENT_OWNER_USER_ID` | 飞书 Agent 归属的本地用户 ID。 |
| `FEISHU_ROBOT_ENABLED` | 是否启动飞书长连接机器人，默认 `false`。 |
| `FEISHU_BUTLER_CONSOLE_URL` | 飞书回复中使用的控制台地址，默认本地 `http://127.0.0.1:55173`。 |
| `KUAISHOU_OPEN_APP_ID` / `KUAISHOU_OPEN_APP_SECRET` | 可选快手开放平台凭据；账号 access token 保存在账号所有者的 Cookie sidecar，不在 `.env` 或日志中保存。 |

## 认证与安全

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `VIDFERRY_AUTH_SECRET` | 由准备脚本生成 | 认证会话密钥。必须保密；未来 HTTPS 域名部署必须改为随机长值。 |
| `VIDFERRY_AUTH_COOKIE_SECURE` | `false` | HTTPS 生产环境设为 `true`。 |
| `VIDFERRY_AUTH_IDLE_MINUTES` | `480` | 空闲会话超时分钟数。 |
| `VIDFERRY_AUTH_ABSOLUTE_HOURS` | `24` | 会话绝对有效期。 |
| `VIDFERRY_AUTH_REMEMBER_HOURS` | `168` | 勾选记住登录后的最长有效期。 |
| `VIDFERRY_AUTH_ALLOW_COOKIE_EXPORT` | `false` | 默认禁止导出平台 Cookie。 |
| `VIDFERRY_AUTH_PHONE_LOGIN_ENABLED` | `false` | 启用腾讯云短信验证码登录。 |
| `VIDFERRY_AUTH_PHONE_AUTO_REGISTER_ENABLED` | `false` | 启用首次手机号验证自动注册；上线前完成短信额度与资源配额检查。 |
| `VIDFERRY_AUTH_PHONE_HMAC_SECRET` | 空 | 手机验证码 HMAC 密钥；启用手机号登录时必须填写。 |
| `VIDFERRY_AUTH_RATE_LIMIT_HMAC_SECRET` | 复用认证密钥 | 限流身份散列密钥。建议在长期部署中独立设置。 |
| `VIDFERRY_AUTH_TENCENT_SECRET_ID` / `VIDFERRY_AUTH_TENCENT_SECRET_KEY` | 空 | 腾讯云 API 凭据，仅启用手机号登录时填写。 |
| `VIDFERRY_AUTH_TENCENT_SMS_APP_ID` / `VIDFERRY_AUTH_TENCENT_SMS_SIGN` / `VIDFERRY_AUTH_TENCENT_SMS_TEMPLATE_ID` | 空 | 腾讯云短信应用、签名和模板。 |
| `VIDFERRY_AUTH_TENCENT_CAPTCHA_APP_ID` / `VIDFERRY_AUTH_TENCENT_CAPTCHA_APP_SECRET_KEY` | 空 | 腾讯云验证码应用配置。 |
| `VIDFERRY_AUTH_TENCENT_REGION` | `ap-guangzhou` | 腾讯云服务地域。 |
| `VIDFERRY_AUTH_TRUSTED_PROXY_CIDRS` | 空 | 仅当 TCP 对端属于这些 CIDR 时读取 `X-Forwarded-For`；本地部署保持为空。 |

手机号登录默认关闭。启用前需要完成腾讯云短信签名、模板和验证码审核；先保持自动注册关闭，完成配额、告警和未来 HTTPS 域名部署验收后再开放注册。完整边界见 [用户认证与部署](用户认证与部署.md)。
