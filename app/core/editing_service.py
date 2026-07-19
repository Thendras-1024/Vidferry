"""处理版本二的剪辑增强:高光片段开头混剪与「Up Next」覆盖层生成。"""


import logging
import threading
import time

from app.core.llm_harness import LLMContractError, call_json_contract, contains_profanity, validate_chunk_summary, validate_editing_plan
from app.core import llm_prompts
from app.core.cover_service import (
    analyze_cover_layout,
    build_cover_clip_command,
    find_cover_image,
    normalize_cover_title,
    write_cover_ass,
)

# 直接取命名 logger，避免依赖运行期注入的 backend_logger（测试环境未注入）。
_logger = logging.getLogger("vidferry.backend")


EDITING_INTRO_MIN_START_SECONDS = 30
EDITING_COVER_DURATION_SECONDS = 1.0


def _editing_cover_title(job, analysis_result):
    title = normalize_cover_title((job or {}).get("coverTitle"))
    if title:
        return title
    options = (analysis_result or {}).get("cover_title_options") or []
    return normalize_cover_title(options[0] if options else "")


def _select_intro_highlight_segments(analysis_result, max_segments=3):
    raw_segments = (analysis_result or {}).get("highlight_segments") or []
    selected = []
    for segment in _normalize_highlight_segments(raw_segments):
        try:
            start = max(0.0, float(segment.get("start") or 0))
            end = max(start + 1, float(segment.get("end") or 0))
        except (TypeError, ValueError):
            continue
        if start < EDITING_INTRO_MIN_START_SECONDS or end - start < 2:
            continue
        selected.append({
            **segment,
            "start": round(start, 2),
            "end": round(end, 2),
        })
        if len(selected) >= max_segments:
            break
    return selected


def _ffmpeg_concat_file_path(path):
    return Path(path).resolve().as_posix().replace("'", "'\\''")


EDITING_UP_NEXT_TEXT = "精彩片段 Up Next"


def _editing_up_next_layout(width, height):
    width = max(320, int(width or 1080))
    height = max(320, int(height or 1920))
    short_side = min(width, height)
    font_size = max(28, min(62, int(short_side * 0.052)))
    box_x = max(24, int(width * 0.15))
    box_y = max(18, int(height * 0.040))
    box_w = min(width - box_x - 24, max(int(font_size * 8.8), int(width * 0.31)))
    box_h = max(int(font_size * 1.45), 48)
    box_w = max(box_w, int(font_size * 6.9))
    center_x = box_x + box_w / 2
    center_y = box_y + box_h / 2
    return {
        "font_size": font_size,
        "box_x": box_x,
        "box_y": box_y,
        "box_w": box_w,
        "box_h": box_h,
        "center_x": round(center_x, 1),
        "center_y": round(center_y, 1),
    }


def _editing_up_next_breath_tags(duration):
    duration_ms = max(1200, int(float(duration or 0) * 1000))
    tags = [
        r"\t(0,220,\fscx106\fscy106)",
        r"\t(220,800,\fscx100\fscy100)",
    ]
    for start in range(0, duration_ms, 1600):
        mid = min(start + 800, duration_ms)
        end = min(start + 1600, duration_ms)
        tags.append(fr"\t({start},{mid},\alpha&H06&\blur0.2)")
        tags.append(fr"\t({mid},{end},\alpha&H18&\blur0.8)")
    return "".join(tags)


