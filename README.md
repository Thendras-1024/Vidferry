# Vidferry

Vidferry 是一个本地优先的视频采集、处理、素材管理和多平台发布工作流。它把 YouTube 视频线索查询、视频下载、ASR 转写、字幕翻译、FFmpeg 字幕烧录、LLM 发布文案生成、素材管理和发布准备串成一条完整流程。

当前版本仍处于本地开发和个人工作流验证阶段，不建议直接作为生产 SaaS 使用。平台登录、发布和 YouTube 下载能力都依赖本机环境以及第三方平台规则，可能需要持续维护。

## 功能概览

- 视频采集处理：关键词批量查询 YouTube、单链接导入、线索状态筛选、下载和处理任务追踪。
- 视频下载：基于 `yt-dlp` 下载视频，并写入本地素材库。
- 字幕处理：基于 `faster-whisper` 转写，生成目标语言字幕，并默认保留英文字幕。
- 视频烧录：基于 FFmpeg 输出国内平台更兼容的 MP4，并在左上角烧录原作者信息。
- 内容分析：基于 OpenAI-compatible LLM 生成标题候选、作品描述、话题标签、视频总结和高光片段建议。
- 素材管理：区分下载原视频和处理后视频，支持预览、删除和状态同步。
- 发布中心：选择处理后视频，自动带入发布稿，并按平台账号提交发布任务。
- 账号管理：维护抖音、B站、快手、视频号、小红书账号 Cookie 状态。

## 技术栈

- 后端：Python 3.10-3.12、Flask、SQLite
- 前端：Vue 3、Vite、Element Plus、Pinia
- 下载：yt-dlp
- 转写：faster-whisper / CTranslate2
- 视频处理：FFmpeg
- 浏览器自动化：patchright / Chrome
- B站发布：biliup
- 内容分析：OpenAI-compatible Chat Completions API

## 系统要求

推荐环境：

- Windows 10/11
- Python `>=3.10,<3.13`
- Node.js `>=18`
- Git
- Google Chrome
- FFmpeg
- uv，推荐；也可用 pip

必须能在终端执行：

```powershell
python --version
node --version
npm --version
git --version
ffmpeg -version
```

如果 `ffmpeg -version` 不可用，需要先安装 FFmpeg 并加入 PATH，或在 `conf.py` 中配置 `FFMPEG_COMMAND`。

## 快速部署

以下命令以 Windows PowerShell 为例。

### 1. 克隆项目

```powershell
git clone https://github.com/Thendras-1024/Vidferry.git
cd Vidferry
```

如果你使用的是上游仓库地址，也可以替换为：

```powershell
git clone https://github.com/dreammis/social-auto-upload.git
cd social-auto-upload
```

### 2. 创建后端虚拟环境

推荐使用 uv：

```powershell
python -m pip install uv
uv sync --extra web
```

如果你希望尽量复现当前开发环境，也可以使用仓库中的 `requirements.txt`。这个文件来自当前可运行环境的 `pip freeze > requirements.txt`，版本锁定更完整，但也可能包含历史依赖或 Windows 平台相关依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
```

说明：

- `pip install -r requirements.txt` 用于安装当前环境快照中的依赖。
- `pip install -e .` 用于把项目本身以开发模式安装，并注册 `sau` 命令。
- 如果你只想按项目声明的最小依赖安装，优先使用 `uv sync --extra web` 或 `pip install -e ".[web]"`。

如果不用 uv：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -e .[web]
```

如果你的 shell 不支持 `.[web]`，可以使用：

```powershell
pip install -e ".[web]"
```

### 3. 安装浏览器自动化依赖

项目使用 `patchright` 驱动浏览器。国内网络可使用镜像：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
.\.venv\Scripts\patchright.exe install chromium
```

如果你已经安装了本机 Chrome，也建议在 `conf.py` 中配置 `LOCAL_CHROME_PATH`，扫码登录和发布流程通常更稳定。

### 4. 配置后端文件

复制配置文件：

```powershell
Copy-Item conf.example.py conf.py
Copy-Item .env.example .env
```

建议至少检查 `conf.py`：

```python
LOCAL_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
LOCAL_CHROME_HEADLESS = False
FFMPEG_COMMAND = "ffmpeg"
YOUTUBE_DOWNLOAD_DIR = BASE_DIR.parent / "video"
YOUTUBE_PROCESSED_DIR = BASE_DIR / "videos" / "processed"
```

`.env` 推荐配置：

```env
YOUTUBE_DOWNLOAD_DIR=./videos/youtube
YOUTUBE_PROCESSED_DIR=./videos/processed
YOUTUBE_TRANSCRIPT_DIR=./videos/transcripts

# 可选：YouTube 需要 JS challenge 时使用
# YTDLP_JS_RUNTIME=node
# YTDLP_JS_RUNTIME_PATH=C:/Program Files/nodejs/node.exe
# YTDLP_REMOTE_COMPONENTS=ejs:github

