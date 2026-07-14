"""处理版本二的剪辑增强:高光片段开头混剪与「Up Next」覆盖层生成。"""


from app.core.llm_harness import LLMContractError, call_json_contract, contains_profanity, validate_chunk_summary, validate_editing_plan
from app.core import llm_prompts


EDITING_INTRO_MIN_START_SECONDS = 30


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
    # 处理版本二核心:截取前 3 个高光片段作开头(带 Up Next 覆盖层),与正片重新归一化后拼接
    segments = _select_intro_highlight_segments(analysis_result, max_segments=3)
    if not segments:
        output_file = Path(processed_file)
        watermarked = False
        if _watermark_enabled(job):
            _apply_watermark_to_mp4(output_file, job)
            watermarked = True
        return {
            "path": output_file,
            "segments": [],
            "skipped": True,
            "reason": "未找到可用于开头混剪的高光片段",
            "watermarked": watermarked,
        }

    job_id = job.get("id")
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
    output_file = Path(processed_file)
    clip_files = []
    normalized_main = work_dir / f"{output_file.stem}_main_normalized.mp4"
    final_tmp = work_dir / f"{output_file.stem}_editing_concat.mp4"
    concat_file = work_dir / f"{output_file.stem}_concat.txt"

    overlay_ass_file = work_dir / f"{output_file.stem}_up_next_overlay.ass"

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
            "-c:v", "libx264",
            "-preset", burn_config["preset"],
            "-crf", burn_config["crf"],
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

    _update_translate_progress(job_id, 86, "处理版本二：正在截取前三个高光片段", step="editing")
    for index, segment in enumerate(segments, start=1):
        clip_file = work_dir / f"{output_file.stem}_intro_{index}.mp4"
        encode_clip(processed_file, clip_file, start=segment["start"], end=segment["end"], is_intro_clip=True)
        clip_files.append(clip_file)

    _update_translate_progress(job_id, 91, "处理版本二：正在拼接高光开头与正片", step="editing")
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
    watermarked = False
    if _watermark_enabled(job):
        _update_translate_progress(job_id, 95, "处理版本二：正在烧录水印", step="editing")
        _apply_watermark_to_mp4(output_file, job)
        watermarked = True
    return {
        "path": output_file,
        "segments": segments,
        "skipped": False,
        "reason": "",
        "watermarked": watermarked,
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


def _call_editing_contract(messages, contract_id, validator, max_tokens):
    return call_json_contract(
        messages=messages,
        contract_id=contract_id,
        validator=validator,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
        temperature=0.4,
        max_tokens=max_tokens,
        prompt_version=llm_prompts.EDITING_PROMPT_VERSION,
    )


def _editing_analysis_system_prompt():
    return llm_prompts.editing_analysis_system_prompt()


def _editing_analysis_user_prompt(job, transcript_text, chunk_context=""):
    return llm_prompts.build_editing_analysis_prompt(job, transcript_text, chunk_context)


def _summarize_transcript_chunks(job, transcript_text, max_timestamp, blocked_ranges):
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
                {"role": "user", "content": llm_prompts.build_chunk_summary_prompt(index, len(chunks), chunk)},
            ],
            "editing_chunk_summary",
            lambda value: validate_chunk_summary(value, max_timestamp, blocked_ranges),
            1200,
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


def _generate_editing_plan(job, segments):
    transcript_text = _format_transcript_for_model(segments)
    if not transcript_text.strip():
        raise NoSpeechDetectedError("未识别到可用于剪辑分析的字幕文本。")

    max_timestamp = _max_transcript_seconds(segments)
    blocked_ranges = _unsafe_transcript_ranges(segments)
    compact_text, chunk_usage = _summarize_transcript_chunks(job, transcript_text, max_timestamp, blocked_ranges)
    chunk_context = ""
    if chunk_usage:
        chunk_context = "下面是长视频分块后的摘要和候选片段，请基于它们汇总最终剪辑方案。"

    minimum_highlights = 6 if _normalize_process_version(job.get("processVersion")) == PROCESS_VERSION_EDITING else 0
    try:
        result, usage, generation_meta = _call_editing_contract(
            [
                {"role": "system", "content": _editing_analysis_system_prompt()},
                {"role": "user", "content": _editing_analysis_user_prompt(job, compact_text, chunk_context)},
            ],
            "editing_plan",
            lambda value: validate_editing_plan(value, max_timestamp, blocked_ranges, minimum_highlights),
            2200,
        )
    except LLMContractError as exc:
        if minimum_highlights and any("可用安全高光不足" in item for item in exc.violations):
            raise RuntimeError("可用安全高光不足 6 条，请人工检查转写内容或重新生成剪辑方案。") from exc
        raise
    if chunk_usage:
        base_tokens = int(usage.get("tokens") or 0)
        usage["tokens"] = base_tokens + int(chunk_usage.get("tokens") or 0)
        usage["totalTokens"] = base_tokens + int(chunk_usage.get("totalTokens") or chunk_usage.get("tokens") or 0)
        usage["promptTokens"] = int(usage.get("promptTokens") or 0) + int(chunk_usage.get("promptTokens") or 0)
        usage["completionTokens"] = int(usage.get("completionTokens") or 0) + int(chunk_usage.get("completionTokens") or 0)
        usage["latencyMs"] = round(float(usage.get("latencyMs") or 0) + float(chunk_usage.get("latencyMs") or 0), 2)
        generation_meta["attemptCount"] += int(chunk_usage.get("attemptCount") or 0)
        generation_meta["validationRetries"] += int(chunk_usage.get("validationRetries") or 0)

    result["publish_copy"] = _strip_topics_from_publish_copy(result.get("publish_copy"))
    result["highlight_segments"] = _normalize_highlight_segments(result.get("highlight_segments"))
    result["process_version"] = PROCESS_VERSION_EDITING
    result["model"] = {
        "provider": usage.get("provider") or "openai-compatible",
        "name": usage.get("model") or LLM_MODEL,
    }
    result["generationMeta"] = generation_meta
    return result, usage


def _process_editing_plan(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_editing_work")
    job_id = job.get("id")
    update_youtube_workflow_job(
        job_id,
        step="analysis",
        message="处理版本二：正在准备转写与高光片段分析",
        progress=12,
        speed="",
        eta="",
    )
    segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir, progress_base=18, progress_done=46)
    update_youtube_workflow_job(
        job_id,
        step="analysis",
        message="转写完成，正在生成剪辑方案",
        progress=58,
    )
    result, usage = _generate_editing_plan(job, segments)
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


def _run_analysis_from_transcript_job(job, source_file):
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
    result, usage = _generate_editing_plan(job, segments)
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
        if not force and analysis_status in {1, 2}:
            return None
        if not force and _active_analysis_job_for_video(cursor, video_id):
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

    _submit_background_task("analysis", run_youtube_analysis_job, job["id"], str(source_file or ""))
    return job
