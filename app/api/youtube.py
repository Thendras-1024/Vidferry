def _submit_workflow_job(resource, target, job, failure_message):
    try:
        _submit_background_task(resource, target, job["id"], owner_user_id=job["ownerUserId"])
    except Exception as exc:
        queue_error = isinstance(exc, BackgroundQueueFullError)
        update_youtube_workflow_job(
            job["id"],
            status="failed",
            step="abnormal",
            message=failure_message,
            error_code=exc.error_code if queue_error else "VF-WORKFLOW-SUBMIT-FAILED",
            error_type="BACKGROUND_QUEUE_FULL" if queue_error else "BACKGROUND_SUBMIT_FAILED",
            error_reason=failure_message,
            error_detail=str(exc),
        )
        raise


def _background_queue_full_response(exc):
    return _json_response(
        429,
        str(exc),
        {"errorCode": exc.error_code, "scope": exc.scope, "resource": exc.resource},
        429,
    )


def _public_workflow_payload(value):
    return _redact_public_paths(value)


@app.route('/youtube/search', methods=['GET'])
def youtube_search():
    query = (
        request.args.get('query')
        or get_workflow_settings().get("searchQuery")
        or YOUTUBE_DEFAULT_QUERY
    ).strip()
    try:
        limit = int(request.args.get('limit', 8))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 30))
    group_id = request.args.get("groupId")

    try:
        duration_min_seconds, duration_max_seconds = _normalize_duration_range(
            request.args.get("durationMinSeconds"),
            request.args.get("durationMaxSeconds"),
        )
        backend_logger.info("YouTube search started : query = %r | limit = %s", query[:120], limit)
        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        videos = _search_youtube_with_ytdlp(query, limit)
        source = "yt-dlp"
        if not videos:
            videos = _search_youtube_fallback(query, limit)
            source = "youtube-search-page"
        videos = _dedupe_videos(videos, limit)
        videos = _enrich_videos(videos)
        duration_job = {
            "durationMinSeconds": duration_min_seconds,
            "durationMaxSeconds": duration_max_seconds,
        }
        accepted_videos = [video for video in videos if _duration_matches_search_job(video, duration_job)]
        duration_filtered = len(videos) - len(accepted_videos)
        save_result = save_new_youtube_videos(accepted_videos, query, _current_account_owner_id(), group_id)
        backend_logger.info(
            "YouTube search completed : source = %s | created = %s | duplicate = %s | groupId = %s | durationRange = %s-%s",
            source,
            save_result["created"],
            save_result["duplicate"],
            group_id or "default",
            duration_min_seconds if duration_min_seconds is not None else "",
            duration_max_seconds if duration_max_seconds is not None else "",
        )
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
                "requested": limit,
                "durationFiltered": duration_filtered,
                "items": save_result["items"],
            }
        }), 200
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except ValueError as e:
        return _json_response(400, str(e), None, 400)
    except Exception as e:
        backend_logger.exception("YouTube 查询失败")
        return jsonify({
            "code": 500,
            "msg": "YouTube 查询失败，请稍后重试",
            "data": None
        }), 500


@app.route('/youtube/search/jobs', methods=['POST'])
def create_youtube_search_job_route():
    try:
        payload = request.get_json(silent=True) or {}
        query = str(
            (
                payload.get("query")
                or get_workflow_settings().get("searchQuery")
                or YOUTUBE_DEFAULT_QUERY
            )
        ).strip()
        if not query:
            return _json_response(400, "搜索关键词不能为空", None, 400)
        limit = _parse_positive_int(payload.get("limit"), 8, 1, 30)
        job = create_youtube_search_job(
            query,
            limit,
            _current_account_owner_id(),
            payload.get("groupId"),
            payload.get("durationMinSeconds"),
            payload.get("durationMaxSeconds"),
        )
        try:
            _submit_background_task("search", run_youtube_search_job, job["jobId"], owner_user_id=job["ownerUserId"])
        except Exception as submit_error:
            fail_youtube_search_job(job["jobId"], f"查询任务提交失败: {str(submit_error)}")
            raise
        backend_logger.info(
            "YouTube search submitted : jobId = %s | query = %r | limit = %s",
            job["jobId"],
            query[:120],
            limit,
        )
        return _json_response(202, "accepted", job, 202)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except (ValueError, LookupError) as e:
        status = 404 if isinstance(e, LookupError) else 400
        return _json_response(status, str(e), None, status)
    except Exception as e:
        backend_logger.exception("创建 YouTube 查询任务失败")
        return _json_response(500, "创建 YouTube 查询任务失败，请稍后重试", None, 500)


