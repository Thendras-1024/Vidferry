# Vidferry 配置参考

所有运行时配置从项目根目录 `.env` 读取。以 `.env.example` 为起点；其中带 `#` 的项是可选覆盖项，取消注释并重启后端才会生效。不要提交 `.env`。

首次本地部署可执行 `python scripts/prepare_local_env.py`，它会补齐 PostgreSQL 密码、`DATABASE_URL` 和认证密钥，但不会填写 LLM 或平台登录凭据。

## 必需配置

| 配置 | 说明 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串。本地 Docker 部署由准备脚本生成。 |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `docker-compose.postgres.yml` 使用的本地数据库信息。 |
| `VIDFERRY_AUTH_SECRET` | 认证会话密钥；生产环境必须使用随机长值。 |

## 文本与视觉模型

文本模型用于内容分析、字幕修订、发布文案和评论筛选。视觉模型用于发布前关键帧审核。

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

`TEXT_LLM_PROVIDER` 和 `MULTIMODAL_LLM_PROVIDER` 支持 `zhipu`、`kimi`、`deepseek`、`volcengine_ark`、`dashscope`、`longcat`、`openai_compatible` 及自动识别。模型不支持的可选字段会由兼容层移除。

常用可选项：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_TIMEOUT` | `180` | 单次 LLM 请求超时秒数。评论筛选或长字幕请求超时时可适当增大。 |
| `LLM_DISABLE_THINKING` | `true` | 请求模型关闭推理输出，以降低延迟和 token 消耗。 |
| `LLM_MAX_TRANSCRIPT_CHARS` | `28000` | 单次分析允许读取的最大转写字符数。 |
| `SUBTITLE_LLM_REVIEW_ENABLED` | `true` | 是否在初译后执行字幕 LLM 修订。 |

## YouTube 与媒体处理

| 配置 | 说明 |
| --- | --- |
| `YOUTUBE_DOWNLOAD_DIR` / `YOUTUBE_PROCESSED_DIR` / `YOUTUBE_TRANSCRIPT_DIR` | 原视频、处理成片和转写文件目录。 |
| `YTDLP_JS_RUNTIME` | yt-dlp 使用的 JS runtime，默认示例为 `node`。YouTube 下载建议安装 Node.js 20+。 |
| `YTDLP_JS_RUNTIME_PATH` | Node.js 不在 `PATH` 时填写绝对路径。 |
| `YTDLP_REMOTE_COMPONENTS` | yt-dlp 远程组件，默认 `ejs:github`。首次下载需要可访问 GitHub。 |
| `WHISPER_MODEL_SIZE` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | 转写模型、设备与计算精度。CPU 推荐 `small`、`cpu`、`int8`。 |
| `VIDEO_ENCODER` | `libx264` 或受当前 FFmpeg 与驱动支持的 `h264_nvenc`。 |
| `VIDEO_NVENC_PRESET` / `VIDEO_NVENC_CQ` | NVIDIA 编码器预设与恒定质量，仅 `h264_nvenc` 生效。 |

评论烧制没有独立环境变量：它是处理版本二的界面开关。启用后通过 yt-dlp 请求最多 100 条热门顶层评论，严格正则过滤后每 20 条分批进行 LLM 筛选。评论翻译可在界面选择 `Google 初译 + LLM 修订`（默认）或仅 `Google 初译`；单批失败会保留其他可用评论与 Google 初译结果。

## 工作流与服务

`.env.example` 中已列出以下可选覆盖项：

- `VIDFERRY_HOST`、`VIDFERRY_PORT`、`VIDFERRY_CORS_ORIGINS`
- `WORKFLOW_MAX_*` 与 `WORKFLOW_MAX_*_QUEUED_JOBS`：下载、处理、分析和检索的并发及排队上限。
- `TRANSLATION_*`：翻译批次和请求超时。
- `AGENT_*`：发布前审核、会话上下文、关键帧采样和风险策略。
- `DOUYIN_*`、`TENCENT_*`、`XHS_*`：对应平台的浏览器自动化超时与重试次数。

并发值过高会同时占用网络、GPU/CPU、FFmpeg 和 LLM 配额；普通本机建议保留示例默认值。

## 认证与安全

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `VIDFERRY_AUTH_COOKIE_SECURE` | `false` | HTTPS 生产环境设为 `true`。 |
| `VIDFERRY_AUTH_IDLE_MINUTES` | `480` | 空闲会话超时分钟数。 |
| `VIDFERRY_AUTH_ABSOLUTE_HOURS` | `24` | 会话绝对有效期。 |
| `VIDFERRY_AUTH_REMEMBER_HOURS` | `168` | 勾选记住登录后的最长有效期。 |
| `VIDFERRY_AUTH_ALLOW_COOKIE_EXPORT` | `false` | 默认禁止导出平台 Cookie。 |
| `VIDFERRY_AUTH_PHONE_LOGIN_ENABLED` | `false` | 启用腾讯云短信验证码登录。 |
| `VIDFERRY_AUTH_PHONE_AUTO_REGISTER_ENABLED` | `false` | 启用首次手机号验证自动注册；上线前完成短信额度与资源配额检查。 |

完整部署边界见 [用户认证与部署](用户认证与部署.md)。
