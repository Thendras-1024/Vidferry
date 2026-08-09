"""下载与命令执行基础设施:FFmpeg/yt-dlp 运行时解析、子进程封装、文件安全替换与下载进度回调。"""

from app.utils.ffmpeg_util import _resolve_ffmpeg_command
from app.utils.file_util import (
    _ensure_dir,
    _find_newest_video_file,
    _replace_file_with_backup,
    _replace_output_file,
)
from app.utils.process_util import _run_command


def _resolve_ytdlp_js_runtimes():
    runtime = str(YTDLP_JS_RUNTIME or "").strip().lower()
    runtime_path = str(YTDLP_JS_RUNTIME_PATH or "").strip()
    if runtime:
        config = {}
        if runtime_path:
            config["path"] = runtime_path
        return {runtime: config}

    deno_path = shutil.which("deno")
    if deno_path:
        return {"deno": {"path": deno_path}}

    node_path = shutil.which("node")
    if node_path:
        return {"node": {"path": node_path}}

    return {}


def _base_ytdlp_opts(include_ffmpeg=False):
    opts = {
        "js_runtimes": _resolve_ytdlp_js_runtimes(),
        # Do not inherit unrelated HTTP(S)_PROXY values from the host process.
        # An explicit YTDLP_PROXY keeps proxy use opt-in for YouTube operations.
        "proxy": YTDLP_PROXY,
    }
    if YTDLP_REMOTE_COMPONENTS:
        opts["remote_components"] = list(YTDLP_REMOTE_COMPONENTS)
    if include_ffmpeg:
        opts["ffmpeg_location"] = _resolve_ffmpeg_command()
    return opts


def _render_command_template(template, **values):
    if not template:
        return ""
    return template.format(**values)


def _format_bytes_per_second(value):
    if not value:
        return ""
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
        number /= 1024
    return ""


def _format_eta(seconds):
    if seconds is None:
        return ""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _make_download_progress_hook(job_id):
    last_update = {"time": 0.0}

    def hook(status):
        now = time.time()
        if status.get("status") == "downloading" and now - last_update["time"] < 0.5:
            return
        last_update["time"] = now

        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        downloaded = status.get("downloaded_bytes") or 0
        progress = 0.0
        if total:
            progress = max(0.0, min(99.0, downloaded / total * 100))

        if status.get("status") == "finished":
            progress = 100.0

        message = "正在使用 yt-dlp 下载视频"
        if status.get("status") == "finished":
            message = "视频下载完成，正在写入素材库"

        update_youtube_workflow_job(
            job_id,
            progress=progress,
            speed=_format_bytes_per_second(status.get("speed")),
            eta=_format_eta(status.get("eta")),
            message=message,
        )

    return hook


