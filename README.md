# Vidferry

Vidferry 是一个本地优先的视频采集、处理、视频素材管理和多平台发布工作流。它把 YouTube 视频线索查询、视频下载、ASR 转写、字幕翻译、FFmpeg 字幕烧录、LLM 发布文案生成、视频素材管理和发布准备串成一条完整流程。

当前版本仍处于本地开发和个人工作流验证阶段，不建议直接作为生产 SaaS 使用。平台登录、发布和 YouTube 下载能力都依赖本机环境以及第三方平台规则，可能需要持续维护。

## 🚀 快速部署 Prompt

```
你是 Vidferry 项目的部署助手。请在我的电脑上完成该项目的完整本地部署。

执行步骤：
1. 若尚未克隆：git clone https://github.com/Thendras-1024/Vidferry.git 并进入目录
2. 仔细阅读仓库根目录的 QUICK_DEPLOYMENT.md，严格按照其中的环境检查、缺失工具安装和部署流程执行；需要配置项说明时，再阅读 CONFIGURATION.md
3. 首先检查 conda、python、node/npm、git、ffmpeg 和 Google Chrome 是否已安装且版本可用；缺失时按 QUICK_DEPLOYMENT.md 协助我安装，安装后重新验证
4. 目标：浏览器能打开 http://127.0.0.1:5173 且首页正常加载
5. 每完成一步向我简短汇报；遇到报错先自行排查并重试
6. 只有在需要我开启 VPN/代理、提供 LLM 的 API Key/Base URL/模型名，或进行各平台账号扫码登录时才停下来问我，不要编造
```
## 界面预览

<p align="center">
  <img src="img/Home.png" alt="首页工作台" title="首页工作台" width="720">
  <br>
  <strong>首页工作台</strong>
</p>

<details>
  <summary>查看全部界面截图</summary>

  <p align="center">
    <img src="img/video_Link.png" alt="视频链接导入与查询" title="视频链接导入与查询" width="720">
    <br>
    <strong>视频链接导入与查询</strong>
  </p>

  <p align="center">
    <img src="img/video_Material_Management1.png" alt="视频素材管理列表" title="视频素材管理列表" width="720">
    <br>
    <strong>视频素材管理列表</strong>
  </p>

  <p align="center">
    <img src="img/video_Material_Management2.png" alt="视频素材详情与预览" title="视频素材详情与预览" width="720">
    <br>
    <strong>视频素材详情与预览</strong>
  </p>

  <p align="center">
    <img src="img/copywriting_Generation1.png" alt="发布文案生成" title="发布文案生成" width="720">
    <br>
    <strong>发布文案生成</strong>
  </p>

  <p align="center">
    <img src="img/copywriting_Generation2.png" alt="发布文案编辑" title="发布文案编辑" width="720">
    <br>
    <strong>发布文案编辑</strong>
  </p>

  <p align="center">
    <img src="img/release_Center.png" alt="发布中心" title="发布中心" width="720">
    <br>
    <strong>发布中心</strong>
  </p>

  <p align="center">
    <img src="img/account_Management.png" alt="账号管理" title="账号管理" width="720">
    <br>
    <strong>账号管理</strong>
  </p>

  <p align="center">
    <img src="img/statistics_Page.png" alt="处理统计" title="处理统计" width="720">
    <br>
    <strong>处理统计</strong>
  </p>

</details>

## 功能概览

- 视频采集处理：关键词批量查询 YouTube、单链接导入、线索状态筛选、下载和处理任务追踪。
- 视频下载：基于 `yt-dlp` 下载视频，并写入本地素材库。
- 字幕处理：基于 `faster-whisper` 词级时间戳生成短语级字幕，生成目标语言字幕，并默认保留英文字幕；旧转写缓存仍可使用，主动重新处理会重新转写以应用新的字幕节奏。
- 视频烧录：基于 FFmpeg 输出国内平台更兼容的 MP4，烧录左上角原作者信息，并可在处理设置中启用文字水印。
- 内容分析：基于 OpenAI-compatible LLM 生成标题候选、作品描述、话题标签、视频总结和高光片段建议。
- 发布前审核：Agent 对发布文案进行风险检查，并可抽取视频关键帧交由视觉模型复核；未配置视觉模型时，默认阻止提交发布。
- 视频素材管理：区分下载原视频和处理后视频，支持预览、删除和状态同步。
- 发布中心：选择处理后视频，自动带入发布稿，并按平台账号提交发布任务。
- 账号管理：维护抖音、B站、快手、视频号、小红书账号 Cookie 状态。

