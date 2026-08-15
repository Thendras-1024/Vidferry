"""YouTube 工作流执行编排:下载/转写/分析/剪辑/发布各阶段的串联与状态流转。"""

import datetime as _datetime

from app.core.error_catalog import classify_workflow_exception
from app.core.highlight_review_service import refine_highlight_segments
from app.core.source_subtitle_service import analyze_source_subtitles


def _get_youtube_video_record(video_id):
    if not video_id:
        return None
    init_youtube_video_table()
    with _db_connect() as conn:
        conn.row_factory = True
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
        conn.row_factory = True
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


def _resolve_source_subtitle_processing(job, source_file):
    mode = str(job.get("subtitleMode") or "legacy")
    existing = job.get("sourceSubtitleAnalysis") or {}
    analysis = existing if existing.get("decision") else None
    usage = {}
    event_id = start_workflow_event(job, "source_subtitle_analysis", "正在识别原视频字幕", input_file_path=source_file)
    if analysis is None:
        video_info = _get_video_info(source_file)
        analysis, usage = analyze_source_subtitles(
            job,
            source_file,
            video_info.get("duration") or 0,
            build_workflow_llm_telemetry(job, event_id, "source_subtitle_analysis"),
        )
    decision = analysis.get("decision")
    if mode == "legacy" or not isinstance(decision, dict):
        translation_enabled = bool(job.get("translationEnabled", True))
        subtitle_mask_enabled = bool(job.get("subtitleMaskEnabled"))
    else:
        translation_enabled = bool(decision.get("translationEnabled"))
        subtitle_mask_enabled = bool(decision.get("subtitleMaskEnabled"))
    updated = update_youtube_workflow_job(
        job["id"],
        translation_enabled=int(translation_enabled),
        subtitle_mask_enabled=int(subtitle_mask_enabled),
        source_subtitle_analysis=analysis,
    )
    classification = analysis.get("classification") or "unknown"
    finish_workflow_event(
        event_id,
        "success",
        "原视频字幕识别完成" if analysis.get("status") == "success" else "原视频字幕识别已按降级策略处理",
        cloud_usage=_editing_plan_usage(usage) if usage else {},
        metadata={
            "status": analysis.get("status") or "unknown",
            "classification": classification,
            "effectiveAction": (decision or {}).get("effectiveAction") or "legacy",
            "region": analysis.get("region"),
        },
    )
    return updated


def _ensure_workflow_publish_schedule(job_id, job):
    """Keep a platform-scheduled publish far enough in the future after processing."""
    raw_schedule = str((job or {}).get("schedule") or "").strip()
    if not raw_schedule:
        return job, ""
    scheduled = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            scheduled = _datetime.datetime.strptime(raw_schedule, fmt)
            break
        except ValueError:
            continue
    if not scheduled:
        return job, ""
    minimum = (_datetime.datetime.now() + _datetime.timedelta(minutes=125)).replace(second=0, microsecond=0)
    if scheduled >= minimum:
        return job, ""
    adjusted = minimum.strftime("%Y-%m-%d %H:%M:%S")
    notice = f"处理完成时原定发布时间已不足平台要求的 2 小时，已自动顺延至 {adjusted}。"
    update_youtube_workflow_job(job_id, schedule=adjusted, message=notice)
    return {**job, "schedule": adjusted}, notice


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
    if result.get("highlightWarning"):
        parts.append(str(result["highlightWarning"]))
    return "；".join(parts)


def _subtitle_skip_reason(subtitle_result):
    return "已按设置跳过字幕翻译和烧录" if subtitle_result.get("skippedBySetting") else "未检测到可识别人声，已跳过字幕处理"


def _source_title_translation_from_events(video_id):
    if not video_id:
        return ""
    with _db_connect() as conn:
        conn.row_factory = True
        rows = conn.execute('''
        SELECT metadata FROM youtube_workflow_events
        WHERE video_id = ? AND stage = 'source_title_translation' AND status = 'success'
        ORDER BY ended_at DESC, id DESC
        LIMIT 10
        ''', (video_id,)).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, ValueError):
            continue
        title = str(metadata.get("sourceTitleZh") or "").strip()
        if title:
            return title
    return ""


def _ensure_source_title_translation(job):
    source_title = str(job.get("title") or "").strip()
    if not source_title:
        return ""
    cached = _source_title_translation_from_events(job.get("videoId") or "")
    event_id = start_workflow_event(job, "source_title_translation", "正在翻译原视频标题")
    if cached:
        finish_workflow_event(event_id, "success", "已复用原视频标题翻译", metadata={"sourceTitleZh": cached, "sourceTitleTranslationStatus": "success", "cached": True})
        return cached
    try:
        translated = _translate_segments([{"text": source_title}], "zh-CN")
        title = str((translated[0] if translated else {}).get("subtitle") or "").strip()
        if not title:
            raise RuntimeError("原视频标题翻译结果为空")
        finish_workflow_event(event_id, "success", "原视频标题翻译完成", metadata={"sourceTitleZh": title, "sourceTitleTranslationStatus": "success"})
        return title
    except Exception as exc:
        finish_workflow_event(event_id, "failed", f"原视频标题翻译未生成: {exc}", metadata={"sourceTitleTranslationStatus": "failed"})
        backend_logger.warning("原视频标题翻译失败 job_id=%s video_id=%s", job.get("id") or "", job.get("videoId") or "", exc_info=True)
        return ""


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


def _settle_background_futures(*futures):
    for future in futures:
        if not future or future.cancel():
            continue
        try:
            future.result()
        except Exception:
            pass


def _highlight_shortfall_message(job, assets):
    expected = int(job.get("highlightCount") or 3) if job.get("highlightIntroEnabled", True) else 0
    actual = len((assets or {}).get("segments") or [])
    if expected and actual < expected:
        return f"高光片段数量不足：请求 {expected} 条，实际生成 {actual} 条，已使用现有片段继续生成成片"
    return ""


