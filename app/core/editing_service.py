def _select_intro_highlight_segments(analysis_result, max_segments=3):
    raw_segments = (analysis_result or {}).get("highlight_segments") or []
    selected = []
    for segment in _normalize_highlight_segments(raw_segments):
        try:
            start = max(0.0, float(segment.get("start") or 0))
            end = max(start + 1, float(segment.get("end") or 0))
        except (TypeError, ValueError):
            continue
        if end - start < 2:
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


def _build_editing_intro_video(job, source_file, processed_file, analysis_result, work_dir):
    segments = _select_intro_highlight_segments(analysis_result, max_segments=3)
    if not segments:
        return {
            "path": Path(processed_file),
            "segments": [],
            "skipped": True,
            "reason": "未找到可用于开头混剪的高光片段",
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

    def encode_clip(input_file, output_clip, start=None, end=None):
        command = [ffmpeg, "-y"]
        if start is not None:
            command.extend(["-ss", f"{start:.3f}"])
        if end is not None and start is not None:
            command.extend(["-t", f"{max(0.5, end - start):.3f}"])
        command.extend(["-i", str(input_file)])
        video_filters = []
        if width and height:
            video_filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "setsar=1",
            ])
        command.extend([
            "-vf", ",".join(video_filters) if video_filters else "setsar=1",
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
        encode_clip(source_file, clip_file, start=segment["start"], end=segment["end"])
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
    return {
        "path": output_file,
        "segments": segments,
        "skipped": False,
        "reason": "",
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


def _extract_json_object(text):
    content = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.S)
    if fenced:
        content = fenced.group(1).strip()
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
    return json.loads(content)


def _call_llm_json(messages, max_tokens=1800):
    if not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY，无法生成处理版本二的剪辑方案。")
    if not LLM_BASE_URL or not LLM_MODEL:
        raise RuntimeError("LLM_BASE_URL 或 LLM_MODEL 未配置，无法生成剪辑方案。")

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    started_at = time.time()

    def request_completion(current_payload):
        request_body = json.dumps(current_payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{LLM_BASE_URL}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        data = request_completion(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "response_format" in payload:
            payload.pop("response_format", None)
            try:
                data = request_completion(payload)
            except urllib.error.HTTPError as retry_exc:
                retry_body = retry_exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"模型接口调用失败 HTTP {retry_exc.code}: {retry_body[:500]}") from retry_exc
        else:
            raise RuntimeError(f"模型接口调用失败 HTTP {exc.code}: {body[:500]}") from exc

    message = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    result = _extract_json_object(message)
    usage = data.get("usage") or {}
    total_tokens = int(usage.get("total_tokens") or 0)
    return result, {
        "provider": "openai-compatible",
        "model": LLM_MODEL,
        "latencyMs": round((time.time() - started_at) * 1000, 2),
        "tokens": total_tokens,
        "totalTokens": total_tokens,
        "promptTokens": int(usage.get("prompt_tokens") or 0),
        "completionTokens": int(usage.get("completion_tokens") or 0),
    }


def _editing_analysis_system_prompt():
    return (
        "你是 Vidferry 的短视频二创剪辑策划助手。"
        "你的任务是基于英文转写和视频元数据，找出适合中文平台二次创作的高光片段。"
        "优先选择外国人明显震惊、惊喜、反差、夸赞中国效率/安全/城市/交通/消费/服务的内容，"
        "尤其关注中外对比、认知反转和可做钩子的片段。"
        "高光片段必须短而明确，每个片段时长控制在 5-10 秒，禁止返回超过 10 秒的片段；"
        "如果原始亮点更长，需要拆分成多个 5-10 秒片段或选取最有冲击力的 5-10 秒。"
        "所有高光片段必须严格按照视频时间轴升序排列，即 start 从小到大输出。"
        "publish_copy 只写正文文案，禁止包含 #话题、标签列表、标题类型话题或 hashtags；"
        "所有话题必须只放在 tags 数组中，因为各平台会以独立字段上传话题。"
        "只输出严格 JSON，不要输出 Markdown。"
    )


def _editing_analysis_user_prompt(job, transcript_text, chunk_context=""):
    metadata = {
        "title": job.get("title") or "",
        "channel": job.get("channel") or "",
        "subscribers": job.get("subscribers") or "",
        "publishedAt": job.get("publishedAt") or "",
        "url": job.get("url") or "",
    }
    return (
        f"视频元数据：{json.dumps(metadata, ensure_ascii=False)}\n"
        f"{chunk_context}\n"
        "请生成处理版本二的剪辑方案。输出 JSON 字段必须包含："
        "summary 字符串；china_view_angle 字符串；title_options 字符串数组；"
        "publish_copy 字符串，必须是不带 #话题/标签的正文文案；tags 字符串数组，单独存放话题；"
        "highlight_segments 数组，每项包含 start 数字秒、end 数字秒、type 字符串、reason 字符串、suggested_caption 字符串；"
        "risk_notes 字符串数组；editing_focus 字符串。"
        "不要在 publish_copy 末尾追加 #中国旅行 #老外看中国 这类话题，也不要把话题写成正文的一部分；"
        "highlight_segments 控制在 5-8 个，优先外国人震惊点和中外对比点；"
        "每个片段 end - start 必须在 5 到 10 秒之间，没有明确时间也要根据转写时间估计；"
        "highlight_segments 必须按 start 从小到大排序，方便后续按时间顺序进行高光剪辑。\n"
        f"转写内容：\n{transcript_text}"
    )


def _summarize_transcript_chunks(job, transcript_text):
    max_chars = max(4000, LLM_MAX_TRANSCRIPT_CHARS)
    chunks = _split_transcript_lines(transcript_text, max_chars)
    if len(chunks) <= 1:
        return transcript_text, None

    summaries = []
    usage_total = {"tokens": 0, "totalTokens": 0, "promptTokens": 0, "completionTokens": 0, "latencyMs": 0}
    for index, chunk in enumerate(chunks, start=1):
        result, usage = _call_llm_json([
            {"role": "system", "content": _editing_analysis_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"这是第 {index}/{len(chunks)} 段转写。请只输出 JSON："
                    "chunk_summary 字符串；highlight_candidates 数组，每项包含 start、end、type、reason、suggested_caption。"
                    "重点找外国人震惊、认知反转、中外对比。\n"
                    f"{chunk}"
                ),
            },
        ], max_tokens=1200)
        summaries.append(result)
        usage_total["tokens"] += int(usage.get("tokens") or 0)
        usage_total["totalTokens"] += int(usage.get("totalTokens") or usage.get("tokens") or 0)
        usage_total["promptTokens"] += int(usage.get("promptTokens") or 0)
        usage_total["completionTokens"] += int(usage.get("completionTokens") or 0)
        usage_total["latencyMs"] += float(usage.get("latencyMs") or 0)
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

    compact_text, chunk_usage = _summarize_transcript_chunks(job, transcript_text)
    chunk_context = ""
    if chunk_usage:
        chunk_context = "下面是长视频分块后的摘要和候选片段，请基于它们汇总最终剪辑方案。"

    result, usage = _call_llm_json([
        {"role": "system", "content": _editing_analysis_system_prompt()},
        {"role": "user", "content": _editing_analysis_user_prompt(job, compact_text, chunk_context)},
    ], max_tokens=2200)
    if chunk_usage:
        base_tokens = int(usage.get("tokens") or 0)
        usage["tokens"] = base_tokens + int(chunk_usage.get("tokens") or 0)
        usage["totalTokens"] = base_tokens + int(chunk_usage.get("totalTokens") or chunk_usage.get("tokens") or 0)
        usage["promptTokens"] = int(usage.get("promptTokens") or 0) + int(chunk_usage.get("promptTokens") or 0)
        usage["completionTokens"] = int(usage.get("completionTokens") or 0) + int(chunk_usage.get("completionTokens") or 0)
        usage["latencyMs"] = round(float(usage.get("latencyMs") or 0) + float(chunk_usage.get("latencyMs") or 0), 2)

    result.setdefault("summary", "")
    result.setdefault("china_view_angle", "")
    result.setdefault("title_options", [])
    result.setdefault("publish_copy", "")
    result["publish_copy"] = _strip_topics_from_publish_copy(result.get("publish_copy"))
    result.setdefault("tags", [])
    result.setdefault("highlight_segments", [])
    result["highlight_segments"] = _normalize_highlight_segments(result.get("highlight_segments"))
    result.setdefault("risk_notes", [])
    result["editing_focus"] = result.get("editing_focus") or "foreigner_shock_and_country_comparison"
    result["process_version"] = PROCESS_VERSION_EDITING
    result["model"] = {
        "provider": usage.get("provider") or "openai-compatible",
        "name": usage.get("model") or LLM_MODEL,
    }
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
    with sqlite3.connect(_db_path()) as conn:
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
    job = create_youtube_workflow_job(payload)
    update_youtube_video_analysis_status(video_id, 2)

    thread = threading.Thread(
        target=run_youtube_analysis_job,
        args=(job["id"], str(source_file or "")),
        daemon=True,
    )
    thread.start()
    return job


