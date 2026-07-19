"""YouTube 工作流执行编排:下载/转写/分析/剪辑/发布各阶段的串联与状态流转。"""


from app.core.error_catalog import classify_workflow_exception
from app.core.highlight_review_service import refine_highlight_segments
from app.config import EDITING_ENABLE_HIGHLIGHT_INTRO


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
    return classify_workflow_exception(exc)


def _log_workflow_failure(stage, job_id, exc):
    error_fields = _workflow_error_fields(exc)
    detail = " ".join(str(exc).split())[:500]
    backend_logger.error(
        "%s失败 job_id=%s error_code=%s error_type=%s exception=%s: %s",
        stage, job_id, error_fields["error_code"], error_fields["error_type"], exc.__class__.__name__, detail,
    )
    return error_fields


def _editing_result_message(editing_result):
    result = editing_result or {}
    parts = []
    if result.get("cover"):
        parts.append("已添加封面片头")
    highlight_count = len(result.get("segments") or [])
    if highlight_count:
        parts.append(f"已拼接 {highlight_count} 个高光片段")
    if not parts:
        parts.append(f"未生成片头 : {result.get('reason') or '无可用封面或高光片段'}")
    return "；".join(parts)


def _editing_plan_usage(usage):
    return {
        "provider": usage.get("provider") or "openai-compatible",
        "model": usage.get("model") or TEXT_LLM_MODEL,
        "tokens": int(usage.get("tokens") or 0),
        "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
        "promptTokens": int(usage.get("promptTokens") or 0),
        "completionTokens": int(usage.get("completionTokens") or 0),
        "latencyMs": float(usage.get("latencyMs") or 0),
    }


