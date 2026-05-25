from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior

# YouTube -> subtitle -> Douyin workflow settings.
# Videos are downloaded by yt-dlp into YOUTUBE_DOWNLOAD_DIR.
SAU_COMMAND = str(BASE_DIR / ".venv" / "Scripts" / "sau.exe")
FFMPEG_COMMAND = "ffmpeg"
YOUTUBE_DOWNLOAD_DIR = BASE_DIR.parent / "video"
YOUTUBE_PROCESSED_DIR = BASE_DIR / "videos" / "processed"

# Optional subtitle pipeline hook. If empty, the workflow copies the downloaded
# video into the processed folder as a placeholder when ffmpeg is available.
# Required placeholders: {input}, {output}. Optional: {video_id}
SUBTITLE_COMMAND_TEMPLATE = ""