@app.route('/youtube/search/jobs/<job_id>', methods=['GET'])
def get_youtube_search_job_route(job_id):
    try:
        return _json_response(data=get_youtube_search_job(job_id, _current_account_owner_id()))
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        backend_logger.exception("获取 YouTube 查询任务失败")
        return _json_response(500, "获取 YouTube 查询任务失败，请稍后重试", None, 500)


@app.route('/youtube/videos', methods=['GET'])
def youtube_videos():
    try:
        result = list_youtube_videos(request.args, _current_account_owner_id())
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": _redact_public_paths(result)
        }), 200
    except ValueError as e:
        return _json_response(400, str(e), None, 400)
    except Exception as e:
        backend_logger.exception("获取 YouTube 视频记录失败")
        return jsonify({
            "code": 500,
            "msg": "获取 YouTube 视频记录失败，请稍后重试",
            "data": None
        }), 500


@app.route('/youtube/workflow/settings', methods=['GET'])
def youtube_workflow_settings():
    try:
        return _json_response(data=get_workflow_settings())
    except Exception as e:
        backend_logger.exception("获取处理设置失败")
        return _json_response(500, "获取处理设置失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/settings', methods=['PUT', 'PATCH'])
def update_youtube_workflow_settings():
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_workflow_settings(payload))
    except Exception as e:
        backend_logger.exception("保存处理设置失败")
        return _json_response(500, "保存处理设置失败，请稍后重试", None, 500)


@app.route('/youtube/videos/import', methods=['POST'])
def import_youtube_video():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "YouTube 链接不能为空", None, 400)
        try:
            url = _validate_youtube_url(url)
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)

        video_id = _extract_youtube_video_id(url)
        backend_logger.info("YouTube import started : videoId = %s | groupId = %s", video_id, payload.get("groupId") or "default")
        started_at = datetime.datetime.now().isoformat(timespec='seconds')
        video = _import_youtube_video_by_url(url, quick_metadata=True)
        save_result = save_new_youtube_videos([video], "manual-url", _current_account_owner_id(), payload.get("groupId"))
        backend_logger.info(
            "YouTube import completed : videoId = %s | groupId = %s | created = %s | duplicate = %s",
            video_id,
            payload.get("groupId") or "default",
            save_result["created"],
            save_result["duplicate"],
        )
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
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except ValueError as e:
        return _json_response(400, str(e), None, 400)
    except Exception as e:
        backend_logger.exception("YouTube 单链接导入失败")
        return _json_response(500, "导入 YouTube 视频失败，请稍后重试", None, 500)


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
        backend_logger.info(
            "重新处理重置开始 video_id=%s process_version=%s refresh_transcript=%s",
            video_id,
            payload.get("processVersion") or "",
            bool(payload.get("refreshTranscript", False)),
        )
        result = reset_youtube_video_processing(
            video_id,
            _current_account_owner_id(),
            delete_processed=bool(payload.get("deleteProcessed", True)),
            process_version=payload.get("processVersion") or "",
            refresh_transcript=bool(payload.get("refreshTranscript", False)),
        )
        backend_logger.info(
            "重新处理重置完成 video_id=%s deleted_materials=%s deleted_jobs=%s",
            video_id,
            result.get("deletedMaterialCount", 0),
            result.get("deletedWorkflowJobCount", 0),
        )
        return _json_response(data=result)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        backend_logger.exception("重新处理重置失败 video_id=%s", video_id)
        return _json_response(500, "重置视频处理状态失败，请稍后重试", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['GET'])
def youtube_video_analysis(video_id):
    try:
        return _json_response(data=get_youtube_video_analysis(video_id, _current_account_owner_id()))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, "获取剪辑方案失败，请稍后重试", None, 500)


@app.route('/youtube/videos/<video_id>/analysis', methods=['PATCH'])
def update_youtube_video_analysis(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_analysis_result(video_id, payload, _current_account_owner_id()))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, "更新发布文案失败，请稍后重试", None, 500)


@app.route('/youtube/videos/<video_id>/publish-draft', methods=['PATCH'])
def update_youtube_publish_draft(video_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_youtube_video_publish_draft(video_id, payload, _current_account_owner_id()))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, "更新发布稿失败，请稍后重试", None, 500)