def _editing_body_signature_compatible(record, job, ass_file):
    stored_signature = record.get("editingBodySignature") or ""
    current_signature = editing_body_signature(job)
    if stored_signature == current_signature:
        return True
    return bool(
        not job.get("translationEnabled", True)
        and not job.get("subtitleMaskEnabled")
        and not ass_file
        and stored_signature == editing_legacy_body_signature(job)
    )


def _save_final_highlight_selection(job, analysis_result, editing_result):
    if not isinstance(analysis_result, dict) or not isinstance(editing_result, dict):
        return
    analysis_result["selected_highlight_segments"] = list(editing_result.get("segments") or [])
    analysis_result["highlightSelection"] = {
        "status": "selected" if analysis_result["selected_highlight_segments"] else "skipped",
        "selectedCount": len(analysis_result["selected_highlight_segments"]),
    }
    save_youtube_video_analysis(job.get("videoId"), analysis_result)


def _mark_editing_intro_stale(job, analysis_result):
    record = _get_youtube_video_record(job.get("videoId")) or {}
    body_signature = record.get("editingBodySignature") or ""
    previous_intro = record.get("editingIntroSignature") or ""
    if body_signature and previous_intro and editing_intro_signature(job, analysis_result or {}, body_signature) != previous_intro:
        update_youtube_video_artifacts(job["videoId"], editingIntroStatus="stale")


def _editing_intro_requested(job):
    return bool(job.get("highlightIntroEnabled", True) or job.get("coverIntroEnabled", True))


def _is_cover_reburn(job):
    return str((job or {}).get("operation") or "") == "cover_reburn"


def _replace_cover_intro(output_file, cover_assets, work_dir):
    cover = (cover_assets or {}).get("cover") or {}
    cover_duration = float(cover.get("durationSeconds") or 0)
    cover_clips = list((cover_assets or {}).get("clips") or [])
    if not cover_clips or cover_duration <= 0:
        raise RuntimeError("未生成新封面片头，请检查封面图片和标题")
    preserved_intro = Path(work_dir) / "preserved_intro_and_body.mp4"
    _run_command([
        _resolve_ffmpeg_command(), "-y", "-ss", f"{cover_duration:.3f}", "-i", str(output_file),
        "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(preserved_intro),
    ], cwd=BASE_DIR)
    return concat_editing_intro_assets(preserved_intro, cover_assets, output_file, work_dir)


def _editing_analysis_required(job):
    if job.get("highlightIntroEnabled", True):
        return True
    return bool(job.get("coverIntroEnabled", True) and not normalize_cover_title(job.get("coverTitle")))


def _run_content_safety_review(job, source_file, segments, transcript_file):
    existing = (job.get("contentRisk") or {}).get("contentSafety") or {}
    if existing.get("decision") in {"trim", "safe"}:
        return job, False
    job = update_youtube_workflow_job(job["id"], source_file_path=str(source_file))
    event_id = start_workflow_event(job, "content_safety_detect", "开始检测长广告与站外引流", input_file_path=transcript_file)
    usage = {}
    try:
        snapshot, usage = detect_content_safety(
            job, segments, build_workflow_llm_telemetry(job, event_id, "content_safety_detect"),
        )
        finish_workflow_event(event_id, "success", "广告风险检测完成", cloud_usage=_editing_plan_usage(usage), metadata={"candidateCount": len(snapshot.get("candidates") or []), "riskCount": len(snapshot.get("risks") or [])})
    except Exception as exc:
        snapshot = {"status": "unavailable", "version": CONTENT_SAFETY_VERSION, "candidates": [], "risks": [], "reason": str(exc)[:240]}
        finish_workflow_event(event_id, "failed", "广告风险检测不可用，等待人工确认")
        backend_logger.warning("content safety detection failed : job_id = %s | error = %s", job.get("id") or "", exc.__class__.__name__)
    snapshot.update({"transcriptFilePath": str(transcript_file), "sourceDuration": float(_get_video_info(source_file).get("duration") or 0)})
    save_content_safety_snapshot(job, snapshot)
    content_risk = {**(job.get("contentRisk") or {}), "contentSafetyReviewEnabled": True, "contentSafety": snapshot}
    job = update_youtube_workflow_job(job["id"], content_risk=content_risk)
    if snapshot.get("status") == "clear":
        backend_logger.info("content safety detection clear : job_id = %s | candidate_count = %s", job.get("id") or "", len(snapshot.get("candidates") or []))
        return job, False
    confirm_event = start_workflow_event(job, "content_safety_confirm", "检测到广告风险，等待管理员确认", input_file_path=source_file, metadata={"riskCount": len(snapshot.get("risks") or []), "status": snapshot.get("status")})
    finish_workflow_event(confirm_event, "success", "等待视频处理确认", metadata={"riskCount": len(snapshot.get("risks") or []), "status": snapshot.get("status")})
    update_youtube_workflow_job(job["id"], status="waiting_confirmation", step="content_safety_confirm", message="检测到广告风险，等待视频处理确认", progress=28, speed="", eta="")
    backend_logger.info("content safety review pending : job_id = %s | candidate_count = %s | risk_count = %s", job.get("id") or "", len(snapshot.get("candidates") or []), len(snapshot.get("risks") or []))
    return job, True