def _write_editing_up_next_overlay_ass(ass_file, width, height, duration):
    ass_file = Path(ass_file)
    layout = _editing_up_next_layout(width, height)
    start = _format_ass_timestamp(0)
    end = _format_ass_timestamp(max(0.5, float(duration or 0.5)))
    text = _escape_ass_text(EDITING_UP_NEXT_TEXT)
    pos = fr"\pos({layout['center_x']},{layout['center_y']})"
    breath_tags = _editing_up_next_breath_tags(duration)
    glow_tags = _editing_up_next_breath_tags(duration).replace(r"\blur0.2", r"\blur5").replace(r"\blur0.8", r"\blur7")
    dialogue_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {max(320, int(width or 1080))}",
        f"PlayResY: {max(320, int(height or 1920))}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: UpNextGlow,Microsoft YaHei,{layout['font_size']},&H00FFFFEB,&H000000FF,&H00FFE660,&H00000000,1,0,0,0,100,100,0,0,1,8,0,5,0,0,0,1",
        f"Style: UpNextText,Microsoft YaHei,{layout['font_size']},&H00FFFFEB,&H000000FF,&H00FFE660,&H00000000,1,0,0,0,100,100,0,0,1,1.4,0,5,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{start},{end},UpNextGlow,,0,0,0,,{{\\an5{pos}\\alpha&H92&\\1c&HFFE660&\\3c&HFFE660&\\bord10\\blur7{glow_tags}}}{text}",
        f"Dialogue: 1,{start},{end},UpNextGlow,,0,0,0,,{{\\an5{pos}\\alpha&H72&\\1c&HFFFFEB&\\3c&HFFE660&\\bord4\\blur3{glow_tags}}}{text}",
        f"Dialogue: 2,{start},{end},UpNextText,,0,0,0,,{{\\an5{pos}\\alpha&H10&\\1c&HFFFFEB&\\3c&HFFE660&\\bord1.4\\blur0.4{breath_tags}}}{text}",
    ]
    ass_file.write_text("\n".join(dialogue_lines), encoding="utf-8")
    return ass_file


def _editing_up_next_overlay_filters(width, height, ass_file):
    subtitle_filter = f"subtitles='{_ffmpeg_subtitle_path(ass_file)}'"
    return [subtitle_filter]


def _editing_intro_video_filters(width, height, is_intro_clip=False, overlay_ass_file=None):
    video_filters = []
    if width and height:
        video_filters.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "setsar=1",
        ])
    else:
        video_filters.append("setsar=1")
    if is_intro_clip and overlay_ass_file:
        video_filters.extend(_editing_up_next_overlay_filters(width, height, overlay_ass_file))
    return video_filters