@app.route('/youtube/videos/<video_id>', methods=['DELETE'])
def delete_youtube_video(video_id):
    try:
        return _json_response(data=delete_youtube_video_record(video_id, _current_account_owner_id()))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except ValueError as e:
        return _json_response(409, str(e), None, 409)
    except Exception as e:
        return _json_response(500, "删除视频线索失败，请稍后重试", None, 500)


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
        return _json_response(data=delete_youtube_video_records(video_ids, _current_account_owner_id()))
    except Exception as e:
        return _json_response(500, "批量删除视频线索失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs', methods=['GET'])
def youtube_workflow_jobs():
    try:
        limit = int(request.args.get("limit", request.args.get("pageSize", 50)))
        limit = max(1, min(limit, 100))
        return _json_response(data=_public_workflow_payload(list_youtube_workflow_jobs(limit, request.args, _current_account_owner_id())))
    except Exception as e:
        return _json_response(500, "获取工作流任务失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>', methods=['GET'])
def youtube_workflow_job_detail(job_id):
    try:
        return _json_response(data=_public_workflow_payload(get_youtube_workflow_job(job_id, _current_account_owner_id())))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        return _json_response(500, "获取工作流任务失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>/publish-confirmation', methods=['POST'])
def confirm_youtube_workflow_publish(job_id):
    try:
        payload = request.get_json(silent=True) or {}
        confirmed = payload.get("confirmed")
        if not isinstance(confirmed, bool):
            return _json_response(400, "confirmed 必须是 true 或 false", None, 400)
        job = resolve_youtube_workflow_publish_confirmation(job_id, confirmed, _current_account_owner_id())
        if confirmed:
            _submit_workflow_job(workflow_job_resource(job), run_youtube_workflow, job, "发布确认后的后台任务提交失败")
            return _json_response(data=_public_workflow_payload(job), status=202)
        return _json_response(data=_public_workflow_payload(job))
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except Exception as e:
        backend_logger.exception("处理发布确认失败 : job_id = %s", job_id)
        return _json_response(500, "处理发布确认失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>/content-safety-confirmation', methods=['POST'])
def confirm_youtube_workflow_content_safety(job_id):
    try:
        payload = request.get_json(silent=True) or {}
        job = resolve_content_safety_confirmation(
            job_id,
            payload.get("decision"),
            payload.get("ranges"),
            payload.get("reason"),
            _current_account_owner_id(),
        )
        target = run_youtube_workflow if any(job.get(key) for key in ("publishToDouyin", "publishToBilibili", "publishToXiaohongshu", "publishToKuaishou", "publishToTencent")) else run_youtube_translate_job
        _submit_workflow_job("processing", target, job, "视频处理确认后的后台任务提交失败")
        backend_logger.info("content safety confirmation accepted : job_id = %s | decision = %s", job_id, payload.get("decision") or "")
        return _json_response(data=_public_workflow_payload(job), status=202)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except (ValueError, WorkflowConflictError) as e:
        return _error_response(409 if isinstance(e, WorkflowConflictError) else 400, str(e), getattr(e, "error_code", None), getattr(e, "error_type", None), getattr(e, "data", None))
    except Exception as e:
        backend_logger.exception("处理视频裁剪确认失败 : job_id = %s", job_id)
        return _json_response(500, "处理视频裁剪确认失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs/<job_id>/source-preview', methods=['GET'])
def youtube_workflow_source_preview(job_id):
    try:
        job = get_youtube_workflow_job(job_id, _current_account_owner_id())
        source_file = Path(job.get("sourceFilePath") or "")
        if not source_file.is_file():
            return _json_response(404, "未找到本地源视频", None, 404)
        source_root = Path(YOUTUBE_DOWNLOAD_DIR).resolve()
        if not source_file.resolve().is_relative_to(source_root):
            return _json_response(403, "源视频路径无效", None, 403)
        return send_from_directory(str(source_file.parent), source_file.name, conditional=True)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except Exception as e:
        backend_logger.exception("读取本地源视频失败 : job_id = %s", job_id)
        return _json_response(500, "读取本地源视频失败", None, 500)


@app.route('/youtube/workflow/statistics', methods=['GET'])
def youtube_workflow_statistics():
    try:
        limit = int(request.args.get("limit", 200))
        limit = max(20, min(limit, 1000))
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("pageSize", limit))
        return _json_response(data=get_workflow_statistics(
            limit,
            page=page,
            page_size=page_size,
            date_from=request.args.get("dateFrom"),
            date_to=request.args.get("dateTo"),
            granularity=request.args.get("granularity", "auto"),
            owner_user_id=_current_account_owner_id(),
        ))
    except Exception as e:
        return _json_response(500, "获取工作流统计失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/statistics/tasks/<job_id>', methods=['GET'])
def youtube_workflow_task_statistics(job_id):
    try:
        detail = get_workflow_task_statistics(job_id, _current_account_owner_id())
        if not detail:
            return _json_response(404, "处理任务不存在", None, 404)
        return _json_response(data=detail)
    except Exception as e:
        return _json_response(500, "获取任务统计详情失败，请稍后重试", None, 500)


@app.route('/youtube/sync/verify-files', methods=['POST'])
def youtube_verify_files():
    try:
        return _json_response(data=verify_youtube_file_consistency(_current_account_owner_id()))
    except Exception as e:
        return _json_response(500, "校验视频文件一致性失败，请稍后重试", None, 500)


@app.route('/youtube/workflow/jobs', methods=['POST'])
def create_youtube_workflow():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        try:
            payload["url"] = _validate_youtube_url(url)
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)

        if payload.get("publishToDouyin") and payload.get("account"):
            _check_named_publish_account(3, payload.get("account"))
        if payload.get("publishToBilibili") and payload.get("bilibiliAccount"):
            _check_named_publish_account(5, payload.get("bilibiliAccount"))
        if payload.get("publishToXiaohongshu") and payload.get("xiaohongshuAccount"):
            _check_named_publish_account(1, payload.get("xiaohongshuAccount"))
        if payload.get("publishToKuaishou") and payload.get("kuaishouAccount"):
            _check_named_publish_account(4, payload.get("kuaishouAccount"))
        if payload.get("publishToTencent") and payload.get("tencentAccount"):
            _check_named_publish_account(2, payload.get("tencentAccount"))
        payload["ownerUserId"] = _current_account_owner_id()
        job = create_youtube_workflow_job(payload)
        resource = workflow_job_resource(job)
        _submit_workflow_job(resource, run_youtube_workflow, job, "完整工作流提交失败")
        backend_logger.info(
            "完整工作流已提交 job_id=%s video_id=%s process_version=%s resource=%s",
            job["id"],
            job.get("videoId", ""),
            job.get("processVersion", ""),
            resource,
        )
        return _json_response(data=_public_workflow_payload(job), status=202)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        existing_job = (e.data or {}).get("job") if e.error_type == "ACTIVE_JOB_LOCK" else None
        if existing_job and existing_job.get("status") in _WORKFLOW_ACTIVE_STATUSES:
            return _json_response(data=_public_workflow_payload({**existing_job, "reused": True}), status=202)
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except Exception as e:
        backend_logger.exception("创建完整工作流失败")
        return _json_response(500, "创建工作流任务失败，请稍后重试", None, 500)


@app.route('/youtube/download/jobs', methods=['POST'])
def create_youtube_download():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        try:
            payload["url"] = _validate_youtube_url(url)
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "ownerUserId": _current_account_owner_id(),
            "account": "",
            "publishToDouyin": False,
            "publishToBilibili": False,
            "publishToXiaohongshu": False,
            "publishToKuaishou": False,
            "publishToTencent": False,
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
            "processVersion": PROCESS_VERSION_TRANSLATION,
            "subtitleMode": "original",
            "translationEnabled": False,
            "highlightIntroEnabled": False,
            "coverIntroEnabled": False,
            "commentBurnEnabled": False,
            "watermarkEnabled": False,
            "watermarkText": "",
            "contentSafetyReviewEnabled": False,
        })
        _submit_workflow_job("download", run_youtube_download_job, job, "下载任务提交失败")
        backend_logger.info("下载任务已提交 job_id=%s video_id=%s", job["id"], job.get("videoId", ""))
        return _json_response(data=_public_workflow_payload(job), status=202)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except Exception as e:
        backend_logger.exception("创建下载任务失败")
        return _json_response(500, "创建下载任务失败，请稍后重试", None, 500)


@app.route('/youtube/translate/jobs', methods=['POST'])
def create_youtube_translate():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        try:
            payload["url"] = _validate_youtube_url(url)
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)

        job = create_youtube_workflow_job({
            **payload,
            "ownerUserId": _current_account_owner_id(),
            "account": "",
            "publishToDouyin": False,
            "publishToBilibili": False,
            "publishToXiaohongshu": False,
            "publishToKuaishou": False,
            "publishToTencent": False,
            "description": payload.get("description") or "",
            "tags": payload.get("tags") or [],
            "schedule": "",
        })
        _submit_workflow_job("processing", run_youtube_translate_job, job, "字幕处理任务提交失败")
        backend_logger.info(
            "字幕处理任务已提交 job_id=%s video_id=%s process_version=%s",
            job["id"],
            job.get("videoId", ""),
            job.get("processVersion", ""),
        )
        return _json_response(data=_public_workflow_payload(job), status=202)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except Exception as e:
        backend_logger.exception("创建字幕处理任务失败")
        return _json_response(500, "创建处理任务失败，请稍后重试", None, 500)


@app.route('/youtube/analysis/jobs', methods=['POST'])
def create_youtube_analysis():
    try:
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return _json_response(400, "url 不能为空", None, 400)
        try:
            payload["url"] = _validate_youtube_url(url)
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)

        existing = get_youtube_video_analysis(payload.get("videoId") or "", _current_account_owner_id())
        force_requested = payload.get("force") is True
        if int(existing.get("status") or 0) == 1 and not force_requested:
            return _json_response(409, "该视频已生成发布文案，可直接查看。", existing, 409)

        force = force_requested or int(existing.get("status") or 0) == 3
        job = maybe_start_youtube_analysis_job({
            **payload,
            "ownerUserId": _current_account_owner_id(),
            "processVersion": PROCESS_VERSION_EDITING,
        }, force=force)
        if not job:
            return _json_response(409, "该视频已有文案生成任务正在执行。", existing, 409)
        backend_logger.info(
            "analysis job submitted : jobId = %s | videoId = %s | force = %s",
            job["id"],
            job.get("videoId", ""),
            force_requested,
        )
        return _json_response(data=_public_workflow_payload(job), status=202)
    except LookupError as e:
        return _json_response(404, str(e), None, 404)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except Exception as e:
        backend_logger.exception("创建剪辑方案任务失败")
        return _json_response(500, "创建剪辑方案任务失败，请稍后重试", None, 500)