# 可选：内容分析和发布文案生成
# LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# LLM_API_KEY=sk-your-key
# LLM_MODEL=qwen-plus
# LLM_TIMEOUT=90
# LLM_MAX_TRANSCRIPT_CHARS=28000
```

说明：

- `.env` 用于本地路径、LLM 和 yt-dlp 运行参数。
- `conf.py` 用于本机 Chrome、FFmpeg、默认下载目录等本地配置。
- 两者都属于本地配置，不要提交到 Git。

### 5. 安装前端依赖

```powershell
cd sau_frontend
npm install
cd ..
```

### 6. 启动后端

在项目根目录打开第一个终端：

```powershell
.\.venv\Scripts\python.exe run.py
```

默认后端地址：

```text
http://127.0.0.1:5409
```

如果要修改监听地址或端口，在 `.env` 中配置：

```env
VIDFERRY_HOST=0.0.0.0
VIDFERRY_PORT=5409
```

### 7. 启动前端

打开第二个终端：

```powershell
cd sau_frontend
npm run dev
```

默认前端地址：

```text
http://127.0.0.1:5173
```

Vite 已配置代理：前端请求 `/api` 会转发到 `http://127.0.0.1:5409`。

## 首次使用流程

### 1. 打开 Web 控制台

访问：

```text
http://127.0.0.1:5173
```

### 2. 配置账号

进入“账号管理”，添加需要发布的平台账号。

平台说明：

- 抖音、小红书、快手、视频号：通常会打开浏览器或展示二维码，按页面提示扫码登录。
- B站：使用 biliup 能力，首次运行可能自动准备运行时文件。

Cookie 文件会保存到：

```text
cookiesFile/
```

这些文件包含账号登录信息，不要提交、分享或上传到公开环境。

### 3. 查询或导入视频

进入“视频采集处理”：

- 使用关键词批量查询 YouTube 候选视频。
- 或粘贴单个 YouTube 链接导入。

### 4. 下载视频

在线索列表中点击下载。下载完成后，原视频会进入“素材管理”的下载原视频区域。

如果 YouTube 提示需要 JS runtime，可安装 Node.js 或 Deno，并在 `.env` 中配置 `YTDLP_JS_RUNTIME`。

### 5. 处理视频

点击“处理”或“一键处理”后，系统会执行：

```text
读取原视频 -> 提取音频 -> Whisper 转写 -> 翻译字幕 -> 生成 ASS -> FFmpeg 烧录 -> 处理后素材入库
```

处理版本：

- 处理版本一：基础字幕处理和左上角原作者信息。
- 处理版本二：在基础处理上叠加高光片段分析和剪辑增强，仍在迭代中。

### 6. 生成和编辑发布稿

LLM 配置完成后，系统可以生成：

- 标题候选
- 作品描述
- 话题标签
- 视频总结
- 高光片段建议

LLM 原始结果只读保存。用户最终发布使用的标题、文案、话题会作为发布稿单独保存。

### 7. 发布中心发布

进入“发布中心”：

1. 选择一个处理后视频。
2. 选择一个或多个平台账号，每个平台最多一个账号。
3. 检查发布内容。
4. 按平台设置专属字段，例如：
   - 抖音：商品名称、商品链接
   - B站：投稿分区
5. 提交发布。

已成功发布过的平台会被限制重复发布，避免同一个视频重复发到同一平台。

## 目录说明

```text
app/                 后端 API、核心业务、数据库、任务和工具模块
sau_backend.py       兼容入口，负责加载模块化后端
run.py               后端正式启动入口
sau_frontend/        Vue 3 + Vite 前端
uploader/            各平台上传适配器
myUtils/             账号、登录和历史工具函数
utils/               通用工具
videos/              下载、转写、处理输出目录
videoFile/           素材库文件目录
db/                  本地 SQLite 数据库
cookiesFile/         平台账号 Cookie 文件
docs/                安装、CLI 和历史设计文档
```

## 关键配置说明

### FFmpeg

默认使用 PATH 中的 `ffmpeg`：

```python
FFMPEG_COMMAND = "ffmpeg"
```

如果 FFmpeg 没有加入 PATH，可以写绝对路径：

```python
FFMPEG_COMMAND = "D:/tools/ffmpeg/bin/ffmpeg.exe"
```

### Chrome

建议配置本机 Chrome：

```python
LOCAL_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
LOCAL_CHROME_HEADLESS = False
```

`LOCAL_CHROME_HEADLESS = False` 会显示浏览器窗口，适合扫码登录和排查发布流程。

### LLM

内容分析使用 OpenAI-compatible API。DashScope 示例：

```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-your-dashscope-key
LLM_MODEL=qwen-plus
LLM_TIMEOUT=90
LLM_MAX_TRANSCRIPT_CHARS=28000
```