def _apply_content_safety_trim(job, source_file):
    snapshot = (job.get("contentRisk") or {}).get("contentSafety") or {}
    if snapshot.get("decision") != "trim":
        return Path(source_file)
    event_id = start_workflow_event(job, "content_trim", "正在裁剪广告风险片段", input_file_path=source_file, metadata={"rangeCount": len(snapshot.get("trimRanges") or [])})
    try:
        output_file, ranges = _content_safety_trim_video(job, source_file, snapshot.get("trimRanges") or [])
        transcript_path = Path(snapshot.get("transcriptFilePath") or "")
        if transcript_path.is_file():
            payload = json.loads(transcript_path.read_text(encoding="utf-8-sig"))
            payload["segments"] = _content_safety_remap_segments(payload.get("segments") or [], ranges)
            payload["sourceFile"] = str(output_file)
            payload["contentSafetyTrimRanges"] = ranges
            trimmed_transcript = transcript_path.with_name(f"{transcript_path.stem}_content_safe.json")
            trimmed_transcript.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            update_youtube_video_artifacts(job.get("videoId"), transcriptFilePath=str(trimmed_transcript))
        update_youtube_workflow_job(job["id"], source_file_path=str(output_file), step="subtitle", message="广告风险片段裁剪完成，正在继续处理", progress=34)
        finish_workflow_event(event_id, "success", "广告风险片段裁剪完成", output_file_path=output_file, metadata={"rangeCount": len(ranges), "removedSeconds": round(sum(item["end"] - item["start"] for item in ranges), 2)})
        backend_logger.info("content trim completed : job_id = %s | range_count = %s", job.get("id") or "", len(ranges))
        return output_file
    except Exception as exc:
        error_fields = _workflow_error_fields(exc)
        finish_workflow_event(event_id, "failed", error_fields["error_reason"])
        backend_logger.error("content trim failed : job_id = %s | error_code = %s | error_type = %s | exception = %s", job.get("id") or "", error_fields["error_code"], error_fields["error_type"], exc.__class__.__name__)
        raise