@app.route('/youtube/editing/intro/jobs', methods=['POST'])
def create_youtube_editing_intro_job():
    try:
        payload = request.get_json(silent=True) or {}
        if not (payload.get("url") or "").strip() or not payload.get("videoId"):
            return _json_response(400, "videoId 和 url 不能为空", None, 400)
        try:
            payload["url"] = _validate_youtube_url(payload["url"])
        except ValueError as exc:
            return _json_response(400, str(exc), None, 400)
        job = create_youtube_workflow_job({
            **payload,
            "ownerUserId": _current_account_owner_id(),
            "operation": "cover_reburn" if payload.get("operation") == "cover_reburn" else "intro_refresh",
            "account": "", "publishToDouyin": False, "publishToBilibili": False,
            "publishToXiaohongshu": False, "publishToKuaishou": False, "publishToTencent": False,
            "description": "", "tags": payload.get("tags") or [], "schedule": "",
        })
        task_label = "封面重烧" if job.get("operation") == "cover_reburn" else "片头高光更新"
        _submit_workflow_job("processing", run_youtube_update_editing_intro_job, job, f"{task_label}任务提交失败")
        backend_logger.info("%s任务已提交 : job_id = %s | video_id = %s", task_label, job["id"], job.get("videoId", ""))
        return _json_response(data=_public_workflow_payload(job), status=202)
    except BackgroundQueueFullError as e:
        return _background_queue_full_response(e)
    except WorkflowConflictError as e:
        return _error_response(409, str(e), e.error_code, e.error_type, e.data)
    except Exception as e:
        backend_logger.exception("创建片头高光更新任务失败")
        return _json_response(500, "创建片头高光更新任务失败，请稍后重试", None, 500)


@app.route('/youtube/analysis/jobs', methods=['GET'])
def youtube_analysis_jobs():
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 100))
        items = [
            item for item in list_youtube_workflow_jobs(limit, owner_user_id=_current_account_owner_id()).get("items", [])
            if item.get("processVersion") == PROCESS_VERSION_EDITING
        ]
        return _json_response(data=_public_workflow_payload({"total": len(items), "items": items}))
    except Exception as e:
        return _json_response(500, "获取剪辑方案任务失败，请稍后重试", None, 500)


