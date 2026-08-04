from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # 仅用于小红书相关流程
LOCAL_CHROME_PATH = ""  # 可选,例如 C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = False  # 上传器/示例默认的无头模式行为
DEBUG_MODE = True  # 默认调试行为

# YouTube -> 字幕 -> 抖音 的工作流配置。
# 视频由 yt-dlp 下载到 YOUTUBE_DOWNLOAD_DIR。
# sau 控制台脚本。`pip install -e .` 装好后,激活环境即可直接用 "sau"(走 PATH);
# 也可填绝对路径,例如 "C:/Users/<user>/miniconda3/envs/vidferry/Scripts/sau.exe"。
SAU_COMMAND = "sau"
FFMPEG_COMMAND = "ffmpeg"
YOUTUBE_DOWNLOAD_DIR = BASE_DIR.parent / "video"
YOUTUBE_PROCESSED_DIR = BASE_DIR / "videos" / "processed"
# 可选的字幕处理流水线钩子。为空时,若 ffmpeg 可用,工作流会把下载的视频
# 复制到处理目录作为占位文件。
# 必填占位符:{input}、{output}。可选:{video_id}
SUBTITLE_COMMAND_TEMPLATE = ""
