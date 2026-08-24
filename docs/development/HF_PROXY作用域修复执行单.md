# HF_PROXY 作用域修复执行单

## 目标

将 `HF_PROXY` 从进程级全局代理改为仅影响 YouTube 视频下载使用的 yt-dlp 请求，避免 Google 翻译、LLM 和其他 HTTP 请求意外继承该代理。

本次不回退 `a273fad`，保留当前翻译逻辑中的：

- 单次 Google 翻译请求最多 3 次尝试；
- 批量失败后逐段兜底；
- 当前批量大小、超时和翻译日志。

## 当前问题

当前 [app/config.py](../../app/config.py) 会读取 `HF_PROXY`，并将它写入：

```text
HTTP_PROXY
HTTPS_PROXY
ALL_PROXY
http_proxy
https_proxy
all_proxy
```

这些变量属于整个 Python 进程。`deep-translator` 使用 `requests` 发起 Google 翻译请求，因此 Google 翻译也会继承 `HF_PROXY`。

当前 yt-dlp 的基础配置位于 [app/core/youtube_download_service.py](../../app/core/youtube_download_service.py)，视频下载入口位于 [app/core/subtitle_service.py](../../app/core/subtitle_service.py)。

## 修改方案

### 1. 移除全局代理注入

修改 [app/config.py](../../app/config.py)：

- 保留 `HF_PROXY = _env_text("HF_PROXY")`；
- 删除 `HF_PROXY` 写入所有 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 的代码；
- 不新增任何全局环境变量写入；
- 保留现有 `YTDLP_PROXY` 和系统代理清理逻辑，避免扩大行为变化。

禁止采用以下方案：

```python
YTDLP_PROXY = HF_PROXY
```

原因：`_base_ytdlp_opts()` 同时被 YouTube 搜索、候选分析等功能复用，这样会让 `HF_PROXY` 影响所有 yt-dlp 操作，而不只是视频下载。

### 2. 给 yt-dlp 基础配置增加局部代理参数

修改 [app/core/youtube_download_service.py](../../app/core/youtube_download_service.py) 中的 `_base_ytdlp_opts()`，增加可选参数，例如：

```python
def _base_ytdlp_opts(include_ffmpeg=False, proxy=None):
```

约定：

- 未显式传入 `proxy` 时，保持原行为，使用 `YTDLP_PROXY`；
- 显式传入 `proxy` 时，只在本次 yt-dlp 配置中使用该值；
- 空代理值不应写入有效的代理配置，避免覆盖 yt-dlp 默认行为。

### 3. 仅在 YouTube 视频下载中使用 HF_PROXY

修改 [app/core/subtitle_service.py](../../app/core/subtitle_service.py) 中的 `_download_youtube_video()`：

```python
proxy = YTDLP_PROXY or HF_PROXY
ydl_opts = {
    **_base_ytdlp_opts(proxy=proxy),
    ...
}
```

代理优先级固定为：

```text
YTDLP_PROXY > HF_PROXY > 不设置显式代理
```

这样可以继续兼容已有的 `YTDLP_PROXY` 配置；只有 `YTDLP_PROXY` 为空时，视频下载才使用 `HF_PROXY`。

其他调用 `_base_ytdlp_opts()` 的地方不传入 `HF_PROXY`，因此继续只使用 `YTDLP_PROXY`：

- YouTube 搜索；
- 候选视频分析；
- 其他非视频下载的 yt-dlp 调用。

## 测试要求

### 单元测试

建议新增一个独立测试文件，例如 `tests/test_proxy_scope.py`，至少覆盖：

1. 导入配置后，`HF_PROXY` 不会覆盖进程中的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`。
2. `_base_ytdlp_opts()` 未传代理时只使用 `YTDLP_PROXY`。
3. `_base_ytdlp_opts(proxy=...)` 只在返回的 yt-dlp options 中设置局部代理。
4. `_download_youtube_video()` 在 `YTDLP_PROXY` 为空时使用 `HF_PROXY`。
5. `_download_youtube_video()` 在 `YTDLP_PROXY` 非空时优先使用 `YTDLP_PROXY`。
6. Google 翻译调用不因为 `HF_PROXY` 被写入全局环境而改变。

测试中使用假的 `YoutubeDL` 和假的翻译请求，不输出真实代理地址、API Key、Cookie 或 `.env` 内容。

### 推荐验证命令

在项目根目录执行：

```powershell
git diff --check
E:\miniforge3\envs\vidferry\python.exe -m pytest tests/test_proxy_scope.py tests/test_multilingual_subtitles.py -q
```

如果新增测试文件被 `.gitignore` 忽略，先检查：

```powershell
git check-ignore -v tests/test_proxy_scope.py
```

不要使用 `git add -f`，除非确认该测试文件确实应纳入提交。

## 手工验收

### 配置前提

- `.env` 中保留现有 `HF_PROXY`，不要把真实值写入文档或日志；
- 如已配置 `YTDLP_PROXY`，先记录其是否为空，不要修改为其他地址；
- 不需要启动或重启服务来完成代码检查。

### 验收顺序

1. 使用当前 `HF_PROXY` 重试原视频下载和处理任务。
2. 确认 yt-dlp 下载仍能通过代理完成。
3. 确认字幕翻译阶段不再继承 `HF_PROXY` 的全局环境注入。
4. 观察批量翻译是否仍出现 `TranslationNotFound`。
5. 如果仍失败，记录完整的批次、重试次数和异常类型，再单独判断 Google 服务或代理本身的问题。

### 通过标准

以下条件全部满足才算通过：

- `HF_PROXY` 不再写入全局 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`；
- YouTube 视频下载仍能使用 `HF_PROXY`；
- Google 翻译请求不再自动使用 `HF_PROXY`；
- 已配置 `YTDLP_PROXY` 时，其优先级不变；
- 现有翻译重试和逐段兜底逻辑未被回退；
- 目标测试通过，且 `git diff --check` 无输出。

## 风险与边界

- 移除全局注入后，`HF_PROXY` 不再自动作用于 Whisper / Hugging Face 模型下载。这是本执行单的预期结果，因为本次要求将它的作用范围收缩到 YouTube 视频下载。
- 如果后续仍需要 Hugging Face 模型代理，应新增独立的、只在模型下载调用处使用的局部代理参数，不能恢复进程级环境变量注入。
- 本次不修改 Google 翻译重试策略，不修改 LLM 修订逻辑，不修改数据库或公共 API。