def _run_editing_plan_analysis(job, source_file, segments, language, transcript_file, event_id):
    try:
        result, usage = _generate_editing_plan(
            job,
            segments,
            build_workflow_llm_telemetry(job, event_id, "analysis"),
        )
        result["_highlightIntroEnabled"] = bool(EDITING_ENABLE_HIGHLIGHT_INTRO)
        if EDITING_ENABLE_HIGHLIGHT_INTRO:
            def report_vision_progress(index, total, remaining_seconds):
                update_youtube_workflow_job(
                    job["id"],
                    step="analysis",
                    message=f"正在审核高光候选 {index}/{total}",
                    progress=88,
                )

            highlights, vision_review = refine_highlight_segments(
                job,
                source_file,
                segments,
                result.get("highlight_segments") or [],
                _max_transcript_seconds(segments),
                progress_callback=report_vision_progress,
                telemetry=build_workflow_llm_telemetry(job, event_id, "analysis"),
            )
            result["highlight_segments"] = highlights
        else:
            vision_review = {"status": "disabled", "reason": "高光拼接开关已关闭"}
        save_youtube_video_analysis(job.get("videoId"), {
            **result,
            "transcriptLanguage": language or "",
            "transcriptFilePath": str(transcript_file),
            "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        finish_workflow_event(
            event_id,
            "success",
            "处理版本二剪辑方案已生成",
            cloud_usage=_editing_plan_usage(usage),
            metadata={
                "highlightCount": len(result.get("highlight_segments") or []),
                "highlightVisionReview": vision_review,
                "generationMeta": result.get("generationMeta") or {},
            },
        )
        if vision_review.get("timedOut"):
            update_youtube_workflow_job(
                job["id"],
                step="analysis",
                message="高光审核超时，已降级为文本候选",
                progress=90,
            )
        elif vision_review.get("status") == "degraded":
            update_youtube_workflow_job(
                job["id"],
                step="analysis",
                message="高光审核不可用，已降级为文本候选",
                progress=90,
            )
        return result
    except Exception as exc:
        finish_workflow_event(event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise


def _start_parallel_editing_plan(job, source_file):
    job_id = job["id"]
    job = update_youtube_workflow_job(
        job_id,
        source_file_path=str(source_file),
        step="subtitle",
        message="处理版本二：正在进行英文语音转写",
        progress=10,
        speed="",
        eta="",
    )
    job = {**job, "_highlightIntroEnabled": bool(EDITING_ENABLE_HIGHLIGHT_INTRO)}
    transcript_event_id = start_workflow_event(job, "transcript", "开始英文语音转写", input_file_path=source_file)
    try:
        segments, language, transcript_file = _prepare_editing_transcript(job, source_file)
    except Exception as exc:
        finish_workflow_event(transcript_event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise
    finish_workflow_event(
        transcript_event_id,
        "success",
        f"英文语音转写完成，识别到 {len(segments)} 段字幕",
        output_file_path=transcript_file,
    )
    analysis_event_id = start_workflow_event(job, "analysis", "开始内容分析与文案生成", input_file_path=transcript_file)
    future = _submit_background_task(
        "analysis",
        _run_editing_plan_analysis,
        job,
        source_file,
        segments,
        language,
        transcript_file,
        analysis_event_id,
    )
    return job, future, analysis_event_id


def _process_subtitles_with_events(job, source_file, language_meta):
    subtitle_event_id = start_workflow_event(
        job,
        "subtitle",
        f"开始{language_meta['label']}翻译与修订",
        input_file_path=source_file,
    )
    burn_event_id = None

    def start_burn_event(ass_file):
        nonlocal burn_event_id
        finish_workflow_event(
            subtitle_event_id,
            "success",
            f"{language_meta['label']}翻译与修订完成",
            output_file_path=ass_file,
        )
        burn_event_id = start_workflow_event(
            job,
            "subtitle_burn",
            f"开始烧制{language_meta['label']}字幕",
            input_file_path=ass_file,
        )

    subtitle_result = _process_subtitles(
        job,
        source_file,
        build_workflow_llm_telemetry(job, subtitle_event_id, "subtitle"),
        before_burn=start_burn_event,
    )
    processed_file = subtitle_result["path"]
    if burn_event_id:
        finish_workflow_event(
            burn_event_id,
            "success",
            f"{language_meta['label']}字幕烧制完成",
            output_file_path=processed_file,
        )
    else:
        finish_workflow_event(
            subtitle_event_id,
            "success",
            f"{language_meta['label']}字幕处理完成",
            output_file_path=processed_file,
        )
    return subtitle_result, subtitle_event_id, burn_event_id


def _prepare_transcript_with_event(job, source_file):
    transcript_event_id = start_workflow_event(job, "transcript", "开始英文语音转写", input_file_path=source_file)
    work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(source_file).stem}_work")
    try:
        segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir)
    except Exception as exc:
        finish_workflow_event(transcript_event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise
    finish_workflow_event(
        transcript_event_id,
        "success",
        f"英文语音转写完成，识别到 {len(segments)} 段字幕",
        output_file_path=transcript_file,
    )
    return transcript_event_id


def run_youtube_download_job(job_id):
    event_id = None
    try:
        job = claim_youtube_workflow_job(
            job_id,
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        if not job:
            return
        backend_logger.info("下载任务开始 job_id=%s video_id=%s", job_id, job.get("videoId", ""))
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
        backend_logger.info("下载任务完成 job_id=%s video_id=%s material_id=%s", job_id, job.get("videoId", ""), material.get("id", ""))
    except Exception as exc:
        error_fields = _log_workflow_failure("下载任务", job_id, exc)
        finish_workflow_event(event_id, "failed", error_fields["error_reason"])
        finish_open_workflow_events(job_id, "failed", error_fields["error_reason"])
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=error_fields["error_reason"],
            **error_fields,
            speed="",
            eta="",
        )


def run_youtube_translate_job(job_id):
    event_id = None
    burn_event_id = None
    transcript_event_id = None
    analysis_event_id = None
    editing_event_id = None
    try:
        initial_job = claim_youtube_workflow_job(
            job_id,
            step="subtitle",
            message="正在准备字幕处理任务",
            progress=2,
            speed="",
            eta="",
        )
        if not initial_job:
            return
        backend_logger.info(
            "字幕处理任务开始 job_id=%s video_id=%s process_version=%s",
            job_id,
            initial_job.get("videoId", ""),
            initial_job.get("processVersion", ""),
        )
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        job = initial_job
        source_file = _resolve_downloaded_source_file(job)

        analysis_result = None
        editing_result = None
        analysis_future = None
        if process_version == PROCESS_VERSION_EDITING:
            job, analysis_future, analysis_event_id = _start_parallel_editing_plan(job, source_file)
        else:
            transcript_event_id = _prepare_transcript_with_event(job, source_file)

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在启动转写和处理",
            step="subtitle",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 5,
        )
        subtitle_result, event_id, burn_event_id = _process_subtitles_with_events(job, source_file, language_meta)
        if process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            analysis_result = analysis_future.result()
            editing_event_id = start_workflow_event(job, "editing", "开始封面片头与高光拼接", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = f"处理版本二 : {_editing_result_message(editing_result)}"
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count, "coverIntro": editing_result.get("cover") or {}},
            )

        if editing_result and editing_result.get("cover"):
            job = {**job, "coverIntro": editing_result["cover"]}
        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )
        final_message = "未检测到可识别人声，已跳过字幕处理并保存到素材库" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库"
        if process_version == PROCESS_VERSION_EDITING and editing_result:
            final_message = f"{final_message}；{_editing_result_message(editing_result)}"
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
        backend_logger.info("字幕处理任务完成 job_id=%s video_id=%s material_id=%s", job_id, job.get("videoId", ""), material.get("id", ""))
    except Exception as exc:
        error_fields = _log_workflow_failure("字幕处理任务", job_id, exc)
        finish_workflow_event(editing_event_id or analysis_event_id or burn_event_id or event_id or transcript_event_id, "failed", error_fields["error_reason"])
        finish_open_workflow_events(job_id, "failed", error_fields["error_reason"])
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=error_fields["error_reason"],
            **error_fields,
            speed="",
            eta="",
        )


