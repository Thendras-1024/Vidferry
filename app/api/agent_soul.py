"""用户级 Agent 设置接口。"""

from flask import g


@app.route("/agent/soul", methods=["GET"])
def get_agent_soul_route():
    try:
        return _json_response(data={"content": get_agent_soul(g.current_user["id"])})
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)


@app.route("/agent/soul", methods=["PUT"])
def update_agent_soul_route():
    try:
        payload = request.get_json(silent=True) or {}
        content = update_agent_soul(g.current_user["id"], payload.get("content", ""))
        return _json_response(data={"content": content})
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)


@app.route("/youtube/title-translations/backfill", methods=["POST"])
def backfill_youtube_title_translations_route():
    try:
        queued = queue_all_source_title_translations(g.current_user["id"])
        return _json_response(data={"queued": queued})
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception:
        backend_logger.exception("source title translation maintenance failed")
        return _json_response(500, "历史标题补齐任务提交失败", None, 500)