不配置 LLM 时，下载、字幕处理和素材管理仍可使用，但内容总结和发布文案生成不可用或会失败。

### YouTube 下载

yt-dlp 会随 Python 依赖安装。某些 YouTube 页面可能需要 JS runtime：

```env
YTDLP_JS_RUNTIME=node
YTDLP_JS_RUNTIME_PATH=C:/Program Files/nodejs/node.exe
```

或使用 Deno：

```env
YTDLP_JS_RUNTIME=deno
YTDLP_JS_RUNTIME_PATH=C:/Users/you/.deno/bin/deno.exe
```

## CLI 使用

安装后可以使用 `sau` 命令：

```powershell
.\.venv\Scripts\sau.exe --help
.\.venv\Scripts\sau.exe douyin --help
.\.venv\Scripts\sau.exe xiaohongshu --help
.\.venv\Scripts\sau.exe kuaishou --help
.\.venv\Scripts\sau.exe bilibili --help
```

示例：

```powershell
.\.venv\Scripts\sau.exe douyin login --account creator
.\.venv\Scripts\sau.exe douyin check --account creator
.\.venv\Scripts\sau.exe douyin upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
```

B站示例：

```powershell
.\.venv\Scripts\sau.exe bilibili login --account creator
.\.venv\Scripts\sau.exe bilibili check --account creator
.\.venv\Scripts\sau.exe bilibili upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 21
```

更多 CLI 说明见 [docs/CLI.md](docs/CLI.md)。

## 常见问题

### 后端启动失败：缺少 flask_cors

说明 Web 依赖没有安装完整。使用：

```powershell
uv sync --extra web
```

或：

```powershell
pip install -e ".[web]"
```

### 前端能打开，但接口请求失败

检查后端是否运行在：

```text
http://127.0.0.1:5409
```

再检查 `sau_frontend/vite.config.js` 中 `/api` 代理是否仍指向该端口。

### FFmpeg 相关错误

先确认：

```powershell
ffmpeg -version
```

如果不可用，请安装 FFmpeg 或在 `conf.py` 中配置 `FFMPEG_COMMAND` 的绝对路径。

### YouTube 查询或下载失败

常见原因：

- 网络无法访问 YouTube。
- yt-dlp 版本过旧。
- YouTube 页面需要 JS runtime。
- 视频本身不可下载或受地区、年龄、版权限制。

可尝试：

```powershell
.\.venv\Scripts\python.exe -m pip install -U yt-dlp
```

并配置 Node.js 或 Deno。

### Whisper 很慢

默认可在 CPU 上运行，但长视频会比较慢。可以通过环境变量调整：

```env
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

如果本机有兼容 GPU，可自行配置 faster-whisper 支持的设备和 compute type。

### 平台登录或发布失败

平台页面和规则变化会影响自动化发布。建议：

- 保持 `LOCAL_CHROME_HEADLESS=False`，方便观察浏览器。
- 先在账号管理里刷新或重新连接账号。
- 确认 Cookie 文件存在于 `cookiesFile/`。
- 发布过程中不要手动关闭自动化浏览器窗口。

## 本地数据与安全

以下内容属于本地运行数据，不应提交到 Git：

```text
.env
conf.py
cookiesFile/
db/*.db
qrcode.png
videos/
videoFile/
sau_frontend/dist/
sau_frontend/node_modules/
```

安全提醒：

- Cookie 文件等同于账号登录凭证。
- LLM API Key 不要写入前端代码或提交记录。
- 发布、删除、下载接口都应只在可信本地环境使用。
- 当前版本没有多用户权限系统，不建议暴露到公网。

## 开发验证

后端语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile sau_backend.py
```

前端构建：

```powershell
cd sau_frontend
npm run build
```

启动顺序建议：

1. 启动后端：`.\.venv\Scripts\python.exe run.py`
2. 启动前端：`cd sau_frontend && npm run dev`
3. 修改后端配置或 Python 代码后，通常需要重启后端。
4. 修改前端后，Vite 通常会热更新。

## 项目状态

- 当前定位：本地优先、单机工作流、开发验证。
- 当前重点：稳定视频采集、下载、字幕处理、内容分析、素材管理和发布准备链路。
- 后续方向：更完整的剪辑版本二、封面帧、云端 OSS、多用户权限、任务队列和更严格的平台发布状态管理。

## 致谢

Vidferry 基于并参考了以下开源项目和工具：

- yt-dlp
- social-auto-upload
- FFmpeg
- faster-whisper / CTranslate2
- deep-translator
- patchright / Playwright
- biliup

## License

MIT License

## 异常报错排查

- `Remote end closed connection without response`：通常是请求被 LLM API 远端服务器识别为非法或异常请求。先检查 VPN/代理是否异常；如果仍然出现，尝试关闭 VPN 后重试。