def _build_editing_intro_video(job, source_file, processed_file, analysis_result, work_dir):
    # 处理版本二核心:封面片头、前 3 个高光片段和正片统一规格后拼接。
    job_id = job.get("id")
    output_file = Path(processed_file)
    if not EDITING_ENABLE_COVER_INTRO and not EDITING_ENABLE_HIGHLIGHT_INTRO:
        return {
            "path": output_file,
            "segments": [],
            "cover": None,
            "skipped": True,
            "reason": "封面片头与高光拼接均已关闭",
            "watermarked": _watermark_enabled(job),
        }

    segments = _select_intro_highlight_segments(analysis_result, max_segments=3) if EDITING_ENABLE_HIGHLIGHT_INTRO else []
    ffmpeg = _resolve_ffmpeg_command()
    _, burn_config = _burn_profile_config(job.get("burnProfile"))
    processed_info = _get_video_info(processed_file)
    width = int(processed_info.get("width") or 0)
    height = int(processed_info.get("height") or 0)
    fps = float(processed_info.get("fps") or 30.0)
    if fps <= 0:
        fps = 30.0
    max_fps = float(burn_config.get("max_fps") or 60.0)
    if fps > max_fps:
        fps = max_fps

    work_dir = _ensure_dir(work_dir)
    clip_files = []
    cover_result = None
    cover_error = ""
    normalized_main = work_dir / f"{output_file.stem}_main_normalized.mp4"
    final_tmp = work_dir / f"{output_file.stem}_editing_concat.mp4"
    concat_file = work_dir / f"{output_file.stem}_concat.txt"

    overlay_ass_file = work_dir / f"{output_file.stem}_up_next_overlay.ass"
    cover_ass_file = work_dir / f"{output_file.stem}_cover.ass"
    cover_clip_file = work_dir / f"{output_file.stem}_cover.mp4"

    def encode_clip(input_file, output_clip, start=None, end=None, is_intro_clip=False):
        command = [ffmpeg, "-y"]
        clip_duration = None
        if start is not None:
            command.extend(["-ss", f"{start:.3f}"])
        if end is not None and start is not None:
            clip_duration = max(0.5, end - start)
            command.extend(["-t", f"{clip_duration:.3f}"])
        command.extend(["-i", str(input_file)])
        if is_intro_clip:
            _write_editing_up_next_overlay_ass(overlay_ass_file, width, height, clip_duration or 8)
        video_filters = _editing_intro_video_filters(width, height, is_intro_clip, overlay_ass_file)
        command.extend([
            "-vf", ",".join(video_filters),
            "-fps_mode", "cfr",
            "-r", f"{fps:.3f}".rstrip("0").rstrip("."),
            *video_encode_args(burn_config),
            "-maxrate", burn_config["maxrate"],
            "-bufsize", burn_config["bufsize"],
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-level:v", "4.1",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-movflags", "+faststart",
            str(output_clip),
        ])
        _run_command(command, cwd=BASE_DIR)

    cover_duration = EDITING_COVER_DURATION_SECONDS
    cover_title = _editing_cover_title(job, analysis_result)
    cover_path = find_cover_image(YOUTUBE_DOWNLOAD_DIR, job.get("videoId"), source_file)
    if EDITING_ENABLE_COVER_INTRO and cover_title and cover_path:
        try:
            _update_translate_progress(job_id, 84, "处理版本二：正在生成封面片头", step="editing")
            layout = analyze_cover_layout(cover_path, width, height, cover_title)
            write_cover_ass(
                cover_ass_file,
                width,
                height,
                cover_duration,
                cover_title,
                layout,
                signature=job.get("coverSignature") or job.get("coverBrandName"),
                watermark_text=_watermark_text(job) if _watermark_enabled(job) else "",
            )
            _run_command(
                build_cover_clip_command(
                    ffmpeg,
                    cover_path,
                    cover_ass_file,
                    cover_clip_file,
                    width,
                    height,
                    fps,
                    cover_duration,
                    burn_config,
                    layout,
                    has_audio=bool(processed_info.get("has_audio")),
                    color_info=processed_info.get("color"),
                ),
                cwd=BASE_DIR,
            )
            if not cover_clip_file.is_file() or cover_clip_file.stat().st_size <= 0:
                raise RuntimeError("FFmpeg 未生成有效封面片头文件")
            clip_files.append(cover_clip_file)
            cover_result = {
                "path": str(cover_path),
                "title": cover_title,
                "signature": job.get("coverSignature") or job.get("coverBrandName") or "Vidferry",
                "durationSeconds": cover_duration,
                "layout": layout,
            }
        except Exception as exc:
            cover_error = str(exc)[:300]
            backend_logger.warning(
                "封面片头生成失败 : job_id = %s | video_id = %s | reason = %s",
                job_id or "",
                job.get("videoId") or "",
                cover_error,
            )

    if not segments and not clip_files:
        if cover_error:
            reason = cover_error
        elif not EDITING_ENABLE_COVER_INTRO:
            reason = "封面片头已关闭且未找到可用高光片段"
        else:
            reason = "未找到本地封面或封面标题"
        return {
            "path": output_file,
            "segments": [],
            "cover": None,
            "skipped": True,
            "reason": reason,
            "watermarked": _watermark_enabled(job),
        }

    if segments:
        _update_translate_progress(job_id, 86, "处理版本二：正在截取前三个高光片段", step="editing")
    for index, segment in enumerate(segments, start=1):
        clip_file = work_dir / f"{output_file.stem}_intro_{index}.mp4"
        encode_clip(processed_file, clip_file, start=segment["start"], end=segment["end"], is_intro_clip=True)
        clip_files.append(clip_file)

    _update_translate_progress(job_id, 91, "处理版本二：正在拼接封面、高光与正片", step="editing")
    encode_clip(processed_file, normalized_main)
    concat_lines = [f"file '{_ffmpeg_concat_file_path(path)}'" for path in [*clip_files, normalized_main]]
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")
    _run_command([
        ffmpeg,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_tmp),
    ], cwd=BASE_DIR)
    _replace_output_file(final_tmp, output_file)
    return {
        "path": output_file,
        "segments": segments,
        "cover": cover_result,
        "skipped": False,
        "reason": cover_error,
        "watermarked": _watermark_enabled(job),
    }