## 技术栈

- 后端：Python 3.10-3.12、Flask、PostgreSQL
- 前端：Vue 3、Vite、Element Plus、Pinia
- 下载：yt-dlp
- 转写：faster-whisper / CTranslate2
- 视频处理：FFmpeg
- 浏览器自动化：patchright / Chrome
- B站发布：biliup
- 内容分析：OpenAI-compatible Chat Completions API

## 目录说明

```text
app/                 后端 API、核心业务、数据库、任务和工具模块
sau_backend.py       兼容入口，负责加载模块化后端
run.py               后端正式启动入口
run_feishu_robot.py  飞书机器人启动入口
sau_frontend/        Vue 3 + Vite 前端
uploader/            各平台上传适配器
myUtils/             账号、登录和历史工具函数
utils/               通用工具
logs/                后端关键流程与各平台上传日志，排查任务失败时优先查看
videos/              下载、转写、处理输出目录
  youtube/            YouTube 原视频及同视频 ID 的本地封面文件，供素材管理页离线预览
videoFile/           素材库文件目录
docker-compose.postgres.yml  PostgreSQL 本地服务定义
cookiesFile/         平台账号 Cookie 文件
docs/                安装、CLI 和历史设计文档
```


## 首次使用流程

### 1. 创建首个管理员

安装依赖并配置 `.env` 后，使用交互式命令创建首个管理员：

```powershell
conda run -n vidferry python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

密码不会出现在命令行参数或日志中。生产部署前请继续阅读 [认证与部署说明](docs/authentication.md)。

### 2. 打开 Web 控制台

访问：

```text
http://127.0.0.1:5173
```

### 3. 配置账号

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

在线索列表中点击下载。下载完成后，原视频会进入“视频素材管理”的下载原视频区域。

首次部署请安装 Node.js 20+。`.env.example` 已默认配置 yt-dlp 的官方 `ejs:github` 组件，用于处理 YouTube JS challenge；Node.js 未加入 `PATH` 时，再填写 `YTDLP_JS_RUNTIME_PATH`。

### 5. 处理视频

点击“处理”或“一键处理”后，系统会执行：

```text
读取原视频 -> 提取音频 -> Whisper 转写 -> 翻译字幕 -> 生成 ASS -> FFmpeg 烧录 -> 处理后素材入库
```

处理版本：

- 处理版本一：基础字幕处理和左上角原作者信息；可在处理设置中启用文字水印，水印内容最长 32 个字符。
- 处理版本二：在基础处理上叠加高光片段分析和剪辑增强，仍在迭代中。

### 6. 生成和编辑发布稿

LLM 配置完成后，系统可以生成：

- 标题候选
- 作品描述
- 话题标签
- 视频总结
- 高光片段建议

LLM 原始结果只读保存。用户最终发布使用的标题、文案、话题会作为发布稿单独保存。

### Agent 发布前审核

发布前审核默认启用。系统会检查发布文案，并从视频抽取关键帧交由多模态模型复核；高风险结论或审核失败会阻止提交发布。请在 `.env` 分别配置文本模型和支持 `image_url` 输入的多模态模型：

```env
TEXT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TEXT_LLM_API_KEY=sk-your-key
TEXT_LLM_MODEL=qwen-plus
TEXT_LLM_PROVIDER=dashscope
MULTIMODAL_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MULTIMODAL_LLM_API_KEY=sk-your-key
MULTIMODAL_LLM_MODEL=qwen-vl-max
MULTIMODAL_LLM_PROVIDER=dashscope
```

文本模型用于内容分析、字幕修订、文案生成和 Agent；多模态模型用于关键帧审核。`*_LLM_PROVIDER` 支持 `zhipu`、`kimi`、`deepseek`、`volcengine_ark`、`dashscope`、`longcat`、`openai_compatible`。四类官方服务使用其 Chat Completions 兼容 Base URL；模型不支持关闭推理或图片输入时，系统会在消息中心持久化提示并按功能策略降级或阻断。多模态模型未配置时，默认策略会阻止发布，避免绕过关键帧审核；内部的抽帧数量、风险阈值和模型参数由程序统一维护，不需要写入 `.env`。

### 飞书远程 Agent

项目可通过飞书自建应用机器人远程调用现有 Vidferry Agent。本机通过飞书长连接接收消息，不需要开放公网 HTTP 端口。

前提：在飞书开放平台创建并发布自建应用，启用机器人能力，订阅 `im.message.receive_v1` 事件并选择长连接接收方式。安装项目依赖时会一并安装 `lark-oapi==1.7.1`。

在本机 `.env` 中配置应用凭据，真实 Secret 不得提交：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_ALLOWED_OPEN_IDS=ou_xxx
```

