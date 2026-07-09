def _get_youtube_video_record(video_id):
    if not video_id:
        return None
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return _row_to_youtube_video(row) if row else None


def _resolve_downloaded_source_file(job):
    record = _get_youtube_video_record(job.get("videoId"))
    downloaded_path = Path((record or {}).get("downloadedFilePath") or "")
    if downloaded_path.is_file():
        return downloaded_path

    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = ? AND source_type = 'youtube_download'
        ORDER BY upload_time DESC, id DESC
        LIMIT 1
        ''', (job.get("videoId") or "",))
        material = cursor.fetchone()
        if material:
            material_path = _material_file_path(dict(material))
            if material_path and material_path.is_file():
                return material_path

    raise RuntimeError("未找到已下载视频文件，请先执行下载。")


def _workflow_error_fields(exc):
    if exc.__class__.__name__ == "LLMJsonParseError":
        return {
            "error_code": "VF-LLM-JSON-INVALID",
            "error_type": "LLM_JSON_PARSE_ERROR",
            "error_reason": "模型返回的发布文案 JSON 格式不合法，系统已尝试自动修复但仍失败。",
            "error_detail": getattr(exc, "detail", "") or str(exc),
        }
    return {
        "error_code": "VF-WORKFLOW-FAILED",
        "error_type": exc.__class__.__name__,
        "error_reason": str(exc),
        "error_detail": "",
    }


def run_youtube_download_job(job_id):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
        source_file = _download_youtube_video(job)
        finish_workflow_event(event_id, "success", "下载完成", output_file_path=source_file)
        material = _register_downloaded_video_material(source_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="下载完成，已绑定到素材库",
            source_file_path=str(source_file),
            processed_file_path=str(source_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        error_fields = _workflow_error_fields(exc)
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            **error_fields,
            speed="",
            eta="",
        )


def run_youtube_translate_job(job_id):
    event_id = None
    analysis_event_id = None
    editing_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle",
            message=f"正在准备{language_meta['label']}字幕处理任务",
            progress=2,
            speed="",
            eta="",
        )
        source_file = _resolve_downloaded_source_file(job)

        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="处理版本二：正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在启动转写和处理",
            step="subtitle",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 5,
        )
        subtitle_result = _process_subtitles(job, source_file)
        if process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )
        final_message = "未检测到可识别人声，已跳过字幕处理并保存到素材库" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库"
        if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
            final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
        elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
            final_message = f"{final_message}；未找到可拼接的高光片段"
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            processed_file_path=str(processed_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(editing_event_id or event_id or analysis_event_id, "failed", str(exc))
        error_fields = _workflow_error_fields(exc)
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            **error_fields,
            speed="",
            eta="",
        )


def run_youtube_analysis_job(job_id, source_file_override=""):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="analysis",
            message="正在准备处理版本二剪辑方案",
            progress=4,
            speed="",
            eta="",
        )
        source_file = Path(source_file_override) if source_file_override else _resolve_downloaded_source_file(job)
        event_id = start_workflow_event(job, "analysis", "开始生成发布文案与内容总结", input_file_path=source_file)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在复用转写文本分析内容",
            progress=8,
        )
        result, usage = _run_analysis_from_transcript_job(job, source_file)
        finish_workflow_event(
            event_id,
            "success",
            "发布文案与内容总结已生成",
            cloud_usage={
                "provider": usage.get("provider") or "openai-compatible",
                "model": usage.get("model") or LLM_MODEL,
                "tokens": int(usage.get("tokens") or 0),
                "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                "promptTokens": int(usage.get("promptTokens") or 0),
                "completionTokens": int(usage.get("completionTokens") or 0),
                "latencyMs": float(usage.get("latencyMs") or 0),
            },
            metadata={"highlightCount": len(result.get("highlight_segments") or [])},
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="发布文案与内容总结已生成，可在视频线索中查看",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        try:
            failed_job = get_youtube_workflow_job(job_id)
            update_youtube_video_analysis_status(failed_job.get("videoId"), 3, _analysis_error_payload(exc, failed_job))
        except Exception as status_exc:
            print(f"更新分析失败状态失败: {status_exc}")
        error_fields = _workflow_error_fields(exc)
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            **error_fields,
            speed="",
            eta="",
        )


def _publish_workflow_outputs(job_id, job, processed_file, material, workflow_event_id=None, skipped_subtitles=False, editing_result=None):
    latest_job = get_youtube_workflow_job(job_id)
    publish_commands = []
    publish_event_id = start_workflow_event(latest_job, "publish", "开始发布", input_file_path=processed_file)
    publish_specs = [
        (3, latest_job.get("account") or "", _publish_to_douyin),
        (5, latest_job.get("bilibiliAccount") or "", _publish_to_bilibili),
        (1, latest_job.get("xiaohongshuAccount") or "", _publish_to_xiaohongshu),
        (4, latest_job.get("kuaishouAccount") or "", _publish_to_kuaishou),
        (2, latest_job.get("tencentAccount") or "", _publish_to_tencent),
    ]
    for platform_type, account_name, command_factory in publish_specs:
        command = _publish_workflow_platform(latest_job, processed_file, material, platform_type, account_name, command_factory)
        if command:
            publish_commands.append(command)

    final_message = "任务完成"
    if not publish_commands:
        final_message = "任务完成，已保存到素材库，未配置发布平台账号所以未发布"
    process_version = _normalize_process_version(latest_job.get("processVersion"))
    if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
        final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
    elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
        final_message = f"{final_message}；未找到可拼接的高光片段"
    if skipped_subtitles:
        final_message = f"{final_message}；未检测到可识别人声，已跳过字幕处理"

    finish_workflow_event(publish_event_id, "success", final_message, output_file_path=processed_file)
    if workflow_event_id:
        finish_workflow_event(workflow_event_id, "success", final_message, output_file_path=processed_file)
    update_youtube_workflow_job(
        job_id,
        status="success",
        step="done",
        message=final_message,
        publish_command="\n".join(publish_commands),
        progress=100,
        speed="",
        eta="",
    )
    if publish_commands:
        update_youtube_video_artifacts(job["videoId"], publish_status=1)
    return publish_commands


def _processed_material_for_workflow(job):
    record = _get_youtube_video_record(job.get("videoId")) or {}
    processed_path = Path(record.get("processedFilePath") or "")
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        material = _find_latest_processed_material(cursor, job.get("videoId") or "", _normalize_process_version(job.get("processVersion")))
        if not material:
            material = _find_latest_youtube_material(cursor, job.get("videoId") or "", "youtube_processed")
    if material:
        material_path = _material_file_path(material)
        if material_path and material_path.is_file():
            return material_path, _row_to_material(material)
    if processed_path.is_file():
        return processed_path, _save_processed_video_to_material(processed_path, job)
    raise RuntimeError("未找到处理后视频，请先完成处理。")


def _video_has_processed_output(record):
    if not record:
        return False
    translate_status = int(record.get("translateStatus") or 0)
    if translate_status not in (1, 2):
        return False
    processed_path = Path(record.get("processedFilePath") or "")
    if processed_path.is_file():
        return True
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        material = _find_latest_youtube_material(cursor, record.get("id") or record.get("videoId") or "", "youtube_processed")
    if not material:
        return False
    material_path = _material_file_path(material)
    return bool(material_path and material_path.is_file())


def run_youtube_workflow(job_id):
    workflow_event_id = None
    download_event_id = None
    analysis_event_id = None
    editing_event_id = None
    subtitle_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        video_record = _get_youtube_video_record(initial_job.get("videoId")) or {}
        if _video_has_processed_output(video_record):
            job = update_youtube_workflow_job(
                job_id,
                status="running",
                step="publish",
                message="已存在处理后视频，正在直接发布",
                progress=92,
                speed="",
                eta="",
            )
            workflow_event_id = start_workflow_event(job, "workflow", "从待发布状态继续发布")
            processed_file, material = _processed_material_for_workflow(job)
            update_youtube_workflow_job(
                job_id,
                processed_file_path=str(processed_file),
                step="publish",
                message="已复用处理后视频，准备发布",
                progress=96,
                speed="",
                eta="",
            )
            _publish_workflow_outputs(job_id, job, processed_file, material, workflow_event_id=workflow_event_id)
            return

        can_reuse_download = int(video_record.get("downloadStatus") or 0) == 1
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle" if can_reuse_download else "download",
            message="已存在下载视频，正在准备处理" if can_reuse_download else "正在使用 yt-dlp 下载视频",
            progress=4 if can_reuse_download else 0,
            speed="",
            eta="",
        )
        workflow_event_id = start_workflow_event(job, "workflow", "完整工作流开始")
        if can_reuse_download:
            source_file = _resolve_downloaded_source_file(job)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="subtitle",
                message="已复用下载视频，正在准备处理",
                progress=6,
                speed="",
                eta="",
            )
        else:
            download_event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
            source_file = _download_youtube_video(job)
            finish_workflow_event(download_event_id, "success", "下载完成", output_file_path=source_file)
            _register_downloaded_video_material(source_file, job)
            update_youtube_video_artifacts(
                job["videoId"],
                download_status=1,
                downloaded_file_path=str(source_file),
            )

        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="视频已下载，正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message=f"视频已下载，正在处理{language_meta['label']}字幕",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 8,
            speed="",
            eta="",
        )
        subtitle_event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        subtitle_result = _process_subtitles(job, source_file)
        maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(subtitle_event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_workflow_job(
            job_id,
            processed_file_path=str(processed_file),
            step="publish",
            message="未检测到可识别人声，已跳过字幕处理并保存到素材库，准备发布" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库，准备发布",
            progress=96,
            speed="",
            eta="",
        )
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )

        _publish_workflow_outputs(
            job_id,
            job,
            processed_file,
            material,
            workflow_event_id=workflow_event_id,
            skipped_subtitles=skipped_subtitles,
            editing_result=editing_result,
        )
    except Exception as exc:
        finish_workflow_event(editing_event_id or subtitle_event_id or analysis_event_id or download_event_id or workflow_event_id, "failed", str(exc))
        if workflow_event_id:
            finish_workflow_event(workflow_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
        )


