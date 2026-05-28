@app.route('/youtube/search', methods=['GET'])
def youtube_search():
    query = request.args.get('query') or YOUTUBE_DEFAULT_QUERY
    try:
        limit = int(request.args.get('limit', 8))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 30))

    try:
        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        videos = _search_youtube_with_ytdlp(query, limit)
        source = "yt-dlp"
        if not videos:
            videos = _search_youtube_fallback(query, limit)
            source = "youtube-search-page"
        videos = _dedupe_videos(videos, limit)
        videos = _enrich_videos(videos)
        save_result = save_new_youtube_videos(videos, query)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "query": query,
                "source": source,
                "searchedAt": started_at,
                "total": save_result["created"],
                "created": save_result["created"],
                "duplicate": save_result["duplicate"],
                "publishedDuplicate": save_result.get("publishedDuplicate", 0),
                "requested": save_result["requested"],
                "items": save_result["items"],
            }
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"YouTube 查询失败: {str(e)}",
            "data": None
        }), 500


@app.route('/youtube/videos', methods=['GET'])
def youtube_videos():
    try:
        result = list_youtube_videos(request.args)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": result
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"获取 YouTube 视频记录失败: {str(e)}",
            "data": None
        }), 500


@app.route('/youtube/workflow/settings', methods=['GET'])
def youtube_workflow_settings():
    try:
        return _json_response(data=get_workflow_settings())
    except Exception as e:
        return _json_response(500, f"获取处理设置失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/settings', methods=['PUT', 'PATCH'])
def update_youtube_workflow_settings():
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_workflow_settings(payload))
    except Exception as e:
        return _json_response(500, f"保存处理设置失败: {str(e)}", None, 500)


