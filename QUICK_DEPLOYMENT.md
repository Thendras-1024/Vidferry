# Vidferry 快速部署指南

本指南面向 Windows 10/11 和 PowerShell。部署 Agent 必须先完成环境检查；已经安装且版本符合要求的工具应直接复用，缺失或版本不符合要求时应协助用户安装并重新验证。

## 0. 检查并安装本机工具

先在 PowerShell 执行以下检查：

```powershell
conda --version
python --version
node --version
npm --version
git --version
ffmpeg -version

$chromePaths = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)
$chromePath = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chromePath) { & $chromePath --version } else { Write-Host "Google Chrome 未安装" }
```

目标版本和用途：

- Conda：用于创建后端 Python 环境。
- Python：`>=3.10,<3.13`；本指南创建 Python 3.12 的 Conda 环境。
- Node.js/npm：Node.js `>=18`，用于前端和 YouTube 下载所需的 JS runtime。
- Git：用于克隆仓库。
- FFmpeg：用于视频处理；必须能运行 `ffmpeg -version`。
- Google Chrome：用于扫码登录和各平台发布。

缺少工具时，先检查 Windows 包管理器是否可用：

```powershell
winget --version
```

如果可用，按缺失项安装。安装命令需要网络；遇到管理员授权或安装器确认时，应提示用户确认后继续。不要重装已通过检查的工具。

```powershell
# Conda（安装后需关闭并重新打开 PowerShell，再执行 conda init powershell）
winget install --id Anaconda.Miniconda3 -e --accept-package-agreements --accept-source-agreements

# Node.js LTS（包含 npm）
winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements

# Git
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements

# FFmpeg
winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements

# Google Chrome
winget install --id Google.Chrome -e --accept-package-agreements --accept-source-agreements
```

安装完成后，重新打开 PowerShell，必要时执行 `conda init powershell` 并再次打开终端，然后重复本节的检查命令。若 `winget` 不可用或某个包安装失败，向用户说明缺少的工具和失败原因，并打开其官方安装渠道协助完成安装；安装后仍须验证版本和命令可用性。

> YouTube 下载及首次下载 biliup 运行时需要用户自行开启 VPN/代理。LLM API Key/Base URL/模型名和各平台扫码登录属于用户信息，不能编造或替代完成。

## 1. 克隆项目

若当前目录还不是 Vidferry 仓库：

```powershell
git clone https://github.com/Thendras-1024/Vidferry.git
cd Vidferry
```

## 2. 创建后端环境并安装依赖

```powershell
conda create -n vidferry python=3.12 -y
conda activate vidferry
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
```

后端运行、CLI、视频下载/处理和平台自动化发布都需要在 `vidferry` 环境中执行。`pip install -e .` 会以开发模式安装项目并注册 `sau` 命令。

Linux/macOS 上如 `requirements.txt` 存在平台兼容性问题，可优先使用：

```powershell
pip install -e ".[web]"
```

如果使用 uv，也可以执行：

```powershell
python -m pip install uv
uv sync --extra web
```

## 3. 安装浏览器自动化依赖

项目使用 `patchright` 驱动浏览器。国内网络可使用镜像：

```powershell
conda activate vidferry
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
patchright install chromium
```

即使已安装本机 Chrome，也需要安装 Patchright Chromium。Chrome 用于更稳定的扫码登录和发布流程。

## 4. 配置后端文件

仅在文件不存在时从示例创建；已有 `conf.py` 或 `.env` 时保留用户现有配置并补充必要项。

```powershell
if (-not (Test-Path conf.py)) { Copy-Item conf.example.py conf.py }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

检查 `conf.py`。将 `LOCAL_CHROME_PATH` 填为第 0 步检测到的 Chrome 路径；FFmpeg 已加入 PATH 时保留 `ffmpeg`，否则填入其绝对路径：

```python
LOCAL_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
LOCAL_CHROME_HEADLESS = False
FFMPEG_COMMAND = "ffmpeg"
YOUTUBE_DOWNLOAD_DIR = BASE_DIR.parent / "video"
YOUTUBE_PROCESSED_DIR = BASE_DIR / "videos" / "processed"
```

`.env` 至少保留以下本地路径配置；LLM 配置在用户提供 API 信息后再填写：

```env
YOUTUBE_DOWNLOAD_DIR=./videos/youtube
YOUTUBE_PROCESSED_DIR=./videos/processed
YOUTUBE_TRANSCRIPT_DIR=./videos/transcripts

# 可选：YouTube 需要 JS challenge 时使用
# YTDLP_JS_RUNTIME=node
# YTDLP_JS_RUNTIME_PATH=C:/Program Files/nodejs/node.exe
# YTDLP_REMOTE_COMPONENTS=ejs:github

# 可选：内容分析和发布文案生成（由用户提供真实值）
# LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# LLM_API_KEY=sk-your-key
# LLM_MODEL=qwen-plus
# LLM_TIMEOUT=90
# LLM_MAX_TRANSCRIPT_CHARS=28000

# 可选：Agent 文本模型和视觉审核模型
# AGENT_CHAT_MODEL=qwen3.6-27b
# AGENT_VISION_MODEL=your-vision-model

# 可选：Whisper 转写模型下载和缓存
# HF_HOME=./models/huggingface
# HF_ENDPOINT=https://hf-mirror.com
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

仅在需要配置 Chrome、FFmpeg、LLM 或 yt-dlp JS runtime 时，读取仓库根目录的 [CONFIGURATION.md](CONFIGURATION.md)。

## 5. 安装前端依赖

```powershell
cd sau_frontend
npm install
cd ..
```

## 6. 启动服务并验证

在项目根目录打开第一个终端，启动后端：

```powershell
conda activate vidferry
python run.py
```

默认后端地址是 `http://127.0.0.1:5409`。若需变更，在 `.env` 中设置 `VIDFERRY_HOST` 和 `VIDFERRY_PORT`。

```env
VIDFERRY_HOST=0.0.0.0
VIDFERRY_PORT=5409
```

打开第二个终端，启动前端：

```powershell
cd sau_frontend
npm run dev
```

访问 `http://127.0.0.1:5173`，确认首页正常加载。Vite 已将 `/api` 代理到 `http://127.0.0.1:5409`。

## 部署 Agent 执行准则

1. 每完成一个阶段，简短汇报检查结果、安装内容或错误处理结果。
2. 遇到命令失败先自行排查并重试；不要跳过环境验证。
3. 仅在需要用户授权、VPN/代理、LLM API 信息或平台扫码登录时暂停并询问用户。
4. 不要把 `.env`、`conf.py`、Cookie 或 API Key 提交到 Git。
