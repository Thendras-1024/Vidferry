"""文件、路径与体积格式化辅助函数。"""

import shutil
from pathlib import Path

from werkzeug.utils import secure_filename

from app.config import BASE_DIR


def _safe_filename(value, default="file"):
    filename = secure_filename(str(value or "").strip())
    return filename or default


def _safe_child_path(base_dir, filename, *, must_exist=False):
    base_path = Path(base_dir).resolve()
    safe_name = _safe_filename(filename)
    candidate = (base_path / safe_name).resolve()
    if not candidate.is_relative_to(base_path):
        raise ValueError("非法文件路径")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError("文件不存在")
    return candidate


def _safe_cookie_filename(value):
    filename = _safe_filename(value, "cookie.json")
    if Path(filename).suffix.lower() != ".json":
        filename = f"{Path(filename).stem or 'cookie'}.json"
    return filename


def _safe_cookie_path(filename, *, must_exist=False):
    return _safe_child_path(BASE_DIR / "cookiesFile", _safe_cookie_filename(filename), must_exist=must_exist)


def _ensure_dir(path):
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


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


def _find_newest_video_file(directory, since_timestamp):
    allowed = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv"}
    candidates = [
        path for path in Path(directory).glob("**/*")
        if path.is_file() and path.suffix.lower() in allowed and path.stat().st_mtime >= since_timestamp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)