@app.route('/youtube/videos/import', methods=['POST'])
def import_youtube_video():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "YouTube 链接不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "链接必须是 http 或 https 地址", None, 400)
        if not _extract_youtube_video_id(url):
            return _json_response(400, "请输入有效的 YouTube 视频链接", None, 400)

        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        video = _import_youtube_video_by_url(url)
        save_result = save_new_youtube_videos([video], "manual-url")
        return _json_response(data={
            "query": url,
            "source": "manual-url",
            "searchedAt": started_at,
            "total": save_result["created"],
            "created": save_result["created"],
            "duplicate": save_result["duplicate"],
            "publishedDuplicate": save_result.get("publishedDuplicate", 0),
            "requested": save_result["requested"],
            "items": save_result["items"],
        })
    except Exception as e:
        return _json_response(500, f"导入 YouTube 视频失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/status', methods=['PATCH'])
def youtube_video_status(video_id):
    return jsonify({
        "code": 405,
        "msg": "视频状态由后台任务自动更新，不能手动修改",
        "data": None
    }), 405


@app.route('/youtube/videos/<video_id>/reset-processing', methods=['POST'])
def reset_youtube_video_processing_route(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        result = reset_youtube_video_processing(
            video_id,
            delete_processed=bool(payload.get("deleteProcessed", True)),
            process_version=payload.get("processVersion") or "",
        )
        return _json_response(data=result)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"重置视频处理状态失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['GET'])
def youtube_video_analysis(video_id):
    try:
        return _json_response(data=get_youtube_video_analysis(video_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"获取剪辑方案失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['PATCH'])
def update_youtube_video_analysis(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_analysis_result(video_id, payload))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"更新发布文案失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>/publish-draft', methods=['PATCH'])
def update_youtube_publish_draft(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_publish_draft(video_id, payload))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"更新发布稿失败: {str(e)}", None, 500)


@app.route('/youtube/videos/<video_id>', methods=['DELETE'])
def delete_youtube_video(video_id):
    try:
        return _json_response(data=delete_youtube_video_record(video_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except ValueError as e:
        return _json_response(409, str(e), None, 409)
    except Exception as e:
        return _json_response(500, f"删除视频线索失败: {str(e)}", None, 500)


@app.route('/youtube/videos/batch-delete-items', methods=['POST'])
@app.route('/youtube/videos:batch-delete', methods=['POST'])
def batch_delete_youtube_videos():
    try:
        payload = request.get_json(silent=True) or {}
        video_ids = [
            str(item or "").strip()
            for item in (payload.get("videoIds") or payload.get("ids") or [])
            if str(item or "").strip()
        ]
        if not video_ids:
            return _json_response(400, "请选择要删除的视频线索", None, 400)
        return _json_response(data=delete_youtube_video_records(video_ids))
    except Exception as e:
        return _json_response(500, f"批量删除视频线索失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs', methods=['GET'])
def youtube_workflow_jobs():
    try:
        limit = int(request.args.get("limit", request.args.get("pageSize", 50)))
        limit = max(1, min(limit, 100))
        return _json_response(data=list_youtube_workflow_jobs(limit, request.args))
    except Exception as e:
        return _json_response(500, f"获取工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>', methods=['GET'])
def youtube_workflow_job_detail(job_id):
    try:
        return _json_response(data=get_youtube_workflow_job(job_id))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"获取工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/statistics', methods=['GET'])
def youtube_workflow_statistics():
    try:
        limit = int(request.args.get("limit", 200))
        limit = max(20, min(limit, 1000))
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("pageSize", limit))
        return _json_response(data=get_workflow_statistics(limit, page=page, page_size=page_size))
    except Exception as e:
        return _json_response(500, f"获取工作流统计失败: {str(e)}", None, 500)


@app.route('/youtube/sync/verify-files', methods=['POST'])
def youtube_verify_files():
    try:
        return _json_response(data=verify_youtube_file_consistency())
    except Exception as e:
        return _json_response(500, f"校验视频文件一致性失败: {str(e)}", None, 500)


@app.route('/youtube/workflow/jobs', methods=['POST'])
def create_youtube_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job(payload)
        thread = threading.Thread(target=run_youtube_workflow, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建工作流任务失败: {str(e)}", None, 500)


@app.route('/youtube/download/jobs', methods=['POST'])
def create_youtube_download():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "account": "",
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
        })
        thread = threading.Thread(target=run_youtube_download_job, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建下载任务失败: {str(e)}", None, 500)


@app.route('/youtube/translate/jobs', methods=['POST'])
def create_youtube_translate():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "account": "",
            "publishToDouyin": False,
            "publishToBilibili": False,
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
        })
        thread = threading.Thread(target=run_youtube_translate_job, args=(job["id"],), daemon=True)
        thread.start()
        return _json_response(data=job, status=202)
    except Exception as e:
        return _json_response(500, f"创建处理任务失败: {str(e)}", None, 500)


@app.route('/youtube/analysis/jobs', methods=['POST'])
def create_youtube_analysis():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        if not re.match(r"^https?://", url):
            return _json_response(400, "url 必须是 http 或 https 链接", None, 400)

        existing = get_youtube_video_analysis(payload.get("videoId") or "")
        if int(existing.get("status") or 0) == 1:
            return _json_response(409, "该视频已生成发布文案，可直接查看。", existing, 409)

        force = int(existing.get("status") or 0) == 3
        job = maybe_start_youtube_analysis_job({
            **payload,
            "processVersion": PROCESS_VERSION_EDITING,
        }, force=force)
        if not job:
            return _json_response(409, "该视频已有文案生成任务正在执行。", existing, 409)
        return _json_response(data=job, status=202)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, f"创建剪辑方案任务失败: {str(e)}", None, 500)


@app.route('/youtube/analysis/jobs', methods=['GET'])
def youtube_analysis_jobs():
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 100))
        items = [
            item for item in list_youtube_workflow_jobs(limit).get("items", [])
            if item.get("processVersion") == PROCESS_VERSION_EDITING
        ]
        return _json_response(data={"total": len(items), "items": items})
    except Exception as e:
        return _json_response(500, f"获取剪辑方案任务失败: {str(e)}", None, 500)


