def _ensure_dir(path):
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _run_command(command, cwd=None, timeout=None):
    is_shell_command = isinstance(command, str)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    result = subprocess.run(
        command,
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=is_shell_command,
        env=env,
    )
    output = "\n".join(part for part in [(result.stdout or "").strip(), (result.stderr or "").strip()] if part)
    if result.returncode != 0:
        display_command = command if is_shell_command else " ".join(command)
        raise RuntimeError(output or f"命令执行失败: {display_command}")
    return result


def _replace_file_with_backup(source_file, output_file):
    source_file = Path(source_file)
    output_file = Path(output_file)
    backup_file = None
    if output_file.exists():
        backup_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_file.exists():
            backup_file.unlink()
        output_file.replace(backup_file)
    try:
        shutil.copy2(source_file, output_file)
        if backup_file and backup_file.exists():
            backup_file.unlink()
    except Exception:
        if output_file.exists():
            output_file.unlink()
        if backup_file and backup_file.exists():
            backup_file.replace(output_file)
        raise
    return output_file


def _replace_output_file(tmp_output_file, output_file):
    tmp_output_file = Path(tmp_output_file)
    output_file = Path(output_file)
    backup_file = None
    if output_file.exists():
        backup_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_file.exists():
            backup_file.unlink()
        output_file.replace(backup_file)
    try:
        tmp_output_file.replace(output_file)
        if backup_file and backup_file.exists():
            backup_file.unlink()
    except Exception:
        if output_file.exists():
            output_file.unlink()
        if backup_file and backup_file.exists():
            backup_file.replace(output_file)
        raise
    return output_file


def _resolve_ffmpeg_command():
    configured = str(FFMPEG_COMMAND or "").strip()
    if configured and (shutil.which(configured) or Path(configured).exists()):
        return configured
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "未找到 FFmpeg。请安装 ffmpeg，或安装 imageio-ffmpeg，或在 conf.py/.env 配置 FFMPEG_COMMAND。"
        ) from exc


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


def _find_newest_video_file(directory, since_timestamp):
    allowed = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv"}
    candidates = [
        path for path in Path(directory).glob("**/*")
        if path.is_file() and path.suffix.lower() in allowed and path.stat().st_mtime >= since_timestamp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


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


