"""管理员维护 Agent Soul 文件。"""

import os as _agent_soul_os
import tempfile as _agent_soul_tempfile
from pathlib import Path as _AgentSoulPath

from flask import g


_AGENT_SOUL_EDITOR_MAX_BYTES = 128 * 1024


def _agent_soul_path():
    return _AgentSoulPath(BASE_DIR).resolve() / "soul.md"


def _read_agent_soul():
    path = _agent_soul_path()
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError) as exc:
        raise ValueError("soul.md 读取失败") from exc


def _write_agent_soul(content):
    content = str(content if content is not None else "")
    encoded = content.encode("utf-8")
    if len(encoded) > _AGENT_SOUL_EDITOR_MAX_BYTES:
        raise ValueError("soul.md 不能超过 128 KB")
    path = _agent_soul_path()
    fd, temp_path = _agent_soul_tempfile.mkstemp(prefix=".soul-", suffix=".tmp", dir=path.parent)
    try:
        with _agent_soul_os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            _agent_soul_os.fsync(handle.fileno())
        _agent_soul_os.replace(temp_path, path)
    except OSError as exc:
        raise ValueError("soul.md 保存失败") from exc
    finally:
        if _agent_soul_os.path.exists(temp_path):
            _agent_soul_os.unlink(temp_path)


@app.route("/admin/agent-soul", methods=["GET"])
def get_agent_soul_route():
    try:
        return _json_response(data={"content": _read_agent_soul()})
    except ValueError as exc:
        return _json_response(500, str(exc), None, 500)


@app.route("/admin/agent-soul", methods=["PUT"])
def update_agent_soul_route():
    try:
        payload = request.get_json(silent=True) or {}
        _write_agent_soul(payload.get("content", ""))
        return _json_response(data={"content": _read_agent_soul()})
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)


@app.route("/admin/youtube/title-translations/backfill", methods=["POST"])
def backfill_youtube_title_translations_route():
    try:
        queued = queue_all_source_title_translations(g.current_user["id"])
        return _json_response(data={"queued": queued})
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception:
        backend_logger.exception("source title translation maintenance failed")
        return _json_response(500, "历史标题补齐任务提交失败", None, 500)
