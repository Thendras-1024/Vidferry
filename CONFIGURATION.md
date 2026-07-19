# Vidferry 配置说明

本文件仅在需要配置本机路径、LLM 或 YouTube 下载运行参数时读取。

## FFmpeg

默认使用 PATH 中的 `ffmpeg`：

```python
FFMPEG_COMMAND = "ffmpeg"
```

如果 FFmpeg 没有加入 PATH，可以写绝对路径：

```python
FFMPEG_COMMAND = "D:/tools/ffmpeg/bin/ffmpeg.exe"
```

## Chrome

建议配置本机 Chrome：

```python
LOCAL_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
LOCAL_CHROME_HEADLESS = False
```

`LOCAL_CHROME_HEADLESS = False` 会显示浏览器窗口，适合扫码登录和排查发布流程。

## LLM

内容分析和关键帧审核使用两套独立的 OpenAI-compatible API 配置。DashScope 示例：

```env
TEXT_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TEXT_LLM_API_KEY=sk-your-dashscope-key
TEXT_LLM_MODEL=qwen-plus
MULTIMODAL_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MULTIMODAL_LLM_API_KEY=sk-your-dashscope-key
MULTIMODAL_LLM_MODEL=qwen-vl-max
LLM_TIMEOUT=90
LLM_MAX_TRANSCRIPT_CHARS=28000
```

文本模型未配置时，下载、字幕处理和视频素材管理仍可使用，但内容总结和发布文案生成不可用或会失败。多模态模型未配置且发布前关键帧审核启用时，发布会被阻止。

新变量优先于旧变量。为便于升级，旧的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`AGENT_CHAT_MODEL` 与 `AGENT_VISION_MODEL` 仍会作为迁移回退读取；请在下一次配置维护时改为以上新变量。

## YouTube 下载

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
