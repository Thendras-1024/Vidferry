"""YouTube 视频线索分组 API。"""


@app.route('/youtube/video-groups', methods=['GET'])
def youtube_video_groups_route():
    try:
        return _json_response(data=list_youtube_video_groups(_current_account_owner_id()))
    except Exception as exc:
        return _json_response(500, f"获取视频分组失败: {str(exc)}", None, 500)


@app.route('/youtube/video-groups', methods=['POST'])
def create_youtube_video_group_route():
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=create_youtube_video_group(payload.get("name"), _current_account_owner_id()))
    except ValueError as exc:
        status = 409 if "已存在" in str(exc) else 400
        return _json_response(status, str(exc), None, status)
    except Exception as exc:
        return _json_response(500, f"创建视频分组失败: {str(exc)}", None, 500)


@app.route('/youtube/video-groups/<int:group_id>', methods=['PATCH'])
def rename_youtube_video_group_route(group_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=rename_youtube_video_group(group_id, payload.get("name"), _current_account_owner_id()))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except ValueError as exc:
        status = 409 if "已存在" in str(exc) or "默认分组" in str(exc) else 400
        return _json_response(status, str(exc), None, status)
    except Exception as exc:
        return _json_response(500, f"重命名视频分组失败: {str(exc)}", None, 500)


@app.route('/youtube/video-groups/<int:group_id>', methods=['DELETE'])
def delete_youtube_video_group_route(group_id):
    try:
        return _json_response(data=delete_youtube_video_group(group_id, _current_account_owner_id()))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except (ValueError, RuntimeError) as exc:
        return _json_response(409, str(exc), None, 409)
    except Exception as exc:
        return _json_response(500, f"删除视频分组失败: {str(exc)}", None, 500)


@app.route('/youtube/videos/group', methods=['PATCH'])
def move_youtube_videos_to_group_route():
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=move_youtube_videos_to_group(payload.get("videoIds"), payload.get("groupId"), _current_account_owner_id()))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception as exc:
        return _json_response(500, f"移动视频分组失败: {str(exc)}", None, 500)
