"""短视频拼接 API。"""

from flask import g, request, send_file

from app.auth.service import record_audit


def _short_video_response(data=None, status=200, message="success"):
    return jsonify({"code": status, "msg": message, "data": data}), status


def _short_video_queue_full_response(exc):
    return _short_video_response({
        "errorCode": exc.error_code,
        "scope": exc.scope,
        "resource": exc.resource,
    }, 429, str(exc))


def _short_video_audit(action, target_type, target_id, details=None):
    record_audit(action, "success", actor_user_id=g.current_user["id"], target_type=target_type,
                 target_id=target_id, details=details, ip_address=request.remote_addr,
                 user_agent=request.user_agent.string)


@app.route("/short-video/projects", methods=["GET"])
def short_video_projects_list():
    return _short_video_response(list_short_video_projects())


@app.route("/short-video/projects", methods=["POST"])
def short_video_projects_create():
    try:
        return _short_video_response(create_short_video_project(request.get_json(silent=True) or {}), 201)
    except ValueError as exc:
        return _short_video_response(None, 400, str(exc))


@app.route("/short-video/projects/<project_id>", methods=["GET"])
def short_video_project_detail(project_id):
    try:
        return _short_video_response(get_short_video_project(project_id))
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))


@app.route("/short-video/projects/<project_id>/search", methods=["POST"])
def short_video_project_search(project_id):
    try:
        get_short_video_project(project_id)
        _set_project_status(project_id, "searching", "正在检索可复用的竖屏候选")
        _submit_background_task("search", run_short_video_search, project_id, _owner_id(), owner_user_id=_owner_id())
        return _short_video_response(get_short_video_project(project_id), 202, "accepted")
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))
    except BackgroundQueueFullError as exc:
        return _short_video_queue_full_response(exc)
    except Exception:
        backend_logger.exception("短视频检索任务提交失败 : project_id = %s", project_id)
        return _short_video_response(None, 500, "短视频检索任务提交失败，请稍后重试")


@app.route("/short-video/projects/<project_id>/candidates", methods=["PUT"])
def short_video_project_candidates_update(project_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _short_video_response(update_short_video_candidates(project_id, payload.get("candidates")))
    except (ValueError, LookupError) as exc:
        return _short_video_response(None, 400, str(exc))


@app.route("/short-video/projects/<project_id>/candidates/<candidate_id>/review", methods=["POST"])
def short_video_candidate_review(project_id, candidate_id):
    try:
        _submit_background_task("analysis", run_short_video_candidate_review, project_id, candidate_id, _owner_id(), owner_user_id=_owner_id())
        return _short_video_response(get_short_video_project(project_id), 202, "accepted")
    except BackgroundQueueFullError as exc:
        return _short_video_queue_full_response(exc)
    except Exception:
        backend_logger.exception(
            "短视频候选审查任务提交失败 : project_id = %s | candidate_id = %s",
            project_id,
            candidate_id,
        )
        return _short_video_response(None, 500, "短视频候选审查任务提交失败，请稍后重试")


@app.route("/short-video/projects/<project_id>/candidates/<candidate_id>/<asset>", methods=["GET"])
def short_video_candidate_asset(project_id, candidate_id, asset):
    try:
        return send_file(short_video_candidate_file(project_id, candidate_id, asset, request.args.get("frame", 0)), conditional=True)
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))


@app.route("/short-video/projects/<project_id>/render", methods=["POST"])
def short_video_project_render(project_id):
    try:
        return _short_video_response(request_short_video_render(project_id, request.get_json(silent=True) or {}), 202, "accepted")
    except (ValueError, LookupError) as exc:
        return _short_video_response(None, 400, str(exc))
    except BackgroundQueueFullError as exc:
        return _short_video_queue_full_response(exc)
    except Exception:
        backend_logger.exception("短视频渲染任务提交失败 : project_id = %s", project_id)
        return _short_video_response(None, 500, "短视频渲染任务提交失败，请稍后重试")


@app.route("/short-video/projects/<project_id>/output", methods=["GET"])
def short_video_project_output(project_id):
    try:
        return send_file(short_video_output_file(project_id), conditional=True)
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))


@app.route("/short-video/bgm", methods=["GET"])
def short_video_bgm_list():
    return _short_video_response(list_short_video_bgm_tracks())


@app.route("/admin/short-video/bgm", methods=["GET", "POST"])
def admin_short_video_bgm():
    if request.method == "GET":
        return _short_video_response(list_short_video_bgm_tracks(enabled_only=False))
    try:
        track = create_short_video_bgm_track(request.files.get("file"), request.form)
        _short_video_audit("SHORT_VIDEO_BGM_CREATE", "short_video_bgm", track["id"], {"title": track["title"]})
        return _short_video_response(track, 201)
    except PermissionError as exc:
        return _short_video_response(None, 403, str(exc))
    except ValueError as exc:
        return _short_video_response(None, 400, str(exc))


@app.route("/admin/short-video/bgm/<int:track_id>", methods=["PATCH"])
def admin_short_video_bgm_update(track_id):
    try:
        track = update_short_video_bgm_track(track_id, request.get_json(silent=True) or {})
        _short_video_audit("SHORT_VIDEO_BGM_UPDATE", "short_video_bgm", track_id, {"enabled": track["enabled"]})
        return _short_video_response(track)
    except PermissionError as exc:
        return _short_video_response(None, 403, str(exc))
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))


@app.route("/admin/short-video/bgm/<int:track_id>", methods=["DELETE"])
def admin_short_video_bgm_delete(track_id):
    try:
        result = delete_short_video_bgm_track(track_id)
        _short_video_audit("SHORT_VIDEO_BGM_DELETE", "short_video_bgm", track_id)
        return _short_video_response(result)
    except PermissionError as exc:
        return _short_video_response(None, 403, str(exc))
    except (LookupError, ValueError) as exc:
        return _short_video_response(None, 400, str(exc))


@app.route("/admin/short-video/channels", methods=["POST"])
def admin_short_video_channel_add():
    try:
        channel = add_short_video_channel_whitelist(request.get_json(silent=True) or {})
        _short_video_audit("SHORT_VIDEO_CHANNEL_CREATE", "short_video_channel", channel["channel"])
        return _short_video_response(channel, 201)
    except PermissionError as exc:
        return _short_video_response(None, 403, str(exc))
    except ValueError as exc:
        return _short_video_response(None, 400, str(exc))


@app.route("/admin/short-video/channels", methods=["GET"])
def admin_short_video_channel_list():
    return _short_video_response(list_short_video_channel_whitelist())


@app.route("/admin/short-video/channels/<int:channel_id>", methods=["DELETE"])
def admin_short_video_channel_delete(channel_id):
    try:
        result = delete_short_video_channel_whitelist(channel_id)
        _short_video_audit("SHORT_VIDEO_CHANNEL_DELETE", "short_video_channel", channel_id)
        return _short_video_response(result)
    except PermissionError as exc:
        return _short_video_response(None, 403, str(exc))
    except LookupError as exc:
        return _short_video_response(None, 404, str(exc))