def run_youtube_analysis_job(job_id, source_file_override=""):
    event_id = None
    try:
        job = claim_youtube_workflow_job(
            job_id,
            step="analysis",
            message="正在准备处理版本二剪辑方案",
            progress=4,
            speed="",
            eta="",
        )
        if not job:
            return
        backend_logger.info("剪辑方案任务开始 job_id=%s video_id=%s", job_id, job.get("videoId", ""))
        source_file = Path(source_file_override) if source_file_override else _resolve_downloaded_source_file(job)
        event_id = start_workflow_event(job, "analysis", "开始生成发布文案与内容总结", input_file_path=source_file)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在复用转写文本分析内容",
            progress=8,
        )
        result, usage = _run_analysis_from_transcript_job(
            job,
            source_file,
            build_workflow_llm_telemetry(job, event_id, "analysis"),
        )
        finish_workflow_event(
            event_id,
            "success",
            "发布文案与内容总结已生成",
            cloud_usage={
                "provider": usage.get("provider") or "openai-compatible",
                "model": usage.get("model") or TEXT_LLM_MODEL,
                "tokens": int(usage.get("tokens") or 0),
                "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                "promptTokens": int(usage.get("promptTokens") or 0),
                "completionTokens": int(usage.get("completionTokens") or 0),
                "latencyMs": float(usage.get("latencyMs") or 0),
            },
            metadata={
                "highlightCount": len(result.get("highlight_segments") or []),
                "generationMeta": result.get("generationMeta") or {},
            },
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
        backend_logger.info("剪辑方案任务完成 job_id=%s video_id=%s", job_id, job.get("videoId", ""))
    except Exception as exc:
        error_fields = _log_workflow_failure("剪辑方案任务", job_id, exc)
        finish_workflow_event(event_id, "failed", error_fields["error_reason"])
        finish_open_workflow_events(job_id, "failed", error_fields["error_reason"])
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
            message=error_fields["error_reason"],
            **error_fields,
            speed="",
            eta="",
        )


