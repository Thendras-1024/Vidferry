# Vidferry 快速部署

本指南用于 Windows 本地部署 Vidferry。项目运行期使用 PostgreSQL。

## 1. 前置条件

- Conda 或 Miniforge，建议 Python 3.12。
- Node.js 20+ 与 npm，用于前端和 yt-dlp 的 YouTube JS runtime。
- FFmpeg，命令需可在 `PATH` 中执行。
- Docker Desktop，用于本地 PostgreSQL。
- Google Chrome，用于平台登录和发布自动化。

检查工具：

```powershell
conda --version
python --version
node --version
npm --version
ffmpeg -version
docker --version
```

## 2. 创建 Python 环境并安装依赖

在项目根目录执行：

```powershell
conda create -n vidferry python=3.12 -y
conda run -n vidferry python -m pip install --upgrade pip
conda run -n vidferry python -m pip install -r requirements.txt
conda run -n vidferry python -m pip install -e .
```

如后端提示缺少 Flask、认证或 CORS 依赖，补装 Web extra：

```powershell
conda run -n vidferry python -m pip install -e ".[web]"
```

安装前端依赖：

```powershell
Set-Location sau_frontend
npm install
Set-Location ..
```

## 3. 准备本地配置与 PostgreSQL

准备脚本会从 `.env.example` 生成 `.env`（如文件不存在），并为本机写入数据库密码、连接串和认证密钥：

```powershell
conda run -n vidferry python scripts/prepare_local_env.py
docker compose --env-file .env -f docker-compose.postgres.yml up -d
```

确认数据库已启动：

```powershell
docker compose --env-file .env -f docker-compose.postgres.yml ps
```

然后编辑 `.env`，至少将 `TEXT_LLM_API_KEY` 替换为本地真实密钥。模型配置、GPU 转写和超时项见 [配置参考](CONFIGURATION.md)。`.env` 不得提交或共享。

## 4. 启动服务

启动后端：

```powershell
conda run -n vidferry python run.py
```

另开一个终端启动前端：

```powershell
Set-Location E:\Vidferry\sau_frontend
npm run dev
```

打开 `http://127.0.0.1:55173`。前端会将 `/api` 与 `/accounts` 请求代理到 `http://127.0.0.1:5409`。

## 5. 创建首个管理员

数据库为空时创建首个管理员：

```powershell
conda run -n vidferry python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

密码以交互方式输入，不会写入命令历史。后续用户由管理员在控制台的“用户与安全”页面创建。

## 6. 首次使用检查

1. 登录控制台，确认素材列表可打开。
2. 在“视频采集处理”导入一个可访问的 YouTube 链接。
3. 下载后检查 `videos/youtube/` 是否生成原视频。
4. 执行一次处理，确认 FFmpeg、转写与字幕流程正常。
5. 需要评论烧制时，在处理版本二中启用该开关。它会在处理阶段而非检索阶段抓取评论，LLM 或 yt-dlp 失败时主成片仍会继续。
6. 使用发布前先在账号管理中完成各平台登录，并在发布中心确认 Cookie 状态。

## 常见问题

### 后端无法连接数据库

确认 `.env` 中 `DATABASE_URL` 非空，且 PostgreSQL 容器运行：

```powershell
docker compose --env-file .env -f docker-compose.postgres.yml logs postgres
```

### 前端可以打开但接口失败

确认 `python run.py` 正在运行在 `127.0.0.1:5409`，且没有修改 `sau_frontend/vite.config.js` 中的代理目标。

### YouTube 下载或评论获取失败

确认网络可访问 YouTube，Node.js 20+ 已安装，并保留 `.env` 中的 `YTDLP_REMOTE_COMPONENTS=ejs:github`。更新到 yt-dlp nightly 后重试；该版本包含 YouTube 当前媒体流 403 的修复，并安装默认 EJS 组件：

```powershell
conda run -n vidferry python -m pip install -U --pre "yt-dlp[default]"
```

评论是否可取由视频的公开评论状态、地区限制和 yt-dlp 当前解析能力决定；评论失败只会跳过评论层。

### LLM 请求超时

默认 `LLM_TIMEOUT=180` 秒。可在 `.env` 取消注释并设置更大值，例如 `LLM_TIMEOUT=240`，然后重启后端。也可保持 `LLM_DISABLE_THINKING=true` 降低推理模型延迟。

### GPU 转写或 NVENC 失败

先使用默认 CPU 配置 `WHISPER_DEVICE=cpu`、`WHISPER_COMPUTE_TYPE=int8` 和 `VIDEO_ENCODER=libx264` 验证流程。GPU 模式必须由当前 CUDA、驱动及 FFmpeg 实际支持。

## 生产部署提示

生产环境使用 HTTPS 反向代理，让后端只监听内网或 `127.0.0.1`，设置 `VIDFERRY_AUTH_COOKIE_SECURE=true` 与强随机 `VIDFERRY_AUTH_SECRET`，并保持单个后端进程运行。详情见 [用户认证与部署](用户认证与部署.md)。