现有本地配置使用 `appID` 和 `App_Secret` 时，机器人启动脚本也会识别；新配置推荐使用上述 `FEISHU_*` 名称。

首次取得自己的 Open ID 时，可以临时将 `FEISHU_ALLOWED_OPEN_IDS` 留空并启动机器人。所有消息仍会被拒绝，终端会仅记录发送者 Open ID；将该 `ou_xxx` 填入白名单并重启后，消息才会进入 Agent。
通过下方启动脚本运行时，机器人日志会同时写入 `logs/feishu_robot.log`。

```powershell
conda activate vidferry
python run_feishu_robot.py
```

机器人只处理白名单用户的单聊文本。每个用户对应独立的 Agent 会话；机器人先确认收到，再在后台调用 Agent，并以飞书卡片回传最终回答和结构化工具摘要，不发送原始 JSON。项目目录中的 PNG、JPEG、WebP、GIF 工具结果可以作为飞书图片发送，视频文件永不上传或发送。下载、处理、配置修改和发布等写操作尚未接入机器人。

机器人只通过上述独立脚本启动，不会随 `python run.py` 自动运行。每个飞书应用同一时刻只应启动一个机器人进程。

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

### 8. 视频号 CLI 发布

视频号当前支持账号登录、Cookie 校验和视频发布；图文发布尚未实现。登录时会打开浏览器并展示二维码：

```powershell
sau tencent login --account your_account
sau tencent check --account your_account
sau tencent upload-video --account your_account --file D:/videos/output.mp4 --title "视频标题" --desc "发布说明" --tags "话题1,话题2"
```

`upload-video` 可额外使用 `--thumbnail` 指定封面、`--draft` 保存草稿、`--schedule "2026-07-13 20:00:00"` 定时发布，以及 `--headless` 在无头模式运行。平台页面和登录规则可能变化，发布前请先执行 `check` 确认 Cookie 有效。

## 第三方依赖下载与安装说明

### biliup

B站登录、检查和上传能力基于 `biliup`。用户通常不需要手动安装 `biliup`：

- 首次运行 `sau bilibili ...` 或 Web 端 B站相关能力时，程序会自动检查并准备 `biliup` 运行时。
- 如果本地没有可用的 `biliup`，程序会从 GitHub Release 下载适配当前系统的版本。
- 如果自动下载失败，通常是网络无法访问 GitHub Release，可检查代理/VPN，或参考 [docs/install.md](docs/install.md) 中的 Bilibili 运行时说明。

> `yt-dlp` 与 `FFmpeg` 随 Python 依赖安装或属本机工具，其配置与排错统一见 [CONFIGURATION.md](CONFIGURATION.md) 和「常见问题」，此处不再重复。

### faster-whisper / CTranslate2

语音转写依赖 `faster-whisper`，底层推理依赖 `CTranslate2`。它们会安装到 Conda 的 `vidferry` 环境中；Whisper 模型文件不随 Python 包一起安装，默认在首次转写时自动下载。

本项目当前默认模型是 `small`，对应代码会读取 `WHISPER_MODEL_SIZE`，默认值见 `app/core/subtitle_service.py`。如果没有指定缓存目录，模型通常会进入当前用户的 Hugging Face 缓存目录，例如 Windows 下的 `C:\Users\<用户名>\.cache\huggingface\hub`。如果不想占用 C 盘，建议在 `.env` 中指定：

