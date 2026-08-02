# Vidferry

Vidferry 是本地优先的视频采集、处理、素材管理与多平台发布工具。它将 YouTube 线索检索、下载、字幕处理、处理版本二剪辑增强、发布文案和账号发布串成一个可追踪的工作流。

项目面向本机或受控内网部署。YouTube、平台登录和自动发布都依赖本机网络、浏览器及第三方平台规则，不适合作为直接暴露公网的多租户服务。

## 主要能力

- YouTube 关键词检索与链接导入，下载原视频并进入本地素材库。
- 基于 faster-whisper 的转写、翻译、字幕修订和 FFmpeg 字幕烧制。
- 处理版本二：原作者信息、封面片头、最多三段高光片头，以及可选的 YouTube 评论烧制。
- 评论烧制只在处理时开启：抓取最多 100 条热门顶层评论，经 LLM 筛选后最多展示 20 条；非中文评论显示中文翻译。
- LLM 生成标题、描述、话题、总结和高光建议；发布前可由 Agent 进行文案与关键帧审核。
- 素材、发布稿、账号和发布任务管理，支持抖音、Bilibili、快手、视频号和小红书。
- 本地 PostgreSQL、固定 `admin` / `user` 角色及平台 Cookie 保护。

## 技术栈

- 后端：Python 3.10-3.12、Flask、PostgreSQL
- 前端：Vue 3、Vite、Element Plus、Pinia
- 视频与 AI：yt-dlp、faster-whisper、FFmpeg、OpenAI-compatible Chat Completions API
- 自动化：patchright / Chrome，Bilibili 使用 biliup 运行时

## 快速开始

首次部署请按 [快速部署](QUICK_DEPLOYMENT.md) 执行。配置项说明见 [配置参考](CONFIGURATION.md)。

本地环境准备完成后，分别启动后端和前端：

```powershell
conda run -n vidferry python run.py
```

```powershell
Set-Location sau_frontend
npm run dev
```

默认访问地址：

- 控制台：`http://127.0.0.1:55173`
- 后端：`http://127.0.0.1:5409`

首次启动空数据库后，创建管理员：

```powershell
conda run -n vidferry python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

## 处理流程

```text
YouTube 线索 / 链接
  -> 下载原视频
  -> 转写与翻译
  -> LLM 分析（可选）
  -> 字幕、封面、高光、评论烧制
  -> 处理后素材
  -> 发布稿与平台发布
```

处理版本二中的评论烧制不会在检索线索时抓取。只有用户启用评论开关并提交处理任务后，后台才请求评论并进行 LLM 筛选；失败、无合格评论或视频过短时只跳过评论层，不影响主成片。

## 项目目录

```text
app/                       后端 API、核心服务、任务与数据库模块
app/db/migrations/         PostgreSQL 迁移文件
sau_frontend/              Vue 控制台
uploader/                  平台上传适配器
skills/                    平台上传 CLI Skill 及命令契约
videos/                    下载、转写和处理输出（本地数据）
videoFile/                 素材库文件（本地数据）
cookiesFile/               平台登录 Cookie（本地敏感数据）
docs/                      中文功能与运维文档
```

## 文档索引

- [快速部署](QUICK_DEPLOYMENT.md)
- [配置参考](CONFIGURATION.md)
- [用户认证与部署](docs/用户认证与部署.md)
- [SQLite 迁移至 PostgreSQL](docs/SQLite迁移至PostgreSQL.md)
- [处理版本二评论烧制功能说明](docs/处理版本二评论烧制功能需求.md)
- [前端控制台说明](sau_frontend/README.md)

## 本地数据与安全

`.env`、`conf.py`、`cookiesFile/`、`videos/`、`videoFile/`、数据库备份和前端构建产物均为本地运行数据，不应提交到 Git。LLM 密钥、认证密钥、登录 Cookie 和用户密码不得写入前端代码或日志。

生产环境应使用 HTTPS、设置强随机的 `VIDFERRY_AUTH_SECRET`、启用 `VIDFERRY_AUTH_COOKIE_SECURE=true`，并让后端仅监听受控网络。