def _publish_workflow_outputs(job_id, job, processed_file, material, workflow_event_id=None, skipped_subtitles=False, editing_result=None):
    latest_job = get_youtube_workflow_job(job_id)
    source_video = _get_youtube_video_record(latest_job.get("videoId")) or {}
    publish_draft = source_video.get("publishDraft") or {}
    publish_job = {**latest_job}
    if publish_draft.get("title"):
        publish_job["title"] = publish_draft["title"]
    if publish_draft.get("description"):
        publish_job["description"] = publish_draft["description"]
    if not publish_job.get("tags") and publish_draft.get("tags"):
        publish_job["tags"] = publish_draft["tags"]
    source_content_risk = get_source_content_risk([material]) or {}
    generated_review_warnings = list((editing_result or {}).get("reviewWarnings") or [])
    requires_confirmation = bool(source_content_risk) or bool(generated_review_warnings)
    if generated_review_warnings:
        source_content_risk = {
            **source_content_risk,
            "requiresPublishConfirmation": True,
            "generatedReviewWarnings": generated_review_warnings,
            "categories": list(dict.fromkeys([
                *(source_content_risk.get("categories") or []), "generated_copy_review",
            ])),
            "message": "生成文案存在待审核表达，视频已处理完成，等待人工确认后发布。",
        }
    if (
        requires_confirmation
        and latest_job.get("publishConfirmationStatus") != "confirmed"
    ):
        waiting_message = source_content_risk.get("message") or "检测到内容待审核项，视频已处理完成，等待人工确认后发布"
        update_youtube_workflow_job(
            job_id,
            status="waiting_confirmation",
            step="publish_confirmation",
            message=waiting_message,
            publish_confirmation_required=1,
            publish_confirmation_status="pending",
            content_risk=source_content_risk,
            progress=96,
            speed="",
            eta="",
        )
        if workflow_event_id:
            finish_workflow_event(
                workflow_event_id,
                "success",
                "视频已处理完成，等待人工确认是否继续发布",
                output_file_path=processed_file,
            )
        return []

    publish_commands = []
    publish_event_id = start_workflow_event(publish_job, "publish", "开始发布", input_file_path=processed_file)
    publish_specs = [
        (3, latest_job.get("account") or "", _publish_to_douyin),
        (5, latest_job.get("bilibiliAccount") or "", _publish_to_bilibili),
        (1, latest_job.get("xiaohongshuAccount") or "", _publish_to_xiaohongshu),
        (4, latest_job.get("kuaishouAccount") or "", _publish_to_kuaishou),
        (2, latest_job.get("tencentAccount") or "", _publish_to_tencent),
    ]
    try:
        for platform_type, account_name, command_factory in publish_specs:
            command = _publish_workflow_platform(publish_job, processed_file, material, platform_type, account_name, command_factory)
            if command:
                publish_commands.append(command)
    except Exception as exc:
        finish_workflow_event(publish_event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise

    final_message = "任务完成"
    if not publish_commands:
        final_message = "任务完成，已保存到素材库，未配置发布平台账号所以未发布"
    process_version = _normalize_process_version(latest_job.get("processVersion"))
    if process_version == PROCESS_VERSION_EDITING and editing_result:
        final_message = f"{final_message}；{_editing_result_message(editing_result)}"
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
    burn_event_id = None
    transcript_event_id = None
    try:
        initial_job = claim_youtube_workflow_job(
            job_id,
            step="workflow",
            message="正在准备完整工作流",
            progress=0,
            speed="",
            eta="",
        )
        if not initial_job:
            return
        backend_logger.info(
            "完整工作流开始 job_id=%s video_id=%s process_version=%s",
            job_id,
            initial_job.get("videoId", ""),
            initial_job.get("processVersion", ""),
        )
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
        analysis_future = None
        if process_version == PROCESS_VERSION_EDITING:
            job, analysis_future, analysis_event_id = _start_parallel_editing_plan(job, source_file)
        else:
            transcript_event_id = _prepare_transcript_with_event(job, source_file)

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message=f"视频已下载，正在处理{language_meta['label']}字幕",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 8,
            speed="",
            eta="",
        )
        subtitle_result, subtitle_event_id, burn_event_id = _process_subtitles_with_events(job, source_file, language_meta)
        if process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            analysis_result = analysis_future.result()
            editing_event_id = start_workflow_event(job, "editing", "开始封面片头与高光拼接", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = f"处理版本二 : {_editing_result_message(editing_result)}"
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count, "coverIntro": editing_result.get("cover") or {}},
            )

        if editing_result and editing_result.get("cover"):
            job = {**job, "coverIntro": editing_result["cover"]}
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
        backend_logger.info("完整工作流完成 job_id=%s video_id=%s", job_id, job.get("videoId", ""))
    except Exception as exc:
        error_fields = _log_workflow_failure("完整工作流", job_id, exc)
        finish_workflow_event(editing_event_id or analysis_event_id or burn_event_id or subtitle_event_id or transcript_event_id or download_event_id or workflow_event_id, "failed", error_fields["error_reason"])
        if workflow_event_id:
            finish_workflow_event(workflow_event_id, "failed", error_fields["error_reason"])
        finish_open_workflow_events(job_id, "failed", error_fields["error_reason"])
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=error_fields["error_reason"],
            **error_fields,
        )