def _run_editing_plan_analysis(job, source_file, segments, language, transcript_file, event_id):
    try:
        result, usage = _generate_editing_plan(
            job,
            segments,
            build_workflow_llm_telemetry(job, event_id, "analysis"),
        )
        highlight_intro_enabled = bool(job.get("highlightIntroEnabled", True))
        result["_highlightIntroEnabled"] = highlight_intro_enabled
        if highlight_intro_enabled:
            def report_vision_progress(index, total, remaining_seconds):
                update_youtube_workflow_job(
                    job["id"],
                    step="analysis",
                    message=f"正在审核高光候选 {index}/{total}",
                    progress=88,
                )

            candidates = [
                {**segment, "candidateId": str(segment.get("candidateId") or f"candidate-{index + 1}")}
                for index, segment in enumerate(result.get("highlight_segments") or [])
                if isinstance(segment, dict)
            ]
            highlights, vision_review = refine_highlight_segments(
                job,
                source_file,
                segments,
                candidates,
                _max_transcript_seconds(segments),
                progress_callback=report_vision_progress,
                telemetry=build_workflow_llm_telemetry(job, event_id, "analysis"),
            )
            result["highlight_candidates"] = candidates
            result["selected_highlight_segments"] = highlights
            result["highlight_segments"] = candidates
            result["highlightReview"] = {
                **(vision_review or {}),
                "candidateCount": len(candidates),
                "shortlistedCandidates": [
                    {
                        "candidateId": item.get("candidateId"),
                        "textShortlistRank": item.get("textShortlistRank"),
                        "textShortlistReason": item.get("textShortlistReason"),
                    }
                    for item in (vision_review or {}).get("textShortlist", {}).get("selected", [])
                    if item.get("textShortlistRank")
                ],
            }
        else:
            vision_review = {"status": "disabled", "reason": "高光拼接开关已关闭"}
        save_youtube_video_analysis(job.get("videoId"), {
            **result,
            "transcriptLanguage": language or "",
            "transcriptFilePath": str(transcript_file),
            "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        _mark_editing_intro_stale(job, result)
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


def _run_comment_burn_preparation(job):
    if not job.get("commentBurnEnabled"):
        return {"status": "disabled", "comments": [], "reason": "评论烧制开关已关闭"}
    signature = comment_burn_signature(job)
    backend_logger.info("评论烧制准备开始 job_id=%s video_id=%s mode=%s", job.get("id") or "", job.get("videoId") or "", job.get("commentTranslationMode") or "google_llm")
    cached = get_youtube_comment_burn_snapshot(job.get("videoId"))
    if cached.get("signature") == signature and cached.get("comments"):
        backend_logger.info("评论烧制复用缓存 job_id=%s video_id=%s comments=%s", job.get("id") or "", job.get("videoId") or "", len(cached.get("comments") or []))
        cached_event_id = start_workflow_event(job, "comment_review", "复用评论筛选与翻译缓存")
        finish_workflow_event(
            cached_event_id,
            "success",
            f"复用 {len(cached.get('comments') or [])} 条可烧制评论",
            metadata={"reviewItems": cached.get("reviewItems") or [], "cached": True},
        )
        return {**cached, "status": "ready", "reused": True}

    fetch_event_id = start_workflow_event(job, "comment_fetch", "开始获取 YouTube 热门评论")
    try:
        fetch_meta = {}
        review_items = []
        candidates = fetch_youtube_comment_candidates(job.get("url"), fetch_meta, review_items)
        backend_logger.info("评论获取完成 job_id=%s fetched=%s candidates=%s regex_filtered=%s", job.get("id") or "", fetch_meta.get("fetchedCount") or 0, len(candidates), fetch_meta.get("regexFilteredCount") or 0)
        save_youtube_comment_burn_snapshot(
            job.get("videoId"),
            {"status": "pending", "comments": [], "candidateCount": len(candidates), "reviewItems": review_items},
            signature,
            "pending",
        )
        finish_workflow_event(fetch_event_id, "success", f"已获取 {len(candidates)} 条可筛选评论", metadata={**fetch_meta, "reviewItems": review_items})
    except Exception as exc:
        backend_logger.warning("评论获取失败 job_id=%s error=%s: %s", job.get("id") or "", exc.__class__.__name__, str(exc)[:160])
        reason = f"评论获取失败：{str(exc)[:160]}"
        finish_workflow_event(fetch_event_id, "failed", reason)
        snapshot = {"status": "failed", "comments": [], "reason": reason, "reviewItems": []}
        save_youtube_comment_burn_snapshot(job.get("videoId"), snapshot, signature, "failed")
        return snapshot
    if not candidates:
        snapshot = {"status": "skipped", "comments": [], "reason": "未获取到可用评论", "candidateCount": 0, "reviewItems": review_items}
        save_youtube_comment_burn_snapshot(job.get("videoId"), snapshot, signature, "skipped")
        return snapshot

    review_event_id = start_workflow_event(job, "comment_review", "正在筛选并翻译评论", metadata={"candidateCount": len(candidates), "reviewItems": review_items})
    try:
        comments, usage, generation_meta = review_youtube_comment_candidates_v2(
            job,
            candidates,
            build_workflow_llm_telemetry(job, review_event_id, "comment_review"),
        )
        backend_logger.info("评论筛选与翻译完成 job_id=%s selected=%s translated=%s burned=%s", job.get("id") or "", generation_meta.get("selectedCount") or 0, generation_meta.get("translatedCount") or 0, len(comments))
        snapshot = {
            "status": "ready" if comments else "skipped",
            "reason": "" if comments else (
                "评论初筛模型输出格式错误，请重试"
                if generation_meta.get("failureCode") == "LLM_OUTPUT_FORMAT_ERROR"
                else "评论翻译失败，未生成可烧制评论"
                if int(generation_meta.get("selectedCount") or 0) and int((generation_meta.get("translation") or {}).get("googleFailedCount") or 0)
                else "LLM 未选出合格评论"
            ),
            "fetchedCount": int(fetch_meta.get("fetchedCount") or 0),
            "candidateCount": len(candidates),
            "regexFilteredCount": int(fetch_meta.get("regexFilteredCount") or 0),
            "selectedCount": int(generation_meta.get("selectedCount") or 0),
            "translatedCount": int(generation_meta.get("translatedCount") or 0),
            "burnedCount": len(comments),
            "translationMode": job.get("commentTranslationMode") or "google_llm",
            "comments": comments,
            "generationMeta": generation_meta,
            "reviewItems": build_comment_review_items(review_items, generation_meta, comments),
        }
        save_youtube_comment_burn_snapshot(job.get("videoId"), snapshot, signature, snapshot["status"])
        finish_workflow_event(
            review_event_id,
            "success",
            f"已筛选 {len(comments)} 条可烧制评论" if comments else snapshot["reason"],
            cloud_usage=_editing_plan_usage(usage),
            metadata={"fetchedCount": int(fetch_meta.get("fetchedCount") or 0), "candidateCount": len(candidates), "selectedCount": snapshot["selectedCount"], "translatedCount": snapshot["translatedCount"], "burnedCount": len(comments), "regexFilteredCount": int(fetch_meta.get("regexFilteredCount") or 0), "generationMeta": generation_meta, "reviewItems": snapshot["reviewItems"], "translationMode": snapshot["translationMode"]},
        )
        return {**snapshot, "signature": signature}
    except Exception as exc:
        backend_logger.warning("评论筛选与翻译失败 job_id=%s error=%s: %s", job.get("id") or "", exc.__class__.__name__, str(exc)[:160])
        reason = f"评论筛选失败：{str(exc)[:160]}"
        failed_review_items = build_comment_review_items(review_items, {}, [])
        finish_workflow_event(review_event_id, "failed", reason, metadata={"candidateCount": len(candidates), "reviewItems": failed_review_items})
        snapshot = {"status": "failed", "comments": [], "reason": reason, "candidateCount": len(candidates), "reviewItems": failed_review_items}
        save_youtube_comment_burn_snapshot(job.get("videoId"), snapshot, signature, "failed")
        return snapshot


def _start_parallel_editing_plan(job, source_file):
    job_id = job["id"]
    comment_future = _submit_background_task("comment", _run_comment_burn_preparation, job) if job.get("commentBurnEnabled") else None
    if not _editing_analysis_required(job):
        return job, None, None, comment_future
    job = update_youtube_workflow_job(
        job_id,
        source_file_path=str(source_file),
        step="subtitle",
        message="处理版本二：正在进行语音转写",
        progress=10,
        speed="",
        eta="",
    )
    job = {**job, "_highlightIntroEnabled": bool(job.get("highlightIntroEnabled", True))}
    transcript_event_id = start_workflow_event(job, "transcript", "开始语音转写", input_file_path=source_file)
    try:
        segments, language, transcript_file = _prepare_editing_transcript(job, source_file)
    except Exception as exc:
        finish_workflow_event(transcript_event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise
    finish_workflow_event(
        transcript_event_id,
        "success",
        f"语音转写完成，识别到 {len(segments)} 段字幕",
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
    return job, future, analysis_event_id, comment_future


def _process_subtitles_with_events(job, source_file, language_meta, on_body_burn_started=None, comment_future=None):
    subtitle_enabled = bool(job.get("translationEnabled", True))
    subtitle_event_id = start_workflow_event(
        job,
        "subtitle",
        f"开始{language_meta['label']}翻译与修订" if subtitle_enabled else "按设置跳过字幕翻译和烧录",
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
            "body_burn" if _normalize_process_version(job.get("processVersion")) == PROCESS_VERSION_EDITING else "subtitle_burn",
            f"开始烧制{language_meta['label']}字幕",
            input_file_path=ass_file,
        )
        if on_body_burn_started:
            on_body_burn_started(ass_file)

    subtitle_result = _process_subtitles(
        job,
        source_file,
        build_workflow_llm_telemetry(job, subtitle_event_id, "subtitle"),
        before_burn=start_burn_event,
        comment_future=comment_future,
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
            _subtitle_skip_reason(subtitle_result) if subtitle_result.get("skipped") else f"{language_meta['label']}字幕处理完成",
            output_file_path=processed_file,
        )
    return subtitle_result, subtitle_event_id, burn_event_id


def _render_parallel_editing_intro(job, source_file, ass_file, analysis_future):
    analysis_result = analysis_future.result() if analysis_future else {}
    work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{job['id']}_editing_intro")
    cover_event = start_workflow_event(job, "cover_render", "开始生成封面片头", input_file_path=source_file)
    highlight_event = None
    try:
        assets = render_editing_intro_assets(job, source_file, ass_file, analysis_result or {}, work_dir)
        highlight_warning = _highlight_shortfall_message(job, assets)
        if highlight_warning:
            assets["highlightWarning"] = highlight_warning
        finish_workflow_event(cover_event, "success", "封面片头生成完成" if assets.get("cover") else "未生成封面片头", output_file_path=(assets.get("clips") or [""])[0])
        highlight_event = start_workflow_event(job, "highlight_render", f"已生成 {len(assets.get('segments') or [])} 个高光短片", input_file_path=ass_file)
        finish_workflow_event(highlight_event, "success", f"高光短片生成完成，共 {len(assets.get('segments') or [])} 段" + (f"；{highlight_warning}" if highlight_warning else ""))
        return analysis_result or {}, assets, work_dir
    except Exception as exc:
        finish_workflow_event(highlight_event or cover_event, "failed", _workflow_error_fields(exc)["error_reason"])
        raise


def _finalize_parallel_editing(job, subtitle_result, source_file, intro_future):
    if intro_future is None:
        raise RuntimeError("片头高光任务未成功提交，请稍后重试")
    rendered = intro_future.result()
    if not rendered:
        raise RuntimeError("片头高光任务未返回渲染结果，请稍后重试")
    analysis_result, assets, work_dir = rendered
    intro_status = "synced"
    body_file = Path(subtitle_result["path"])
    final_file = body_file
    body_signature = editing_body_signature(job)
    intro_signature = editing_intro_signature(job, analysis_result, body_signature) if assets.get("clips") else ""
    try:
        if assets.get("clips"):
            body_file = body_file.with_name(f"{body_file.stem}_body{body_file.suffix}")
            Path(subtitle_result["path"]).replace(body_file)
            # 改名后立即落库：即便后续 concat 失败，body 仍可被"更新片头高光"复用。
            update_youtube_video_artifacts(job["videoId"], editingBodyPath=str(body_file), editingAssPath=subtitle_result.get("assPath") or "", editingBodySignature=body_signature, editingIntroSignature=intro_signature, editingHighlightSnapshot=json.dumps(assets.get("segments") or [], ensure_ascii=False), editingIntroStatus="concat_pending")
            concat_event = start_workflow_event(job, "editing_concat", "开始无重编码拼接片头与正片", input_file_path=body_file)
            try:
                final_file = concat_editing_intro_assets(body_file, assets, subtitle_result["path"], work_dir)
                finish_workflow_event(concat_event, "success", "封面、高光与正片拼接完成", output_file_path=final_file)
            except Exception as exc:
                # concat 失败：把悬空的 processedFilePath 指向改名后的 body(带字幕、无片头，仍是合法成片)，
                # 再 re-raise 让任务走 failed(符合文档"任务失败并保留 body")。
                update_youtube_video_artifacts(job["videoId"], processedFilePath=str(body_file), editingIntroStatus="concat_failed")
                finish_workflow_event(concat_event, "failed", _workflow_error_fields(exc)["error_reason"])
                raise
        result = {"path": str(final_file), "segments": assets.get("segments") or [], "cover": assets.get("cover"), "skipped": not bool(assets.get("clips")), "reason": "", "highlightWarning": assets.get("highlightWarning") or "", "bodyPath": str(body_file), "assPath": subtitle_result.get("assPath") or "", "bodySignature": body_signature, "introSignature": intro_signature}
        _save_final_highlight_selection(job, analysis_result, result)
        update_youtube_video_artifacts(job["videoId"], editingBodyPath=result["bodyPath"], editingAssPath=result["assPath"], editingBodySignature=body_signature, editingIntroSignature=intro_signature, editingHighlightSnapshot=json.dumps(result["segments"], ensure_ascii=False), editingIntroStatus=intro_status)
        return result
    finally:
        # 清理片头渲染临时目录(封面/高光短片中间产物与 concat 中转文件)。
        if work_dir:
            safe_rmtree(work_dir)


def _append_translation_cover_intro(job, source_file, subtitle_result):
    if not job.get("coverIntroEnabled", True):
        return {"path": subtitle_result["path"], "cover": None, "skipped": True}
    work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{job['id']}_translation_cover")
    cover_event = start_workflow_event(job, "cover_render", "开始生成封面片头", input_file_path=source_file)
    try:
        cover_job = {
            **job,
            "highlightIntroEnabled": False,
            "coverTitle": normalize_cover_title(job.get("coverTitle")) or normalize_cover_title(job.get("title")),
        }
        assets = render_editing_intro_assets(cover_job, source_file, None, {}, work_dir)
        if not assets.get("clips"):
            finish_workflow_event(cover_event, "success", "未生成封面片头")
            return {"path": subtitle_result["path"], "cover": None, "skipped": True}
        body_file = Path(subtitle_result["path"])
        final_file = body_file.with_name(f"{body_file.stem}_with_cover{body_file.suffix}")
        concat_event = start_workflow_event(job, "editing_concat", "开始拼接封面片头与正片", input_file_path=body_file)
        try:
            final_file = concat_editing_intro_assets(body_file, assets, final_file, work_dir)
        except Exception as exc:
            finish_workflow_event(concat_event, "failed", _workflow_error_fields(exc)["error_reason"])
            raise
        finish_workflow_event(cover_event, "success", "封面片头生成完成", output_file_path=(assets.get("clips") or [""])[0])
        finish_workflow_event(concat_event, "success", "封面片头与正片拼接完成", output_file_path=final_file)
        return {"path": str(final_file), "cover": assets.get("cover"), "skipped": False}
    except Exception as exc:
        finish_workflow_event(cover_event, "failed", _workflow_error_fields(exc)["error_reason"])
        raise
    finally:
        safe_rmtree(work_dir)


def _prepare_transcript_with_event(job, source_file):
    transcript_event_id = start_workflow_event(job, "transcript", "开始语音转写", input_file_path=source_file)
    work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(source_file).stem}_work")
    try:
        segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir)
    except Exception as exc:
        finish_workflow_event(transcript_event_id, "failed", _workflow_error_fields(exc)["error_reason"])
        raise
    finish_workflow_event(
        transcript_event_id,
        "success",
        f"语音转写完成，识别到 {len(segments)} 段字幕",
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
    analysis_future = None
    intro_future = None
    comment_future = None
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
        _ensure_source_title_translation(initial_job)
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        job = initial_job
        source_file = _resolve_downloaded_source_file(job)

        if job.get("contentSafetyReviewEnabled"):
            try:
                safety_segments, _safety_language, safety_transcript = _get_or_create_transcript(job, source_file, _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(source_file).stem}_content_safety"))
            except NoSpeechDetectedError:
                safety_segments, safety_transcript = [], ""
            job, pending_content_safety_confirmation = _run_content_safety_review(job, source_file, safety_segments, safety_transcript)
            if pending_content_safety_confirmation:
                return
            source_file = _apply_content_safety_trim(job, source_file)

        job = _resolve_source_subtitle_processing(job, source_file)
        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            job, analysis_future, analysis_event_id, comment_future = _start_parallel_editing_plan(job, source_file)
        elif job.get("translationEnabled", True):
            transcript_event_id = _prepare_transcript_with_event(job, source_file)

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在启动转写和处理" if job.get("translationEnabled", True) else "已找到下载视频，已按设置跳过字幕处理",
            step="subtitle",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 5,
        )
        def start_intro_render(ass_file):
            nonlocal intro_future
            if process_version == PROCESS_VERSION_EDITING and _editing_intro_requested(job):
                intro_future = _submit_background_task("analysis", _render_parallel_editing_intro, job, source_file, ass_file, analysis_future)

        subtitle_result, event_id, burn_event_id = _process_subtitles_with_events(job, source_file, language_meta, start_intro_render, comment_future=comment_future if process_version == PROCESS_VERSION_EDITING else None)
        if process_version == PROCESS_VERSION_EDITING and not job.get("translationEnabled", True):
            start_intro_render(None)
        if job.get("translationEnabled", True) and process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        skipped_subtitles = bool(subtitle_result.get("skipped"))
        translation_cover_result = None
        if process_version == PROCESS_VERSION_TRANSLATION:
            translation_cover_result = _append_translation_cover_intro(job, source_file, subtitle_result)
            processed_file = translation_cover_result["path"]

        if process_version == PROCESS_VERSION_EDITING and intro_future:
            editing_event_id = start_workflow_event(job, "editing", "正在等待并行片头高光与正片烧制", input_file_path=processed_file)
            editing_result = _finalize_parallel_editing(job, subtitle_result, source_file, intro_future)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            _save_final_highlight_selection(job, analysis_result, editing_result)
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
        elif translation_cover_result and translation_cover_result.get("cover"):
            job = {**job, "coverIntro": translation_cover_result["cover"]}
        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )
        final_message = f"{_subtitle_skip_reason(subtitle_result)}并保存到素材库" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库"
        if process_version == PROCESS_VERSION_EDITING and editing_result:
            final_message = f"{final_message}；{_editing_result_message(editing_result)}"
        elif translation_cover_result and translation_cover_result.get("cover"):
            final_message = f"{final_message}；已添加封面片头"
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
        _settle_background_futures(intro_future, analysis_future, comment_future)
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
        _mark_editing_intro_stale(job, result)
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

def run_youtube_update_editing_intro_job(job_id):
    editing_event_id = None
    work_dir = None
    try:
        job = claim_youtube_workflow_job(job_id, step="editing", message="正在重新烧制封面" if _is_cover_reburn(get_youtube_workflow_job(job_id)) else "正在更新封面片头与高光", progress=10, speed="", eta="")
        if not job:
            return
        cover_only = _is_cover_reburn(job)
        record = _get_youtube_video_record(job.get("videoId")) or {}
        body_file = Path(record.get("editingBodyPath") or "")
        ass_path = record.get("editingAssPath") or ""
        ass_file = Path(ass_path) if ass_path else None
        if not body_file.is_file() or (job.get("translationEnabled", True) and (not ass_file or not ass_file.is_file())):
            raise RuntimeError("未找到可复用的编辑版正片，请执行完整处理")
        if not _editing_body_signature_compatible(record, job, ass_file):
            raise RuntimeError("字幕、水印或评论设置已变化，请执行完整处理")
        if record.get("editingBodySignature") != editing_body_signature(job):
            update_youtube_video_artifacts(job["videoId"], editingBodySignature=editing_body_signature(job))
            backend_logger.info("editing body signature upgraded : job_id = %s | video_id = %s", job_id, job.get("videoId", ""))
        output_path = record.get("processedFilePath") or ""
        if output_path:
            output_file = Path(output_path)
        elif body_file.stem.endswith("_body"):
            output_file = body_file.with_name(f"{body_file.stem[:-5]}{body_file.suffix}")
        else:
            raise RuntimeError("未找到编辑版成片输出路径，请执行完整处理")
        source_file = _resolve_downloaded_source_file(job)
        analysis_result = (get_youtube_video_analysis(job.get("videoId")) or {}).get("result") or {}
        editing_event_id = start_workflow_event(job, "editing", "开始重新烧制封面" if cover_only else "开始更新封面片头与高光", input_file_path=body_file)
        work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{job['id']}_editing_intro")
        if cover_only:
            assets = render_editing_intro_assets({**job, "highlightIntroEnabled": False}, source_file, None, {}, work_dir)
            final_file = _replace_cover_intro(output_file, assets, work_dir)
            assets["segments"] = record.get("editingHighlightSnapshot") or []
        else:
            assets = render_editing_intro_assets(job, source_file, ass_file, analysis_result, work_dir)
            highlight_warning = _highlight_shortfall_message(job, assets)
            if highlight_warning:
                assets["highlightWarning"] = highlight_warning
            final_file = concat_editing_intro_assets(body_file, assets, output_file, work_dir) if assets.get("clips") else body_file
        intro_signature = editing_intro_signature(job, analysis_result, record["editingBodySignature"])
        result = {"path": str(final_file), "segments": assets.get("segments") or [], "cover": assets.get("cover"), "highlightWarning": assets.get("highlightWarning") or ""}
        _save_processed_video_to_material(final_file, {**job, "coverIntro": result.get("cover") or {}})
        if not cover_only:
            _save_final_highlight_selection(job, analysis_result, result)
        update_youtube_video_artifacts(job["videoId"], editingIntroSignature=intro_signature, editingHighlightSnapshot=json.dumps(result["segments"], ensure_ascii=False), editingIntroStatus="synced")
        message = "封面片头已重新烧制" if cover_only else f"已更新 {len(result['segments'])} 个高光片段" + (f"；{highlight_warning}" if highlight_warning else "")
        finish_workflow_event(editing_event_id, "success", message, output_file_path=final_file)
        update_youtube_workflow_job(job_id, status="success", step="done", message=message, processed_file_path=str(final_file), progress=100, speed="", eta="")
    except Exception as exc:
        error_fields = _log_workflow_failure("更新片头高光任务", job_id, exc)
        finish_workflow_event(editing_event_id, "failed", error_fields["error_reason"])
        finish_open_workflow_events(job_id, "failed", error_fields["error_reason"])
        update_youtube_workflow_job(job_id, status="failed", step="failed", message=error_fields["error_reason"], **error_fields, speed="", eta="")
    finally:
        # 清理本次片头渲染临时目录(封面/高光短片中间产物与 concat 中转文件)。
        if work_dir:
            safe_rmtree(work_dir)


def _workflow_publish_summary(results):
    results = list(results or [])
    successful_platforms = [item.get("platformName") for item in results if item.get("status") in {"confirmed", "reused"}]
    failed_platforms = [item.get("platformName") for item in results if item.get("status") not in {"confirmed", "reused"}]
    return {
        "successfulPlatforms": successful_platforms,
        "failedPlatforms": failed_platforms,
        "failed": bool(failed_platforms),
    }


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
    if publish_draft.get("customTags"):
        publish_job["customTags"] = publish_draft["customTags"]
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

    publish_job, schedule_notice = _ensure_workflow_publish_schedule(job_id, publish_job)
    publish_results = []
    skipped_platforms = []
    publish_event_id = start_workflow_event(publish_job, "publish", "开始发布", input_file_path=processed_file)
    publishing_platform_type = 0
    publish_specs = [
        (3, latest_job.get("account") or ""),
        (5, latest_job.get("bilibiliAccount") or ""),
        (1, latest_job.get("xiaohongshuAccount") or ""),
        (4, latest_job.get("kuaishouAccount") or ""),
        (2, latest_job.get("tencentAccount") or ""),
    ]
    queued_tasks = []
    queued_owner_user_id = None
    for platform_type, account_name in publish_specs:
        if not account_name:
            continue
        account_info = _check_named_publish_account(platform_type, account_name, publish_job.get("ownerUserId"))
        queued_task = _workflow_publish_task(publish_job, processed_file, platform_type, account_info)
        queued_task.update({
            "publishTaskId": f"workflow:{job_id}",
            "accountName": account_name,
            "fileList": [str(material.get("file_path") or material.get("storage_key") or processed_file)],
            "absoluteFiles": [Path(processed_file)],
            "timeoutSeconds": 3600,
        })
        queued_tasks.append(queued_task)
        queued_owner_user_id = account_info.get("ownerUserId")
    if queued_tasks:
        queued = enqueue_publish_tasks(
            queued_tasks,
            source="workflow",
            source_ref_id=job_id,
            owner_user_id=queued_owner_user_id,
            publish_task_id=f"workflow:{job_id}",
        )
        dispatch_status = queued.get("status") or "queued"
        if dispatch_status not in {"queued", "waiting_existing"}:
            backend_logger.info(
                "workflow publish resolved without new execution : job_id = %s | publish_task_id = %s | status = %s",
                job_id,
                queued["publishTaskId"],
                dispatch_status,
            )
            return []
        message = "等待已有发布任务完成" if dispatch_status == "waiting_existing" else "发布任务已进入队列"
        if skipped_platforms:
            message += "；已跳过已发布平台：" + "、".join(skipped_platforms)
        update_youtube_workflow_job(
            job_id,
            status="waiting_publish",
            step="publish",
            message=message,
            progress=97,
            speed="",
            eta="",
        )
        backend_logger.info("workflow publish queued : job_id = %s | publish_task_id = %s", job_id, queued["publishTaskId"])
        return []
    try:
        for platform_type, account_name in publish_specs:
            if not account_name:
                continue
            publishing_platform_type = platform_type
            result = _publish_workflow_platform(publish_job, processed_file, material, platform_type, account_name)
            if result:
                publish_results.append(result)
    except Exception as exc:
        platform_label = platform_name(publishing_platform_type) if publishing_platform_type else "目标平台"
        publish_error = RuntimeError(f"PUBLISH_FAILED:{platform_label}:{str(exc)}")
        finish_workflow_event(publish_event_id, "failed", _workflow_error_fields(publish_error)["error_reason"])
        raise publish_error from exc

    summary = _workflow_publish_summary(publish_results)
    final_message = "任务完成"
    if not publish_results:
        final_message = "任务完成，已保存到素材库，未配置发布平台账号所以未发布"
    elif summary["failed"]:
        success_text = "、".join(summary["successfulPlatforms"])
        failed_text = "、".join(summary["failedPlatforms"])
        final_message = f"发布完成，失败平台：{failed_text}" + (f"；成功平台：{success_text}" if success_text else "")
    if skipped_platforms:
        final_message = f"{final_message}；已跳过已发布平台：{'、'.join(skipped_platforms)}"
    process_version = _normalize_process_version(latest_job.get("processVersion"))
    if process_version == PROCESS_VERSION_EDITING and editing_result:
        final_message = f"{final_message}；{_editing_result_message(editing_result)}"
    if skipped_subtitles:
        final_message = f"{final_message}；{_subtitle_skip_reason({'skippedBySetting': not latest_job.get('translationEnabled', True)})}"
    if schedule_notice:
        final_message = f"{final_message}；{schedule_notice}"

    final_status = "failed" if summary["failed"] else "success"
    finish_workflow_event(publish_event_id, final_status, final_message, output_file_path=processed_file)
    if workflow_event_id:
        finish_workflow_event(workflow_event_id, final_status, final_message, output_file_path=processed_file)
    update_youtube_workflow_job(
        job_id,
        status=final_status,
        step="done" if final_status == "success" else "publish",
        message=final_message,
        publish_command="\n".join(summary["successfulPlatforms"]),
        progress=100,
        speed="",
        eta="",
    )
    if summary["successfulPlatforms"]:
        update_youtube_video_artifacts(job["videoId"], publish_status=1)
    return publish_results


def _processed_material_for_workflow(job):
    record = _get_youtube_video_record(job.get("videoId")) or {}
    processed_path = Path(record.get("processedFilePath") or "")
    with _db_connect() as conn:
        conn.row_factory = True
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


def _video_has_processed_output(record, job=None):
    if not record:
        return False
    translate_status = int(record.get("translateStatus") or 0)
    if translate_status not in (1, 2):
        return False
    processed_path = Path(record.get("processedFilePath") or "")
    if processed_path.is_file():
        return True
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        material = _find_latest_youtube_material(cursor, record.get("id") or record.get("videoId") or "", "youtube_processed")
    if not material:
        return False
    material_path = _material_file_path(material)
    return bool(material_path and material_path.is_file())


def workflow_job_resource(job):
    record = _get_youtube_video_record((job or {}).get("videoId")) or {}
    return "publish" if _video_has_processed_output(record, job) else "processing"


def run_youtube_workflow(job_id):
    workflow_event_id = None
    download_event_id = None
    analysis_event_id = None
    editing_event_id = None
    subtitle_event_id = None
    burn_event_id = None
    transcript_event_id = None
    analysis_future = None
    intro_future = None
    comment_future = None
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
        _ensure_source_title_translation(initial_job)
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        video_record = _get_youtube_video_record(initial_job.get("videoId")) or {}
        if _video_has_processed_output(video_record, initial_job):
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

        if job.get("contentSafetyReviewEnabled"):
            try:
                safety_segments, _safety_language, safety_transcript = _get_or_create_transcript(job, source_file, _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(source_file).stem}_content_safety"))
            except NoSpeechDetectedError:
                safety_segments, safety_transcript = [], ""
            job, pending_content_safety_confirmation = _run_content_safety_review(job, source_file, safety_segments, safety_transcript)
            if pending_content_safety_confirmation:
                finish_workflow_event(workflow_event_id, "success", "广告风险检测完成，等待视频处理确认")
                return
            source_file = _apply_content_safety_trim(job, source_file)

        job = _resolve_source_subtitle_processing(job, source_file)
        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            job, analysis_future, analysis_event_id, comment_future = _start_parallel_editing_plan(job, source_file)
        elif job.get("translationEnabled", True):
            transcript_event_id = _prepare_transcript_with_event(job, source_file)

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message=f"视频已下载，正在处理{language_meta['label']}字幕" if job.get("translationEnabled", True) else "视频已下载，已按设置跳过字幕处理",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 8,
            speed="",
            eta="",
        )
        def start_intro_render(ass_file):
            nonlocal intro_future
            if process_version == PROCESS_VERSION_EDITING and _editing_intro_requested(job):
                intro_future = _submit_background_task("analysis", _render_parallel_editing_intro, job, source_file, ass_file, analysis_future)

        subtitle_result, subtitle_event_id, burn_event_id = _process_subtitles_with_events(job, source_file, language_meta, start_intro_render, comment_future=comment_future if process_version == PROCESS_VERSION_EDITING else None)
        if process_version == PROCESS_VERSION_EDITING and not job.get("translationEnabled", True):
            start_intro_render(None)
        if job.get("translationEnabled", True) and process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        skipped_subtitles = bool(subtitle_result.get("skipped"))
        translation_cover_result = None
        if process_version == PROCESS_VERSION_TRANSLATION:
            translation_cover_result = _append_translation_cover_intro(job, source_file, subtitle_result)
            processed_file = translation_cover_result["path"]

        if process_version == PROCESS_VERSION_EDITING and intro_future:
            editing_event_id = start_workflow_event(job, "editing", "正在等待并行片头高光与正片烧制", input_file_path=processed_file)
            editing_result = _finalize_parallel_editing(job, subtitle_result, source_file, intro_future)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            _save_final_highlight_selection(job, analysis_result, editing_result)
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
        elif translation_cover_result and translation_cover_result.get("cover"):
            job = {**job, "coverIntro": translation_cover_result["cover"]}
        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_workflow_job(
            job_id,
            processed_file_path=str(processed_file),
            step="publish",
            message=f"{_subtitle_skip_reason(subtitle_result)}并保存到素材库，准备发布" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库，准备发布",
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
        _settle_background_futures(intro_future, analysis_future, comment_future)
        error_fields = _log_workflow_failure("完整工作流", job_id, exc)
        latest_job = get_youtube_workflow_job(job_id)
        failure_event_id = workflow_event_id if latest_job.get("step") == "publish" else (editing_event_id or analysis_event_id or burn_event_id or subtitle_event_id or transcript_event_id or download_event_id or workflow_event_id)
        finish_workflow_event(failure_event_id, "failed", error_fields["error_reason"])
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