```env
HF_HOME=./models/huggingface
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

常见模型体积大致如下，实际占用会随模型版本略有变化：

| 模型 | 适用场景 | 下载体积 |
| --- | --- | --- |
| `tiny` | 最快，质量最低，适合测试安装 | 约 80 MB |
| `base` | 比 `tiny` 稍准，仍很快 | 约 150 MB |
| `small` | 当前默认，速度和质量比较均衡 | 约 500 MB |
| `medium` | 更准，但 CPU 会明显变慢 | 约 1.5 GB |
| `large-v3` | 质量更高，资源占用大 | 约 3.1 GB |

`large-v3` 首次下载及缓存建议预留至少 5 GB 磁盘空间。CPU 模式建议使用至少 16 GB 内存，但处理速度会明显低于 `small`；如使用 NVIDIA CUDA，建议至少 8 GB 显存，并将 `WHISPER_DEVICE` 改为 `cuda`、`WHISPER_COMPUTE_TYPE` 改为 `float16` 或 `int8_float16`。Windows 上还需要先执行 `conda env update -n vidferry -f environment.gpu-win.yml`，以在当前 Conda 环境安装 CUDA 12 的 cuBLAS/cuDNN 运行库。缺少这些运行库时，GPU 转写会被阻止，并在右上角消息中给出修复指引；可改为 `WHISPER_DEVICE=cpu` 后重启。资源不足时保持默认 `small`。修改 `.env` 后需要重启后端；已有转写缓存会被复用，不会因为切换模型自动重新转写。

国内网络如果无法直接访问 Hugging Face，可以使用 HF-Mirror 预下载模型。以当前默认 `small` 为例：

```powershell
conda activate vidferry
python -m pip install -U huggingface_hub
$env:HF_ENDPOINT="https://hf-mirror.com"
huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
```

然后在 `.env` 中指定本地模型目录：

```env
WHISPER_MODEL_SIZE=./models/faster-whisper-small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

如果只是想让首次运行自动走国内镜像，而不是提前下载，也可以在 `.env` 中配置：

```env
HF_ENDPOINT=https://hf-mirror.com
HF_HOME=./models/huggingface
WHISPER_MODEL_SIZE=small
```

CPU 可以运行 `tiny`、`base`、`small`，但长视频会比较慢；普通电脑优先用 `small` 或 `base`，显卡和内存充足时再考虑 `medium` 或 `large-v3`。

### deep-translator

字幕翻译依赖 `deep-translator`，会随 Python 依赖安装。它不需要额外下载二进制文件，但翻译效果和稳定性会受网络、目标翻译服务可用性影响。

### social-auto-upload

本项目参考并复用了 `social-auto-upload` 的多平台自动化发布思路和部分能力。当前 Vidferry 代码已在本仓库内维护，不需要额外再下载另一个 `social-auto-upload` 仓库。

## 常见问题

### 后端启动失败：缺少 flask_cors

说明 Web 依赖没有安装完整。先激活后端环境，再补装 Web 依赖：

```powershell
conda activate vidferry
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
- YouTube 页面需要 JS runtime 或 EJS 组件首次下载。
- 视频本身不可下载或受地区、年龄、版权限制。

可尝试：

```powershell
conda activate vidferry
python -m pip install -U yt-dlp
```

确认已安装 Node.js 20+，并在 `.env` 中保留 `YTDLP_REMOTE_COMPONENTS=ejs:github`；首次下载需要能访问 GitHub 以获取 EJS 组件。

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

### LLM / 内容分析报错

- `Remote end closed connection without response`：通常是请求被 LLM API 远端识别为异常。先检查 VPN/代理是否异常；若仍出现，尝试关闭 VPN 后重试（DashScope 为国内服务，关闭 VPN 通常不影响）。

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
- 飞书 App Secret 只保存在本机 `.env`；机器人只允许 `FEISHU_ALLOWED_OPEN_IDS` 中的用户调用 Agent。

## 项目状态

- 当前定位：本地优先、单机工作流、开发验证。
- 当前重点：稳定视频采集、下载、字幕处理、内容分析、视频素材管理和发布准备链路。
- 数据库：PostgreSQL 是唯一运行数据库；首次部署按 [QUICK_DEPLOYMENT.md](QUICK_DEPLOYMENT.md) 启动本地数据库服务。
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

### 飞书项目管家

飞书机器人支持“现在有什么要处理”“为什么失败”“账号是否正常”“下一步怎么做”等只读项目管家查询，不会主动发送提醒。完整配置和验收见 [项目管家说明](docs/PROJECT_BUTLER.md)。

## License

MIT License