def _format_segment_time(seconds):
    seconds = max(0, int(float(seconds or 0)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _format_transcript_for_model(segments):
    lines = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = _format_segment_time(segment.get("start"))
        end = _format_segment_time(segment.get("end"))
        lines.append(f"[{start}-{end}] {text}")
    return "\n".join(lines)


def _split_transcript_lines(text, max_chars):
    lines = text.splitlines()
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks or [text[:max_chars]]


def _max_transcript_seconds(segments):
    values = []
    for segment in segments or []:
        try:
            values.append(float(segment.get("end") or 0))
        except (AttributeError, TypeError, ValueError):
            continue
    return max(values, default=0.0)


def _unsafe_transcript_ranges(segments):
    ranges = []
    for segment in segments or []:
        if not contains_profanity(segment.get("text")):
            continue
        try:
            start = float(segment.get("start") or 0)
            end = float(segment.get("end") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if end > start:
            ranges.append((start, end))
    return ranges


def _call_editing_contract(messages, contract_id, validator, max_tokens, telemetry=None, soft_validator=None):
    return call_json_contract(
        messages=messages,
        contract_id=contract_id,
        validator=validator,
        model=TEXT_LLM_MODEL,
        api_key=TEXT_LLM_API_KEY,
        base_url=TEXT_LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=0.4,
        max_tokens=max_tokens,
        prompt_version=llm_prompts.EDITING_PROMPT_VERSION,
        telemetry=telemetry,
        soft_validator=soft_validator,
    )


def _editing_analysis_system_prompt():
    return llm_prompts.editing_analysis_system_prompt()


def _editing_analysis_user_prompt(job, transcript_text, chunk_context=""):
    return llm_prompts.build_editing_analysis_prompt(job, transcript_text, chunk_context)


def _summarize_transcript_chunks(job, transcript_text, max_timestamp, blocked_ranges, telemetry=None):
    max_chars = max(4000, LLM_MAX_TRANSCRIPT_CHARS)
    chunks = _split_transcript_lines(transcript_text, max_chars)
    if len(chunks) <= 1:
        return transcript_text, None

    summaries = []
    usage_total = {"tokens": 0, "totalTokens": 0, "promptTokens": 0, "completionTokens": 0, "latencyMs": 0, "attemptCount": 0, "validationRetries": 0}
    for index, chunk in enumerate(chunks, start=1):
        result, usage, generation_meta = _call_editing_contract(
            [
                {"role": "system", "content": _editing_analysis_system_prompt()},
                {"role": "user", "content": llm_prompts.build_chunk_summary_prompt(job, index, len(chunks), chunk)},
            ],
            "editing_chunk_summary",
            lambda value: validate_chunk_summary(value, max_timestamp, blocked_ranges),
            1200,
            telemetry,
        )
        summaries.append(result)
        usage_total["tokens"] += int(usage.get("tokens") or 0)
        usage_total["totalTokens"] += int(usage.get("totalTokens") or usage.get("tokens") or 0)
        usage_total["promptTokens"] += int(usage.get("promptTokens") or 0)
        usage_total["completionTokens"] += int(usage.get("completionTokens") or 0)
        usage_total["latencyMs"] += float(usage.get("latencyMs") or 0)
        usage_total["attemptCount"] += int(generation_meta.get("attemptCount") or 0)
        usage_total["validationRetries"] += int(generation_meta.get("validationRetries") or 0)
    return json.dumps(summaries, ensure_ascii=False), usage_total


def _normalize_highlight_segments(segments):
    if not isinstance(segments, list):
        return []

    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            start = max(0.0, float(segment.get("start") or 0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(segment.get("end") or 0)
        except (TypeError, ValueError):
            end = 0.0
        if start < EDITING_INTRO_MIN_START_SECONDS:
            continue
        if end <= start:
            end = start + 5
        duration = end - start
        if duration < 5:
            end = start + 5
        elif duration > 10:
            end = start + 10
        normalized.append({
            **segment,
            "start": round(start, 2),
            "end": round(end, 2),
        })
    return sorted(normalized, key=lambda item: (item.get("start") or 0, item.get("end") or 0))


def _strip_topics_from_publish_copy(value):
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"[ \t]*(?:#[\w\u4e00-\u9fff-]+[ \t]*)+$", "", text).strip()
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and re.fullmatch(r"\s*(?:#[\w\u4e00-\u9fff-]+[\s,，、]*)+\s*", lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _generate_editing_plan(job, segments, telemetry=None):
    """文案生成入口：记录开始 / 完成 / 失败日志，便于在并发线程下定位单次 LLM 调用。"""
    video_label = str(job.get("title") or job.get("videoId") or "-")
    thread_label = threading.current_thread().name
    _logger.info("文案生成开始 : thread = %s | video = %s", thread_label, video_label)
    started_at = time.time()
    result, usage = _generate_editing_plan_impl(job, segments, telemetry)
    _logger.info(
        "文案生成完成 : thread = %s | video = %s | elapsed = %.1fs | tokens = %d",
        thread_label, video_label, time.time() - started_at, int(usage.get("totalTokens") or 0),
    )
    return result, usage


def _generate_editing_plan_impl(job, segments, telemetry=None):
    research_context = youtube_video_research_context(job.get("videoId"))
    job = {**job, **research_context}
    transcript_text = _format_transcript_for_model(segments)
    if not transcript_text.strip():
        raise NoSpeechDetectedError("未识别到可用于剪辑分析的字幕文本。")

    max_timestamp = _max_transcript_seconds(segments)
    blocked_ranges = _unsafe_transcript_ranges(segments)
    compact_text, chunk_usage = _summarize_transcript_chunks(job, transcript_text, max_timestamp, blocked_ranges, telemetry)
    chunk_context = ""
    if chunk_usage:
        chunk_context = "下面是长视频分块后的摘要和候选片段，请基于它们汇总最终剪辑方案。"

    result, usage, generation_meta = _call_editing_contract(
        [
            {"role": "system", "content": _editing_analysis_system_prompt()},
            {"role": "user", "content": _editing_analysis_user_prompt(job, compact_text, chunk_context)},
        ],
        "editing_plan",
        lambda value: validate_editing_plan(value, max_timestamp, blocked_ranges),
        6000,  # editing_plan 输出结构大，需为 reasoning + 完整 JSON 留足空间，2200 会触发截断或空 content
        telemetry,
        soft_validator=lambda value, warnings: validate_editing_plan(
            value, max_timestamp, blocked_ranges, soft_warnings=warnings,
        ),
    )
    if chunk_usage:
        base_tokens = int(usage.get("tokens") or 0)
        usage["tokens"] = base_tokens + int(chunk_usage.get("tokens") or 0)
        usage["totalTokens"] = base_tokens + int(chunk_usage.get("totalTokens") or chunk_usage.get("tokens") or 0)
        usage["promptTokens"] = int(usage.get("promptTokens") or 0) + int(chunk_usage.get("promptTokens") or 0)
        usage["completionTokens"] = int(usage.get("completionTokens") or 0) + int(chunk_usage.get("completionTokens") or 0)
        usage["latencyMs"] = round(float(usage.get("latencyMs") or 0) + float(chunk_usage.get("latencyMs") or 0), 2)
        generation_meta["attemptCount"] += int(chunk_usage.get("attemptCount") or 0)
        generation_meta["validationRetries"] += int(chunk_usage.get("validationRetries") or 0)

    highlight_filter_summary = result.pop("_highlightFilterSummary", {})
    review_warnings = list(generation_meta.get("softWarnings") or [])
    result["publish_copy"] = _strip_topics_from_publish_copy(result.get("publish_copy"))
    result["highlight_segments"] = _normalize_highlight_segments(result.get("highlight_segments"))
    has_explicit_profanity = bool(blocked_ranges)
    result["contentRisk"] = {
        "requiresPublishConfirmation": has_explicit_profanity,
        "categories": ["explicit_profanity"] if has_explicit_profanity else [],
        "excludedHighlightCount": int(highlight_filter_summary.get("blockedByContentRisk") or 0),
        "availableHighlightCount": len(result["highlight_segments"]),
        "message": (
            "检测到转写中含明确粗口，中文字幕已使用 * 替换；原声及英文字幕可能仍含风险，发布前需要人工确认。"
            if has_explicit_profanity else ""
        ),
    }
    if review_warnings:
        result["reviewWarnings"] = review_warnings
        result["contentRisk"]["requiresPublishConfirmation"] = True
        result["contentRisk"]["categories"].append("generated_copy_review")
        result["contentRisk"]["message"] = "生成文案存在待审核表达，视频已处理但发布前需要人工确认。"
    result["process_version"] = PROCESS_VERSION_EDITING
    result["model"] = {
        "provider": usage.get("provider") or "openai-compatible",
        "name": usage.get("model") or TEXT_LLM_MODEL,
    }
    result["generationMeta"] = generation_meta
    return result, usage


def _prepare_editing_transcript(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_editing_work")
    return _get_or_create_transcript(job, source_file, work_dir, progress_base=18, progress_done=46)


def _process_editing_plan(job, source_file, telemetry=None):
    segments, language, transcript_file = _prepare_editing_transcript(job, source_file)
    result, usage = _generate_editing_plan(job, segments, telemetry)
    save_youtube_video_analysis(job.get("videoId"), {
        **result,
        "transcriptLanguage": language or "",
        "transcriptFilePath": str(transcript_file),
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    return result, usage


def _analysis_error_payload(exc, job=None):
    return {
        "summary": "",
        "china_view_angle": "",
        "title_options": [],
        "cover_title_options": [],
        "cover_context": "",
        "publish_copy": "",
        "tags": [],
        "highlight_segments": [],
        "risk_notes": ["内容分析失败，请检查模型配置或稍后重试。"],
        "error": {
            "code": "VF-ANALYSIS-FAILED",
            "type": exc.__class__.__name__,
            "reason": str(exc),
        },
        "process_version": (job or {}).get("processVersion") or PROCESS_VERSION_TRANSLATION,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _run_analysis_from_transcript_job(job, source_file, telemetry=None):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_analysis_work")
    job_id = job.get("id")
    update_youtube_workflow_job(
        job_id,
        status="running",
        step="analysis",
        message="正在复用转写文本生成发布文案",
        source_file_path=str(source_file),
        progress=12,
        speed="",
        eta="",
    )
    update_youtube_video_analysis_status(job.get("videoId"), 2)
    segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir, progress_base=16, progress_done=42)
    update_youtube_workflow_job(
        job_id,
        message="转写文本准备完成，正在调用模型生成标题、文案和标签",
        progress=58,
    )
    result, usage = _generate_editing_plan(job, segments, telemetry)
    result["process_version"] = job.get("processVersion") or PROCESS_VERSION_TRANSLATION
    save_youtube_video_analysis(job.get("videoId"), {
        **result,
        "transcriptLanguage": language or "",
        "transcriptFilePath": str(transcript_file),
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    update_youtube_workflow_job(
        job_id,
        status="success",
        step="done",
        message="发布文案与内容总结已生成",
        progress=100,
        speed="",
        eta="",
    )
    return result, usage


def maybe_start_youtube_analysis_job(base_job, source_file=None, force=False):
    video_id = (base_job or {}).get("videoId") or ""
    if not video_id:
        return None

    init_youtube_workflow_table()
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT analysis_status FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        if not row:
            return None
        analysis_status = int(row["analysis_status"] or 0)
        if analysis_status == 2 or _active_analysis_job_for_video(cursor, video_id):
            return None
        if not force and analysis_status == 1:
            return None

    payload = {
        **base_job,
        "account": "",
        "publishToDouyin": False,
        "publishToBilibili": False,
        "processVersion": base_job.get("processVersion") or PROCESS_VERSION_TRANSLATION,
        "description": base_job.get("description") or "",
        "tags": base_job.get("tags") or [],
        "schedule": "",
    }
    try:
        job = create_youtube_workflow_job(payload, allow_active_job=True, lock_scope="analysis")
    except WorkflowConflictError:
        return None
    update_youtube_video_analysis_status(video_id, 2)
    try:
        _submit_background_task("analysis", run_youtube_analysis_job, job["id"], str(source_file or ""))
    except Exception as exc:
        message = "分析任务提交失败"
        update_youtube_workflow_job(
            job["id"],
            status="failed",
            step="abnormal",
            message=message,
            error_code="VF-WORKFLOW-SUBMIT-FAILED",
            error_type="BACKGROUND_SUBMIT_FAILED",
            error_reason=message,
            error_detail=str(exc),
        )
        update_youtube_video_analysis_status(video_id, 3, {
            "error": {"code": "VF-WORKFLOW-SUBMIT-FAILED", "message": message},
        })
        raise
    return job
