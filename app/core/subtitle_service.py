def _format_ass_timestamp(seconds):
    seconds = max(0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds >= 100:
        secs += 1
        centiseconds = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _escape_ass_text(text):
    return str(text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _extract_audio_for_whisper(source_file, work_dir):
    ffmpeg = _resolve_ffmpeg_command()
    audio_file = Path(work_dir) / f"{Path(source_file).stem}_16k.wav"
    _run_command([
        ffmpeg,
        "-y",
        "-i", str(source_file),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_file),
    ], cwd=BASE_DIR)
    return audio_file


def _get_media_duration_seconds(media_file):
    try:
        with wave.open(str(media_file), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate or 1)
    except Exception:
        return 0


def _get_video_info(media_file):
    ffmpeg = _resolve_ffmpeg_command()
    command = [ffmpeg, "-hide_banner", "-i", str(media_file)]
    result = subprocess.run(command, cwd=str(BASE_DIR), capture_output=True, text=True)
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)

    duration = 0.0
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    width = 1080
    height = 1920
    video_match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})\b", output)
    if video_match:
        width = int(video_match.group(1))
        height = int(video_match.group(2))

    fps = 30.0
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", output)
    if fps_match:
        try:
            fps = float(fps_match.group(1))
        except ValueError:
            fps = 30.0
    if fps <= 0 or fps > 120:
        fps = 30.0

    return {"width": width, "height": height, "duration": duration, "fps": fps}


def _transcribe_audio(audio_file):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("未安装 faster-whisper，请先安装依赖后再执行字幕处理。") from exc

    model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(str(audio_file), beam_size=5, vad_filter=True)
    result = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            result.append({"start": float(segment.start), "end": float(segment.end), "text": text})
    if not result:
        raise NoSpeechDetectedError("未检测到可识别人声，已跳过字幕处理。")
    return result, getattr(info, "language", "")


def _transcript_path(video_id, source_file):
    key = re.sub(r"[^A-Za-z0-9_-]+", "_", video_id or Path(source_file).stem)
    return _ensure_dir(YOUTUBE_TRANSCRIPT_DIR) / f"{key}.json"


def _load_transcript_file(path):
    transcript_path = Path(path or "")
    if not transcript_path.is_file():
        return None
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if not segments:
        return None
    return {
        "segments": segments,
        "language": data.get("language") or "",
        "path": transcript_path,
    }


def _get_or_create_transcript(job, source_file, work_dir, progress_base=10, progress_done=34):
    video_id = job.get("videoId") or ""
    job_id = job.get("id")
    record = _get_youtube_video_record(video_id)
    cached = _load_transcript_file((record or {}).get("transcriptFilePath") or "")
    if cached:
        _update_translate_progress(job_id, progress_done, f"已复用转写缓存，识别到 {len(cached['segments'])} 段字幕")
        return cached["segments"], cached["language"], cached["path"]

    transcript_file = _transcript_path(video_id or job_id, source_file)
    cached = _load_transcript_file(transcript_file)
    if cached:
        update_youtube_video_artifacts(
            video_id,
            transcript_status=1,
            transcript_file_path=str(cached["path"]),
            transcript_language=cached["language"],
        )
        _update_translate_progress(job_id, progress_done, f"已复用转写缓存，识别到 {len(cached['segments'])} 段字幕")
        return cached["segments"], cached["language"], cached["path"]

    _update_translate_progress(job_id, progress_base, "正在提取音频，准备语音识别")
    audio_file = _extract_audio_for_whisper(source_file, work_dir)
    _update_translate_progress(job_id, max(progress_base + 10, 20), "正在进行语音识别，长视频可能需要较久")
    segments, language = _transcribe_audio(audio_file)
    payload = {
        "videoId": video_id,
        "sourceFile": str(source_file),
        "language": language or "",
        "segments": segments,
        "createdAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    transcript_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if video_id:
        update_youtube_video_artifacts(
            video_id,
            transcript_status=1,
            transcript_file_path=str(transcript_file),
            transcript_language=language or "",
        )
    _update_translate_progress(job_id, progress_done, f"已识别 {len(segments)} 段字幕")
    return segments, language, transcript_file


def _translate_segments(segments, target_language=DEFAULT_SUBTITLE_LANGUAGE, job_id=""):
    target_language, language_meta = _subtitle_language_meta(target_language)
    if isinstance(segments, dict):
        job_id = job_id or segments.get("jobId") or ""
        segments = segments.get("segments") or []
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise RuntimeError("未安装 deep-translator，请先安装依赖后再执行字幕翻译。") from exc

    if target_language == "en":
        return [dict(segment, subtitle=segment.get("text") or "") for segment in segments]

    translator = GoogleTranslator(source="auto", target=target_language)
    translated = [dict(segment) for segment in segments]
    batch = []
    batch_indices = []
    total_segments = len(translated)
    translated_count = 0
    batch_number = 0
    max_chars = int(os.environ.get("TRANSLATION_BATCH_MAX_CHARS", "1200") or 1200)
    request_timeout = float(os.environ.get("TRANSLATION_REQUEST_TIMEOUT", "10") or 10)
    fallback_line_limit = int(os.environ.get("TRANSLATION_FALLBACK_LINE_LIMIT", "5") or 5)

    def log(message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"{timestamp} | TRANSLATE | job={job_id or '-'} | {message}", flush=True)

    def translate_text(text):
        import deep_translator.google as google_module

        original_get = google_module.requests.get

        def get_with_timeout(*args, **kwargs):
            kwargs.setdefault("timeout", request_timeout)
            return original_get(*args, **kwargs)

        google_module.requests.get = get_with_timeout
        try:
            return translator.translate(text)
        finally:
            google_module.requests.get = original_get

    def update_translation_progress(message=""):
        if not job_id or not total_segments:
            return
        progress = 34 + min(11, (translated_count / total_segments) * 11)
        _update_translate_progress(
            job_id,
            progress,
            message or f"正在翻译字幕 {translated_count}/{total_segments} 段",
        )

    def flush_batch():
        nonlocal translated_count, batch_number
        if not batch:
            return
        batch_number += 1
        current_batch = batch[:]
        current_indices = batch_indices[:]
        batch_chars = sum(len(item) for item in current_batch)
        log(f"开始翻译批次 {batch_number}: {len(current_batch)} 段, {batch_chars} 字符, timeout={request_timeout}s")
        update_translation_progress(f"正在翻译字幕 {translated_count}/{total_segments} 段，批次 {batch_number}")
        batch_failed = False
        try:
            started_at = time.time()
            translated_text = translate_text("\n".join(current_batch))
            lines = [line.strip() for line in str(translated_text).splitlines()]
            log(f"批次 {batch_number} 翻译完成，用时 {time.time() - started_at:.1f}s")
        except Exception as exc:
            batch_failed = True
            log(f"批次 {batch_number} 翻译失败，准备兜底重试或终止任务: {exc.__class__.__name__}: {exc}")
            lines = []

        if batch_failed:
            if len(current_batch) > fallback_line_limit:
                raise RuntimeError(
                    f"字幕翻译失败，请检查网络或翻译服务。批次 {batch_number} 请求失败，且超过逐段兜底上限。"
                )
            lines = []
            for offset, text in enumerate(current_batch, start=1):
                try:
                    started_at = time.time()
                    line = str(translate_text(text)).strip()
                    log(f"批次 {batch_number} 逐段 {offset}/{len(current_batch)} 完成，用时 {time.time() - started_at:.1f}s")
                    lines.append(line)
                except Exception as exc:
                    log(f"批次 {batch_number} 逐段 {offset}/{len(current_batch)} 失败: {exc.__class__.__name__}: {exc}")
                    raise RuntimeError("字幕翻译失败，请检查网络或翻译服务。") from exc
                translated_count += 1
                update_translation_progress()
        elif len(lines) != len(current_batch):
            log(
                f"批次 {batch_number} 返回行数不匹配: expected={len(current_batch)}, actual={len(lines)}，改为逐段翻译"
            )
            if len(current_batch) > fallback_line_limit:
                log(
                    f"批次 {batch_number} 超过逐段兜底上限 {fallback_line_limit}，终止任务避免生成错误字幕"
                )
                raise RuntimeError(
                    f"字幕翻译失败，请检查网络或翻译服务。批次 {batch_number} 返回行数异常。"
                )
            else:
                lines = []
                for offset, text in enumerate(current_batch, start=1):
                    try:
                        started_at = time.time()
                        line = str(translate_text(text)).strip()
                        log(f"批次 {batch_number} 逐段 {offset}/{len(current_batch)} 完成，用时 {time.time() - started_at:.1f}s")
                        lines.append(line)
                    except Exception as exc:
                        log(f"批次 {batch_number} 逐段 {offset}/{len(current_batch)} 失败: {exc.__class__.__name__}: {exc}")
                        raise RuntimeError("字幕翻译失败，请检查网络或翻译服务。") from exc
                    translated_count += 1
                    update_translation_progress()
        else:
            translated_count += len(current_batch)
            update_translation_progress()
        for offset, index in enumerate(current_indices):
            line = lines[offset] if offset < len(lines) else translated[index].get("text")
            if not str(line or "").strip():
                raise RuntimeError("字幕翻译失败，请检查网络或翻译服务。")
            translated[index]["subtitle"] = line or translated[index]["text"]
        batch.clear()
        batch_indices.clear()

    log(f"开始翻译字幕: {total_segments} 段 -> {language_meta['label']}, batch_max_chars={max_chars}")
    for index, segment in enumerate(segments):
        text = segment["text"]
        if sum(len(item) for item in batch) + len(text) + len(batch) > max_chars:
            flush_batch()
        batch.append(text)
        batch_indices.append(index)
    flush_batch()
    log(f"字幕翻译结束: {translated_count}/{total_segments} 段")
    unchanged_count = sum(
        1
        for segment in translated
        if re.sub(r"\s+", " ", str(segment.get("subtitle") or "").strip()).lower()
        == re.sub(r"\s+", " ", str(segment.get("text") or "").strip()).lower()
    )
    if total_segments and unchanged_count == total_segments:
        raise RuntimeError("字幕翻译失败，请检查网络或翻译服务。")
    if job_id and total_segments:
        _update_translate_progress(job_id, 45, f"{language_meta['label']}字幕处理完成 {translated_count}/{total_segments} 段")
    return translated


def _author_overlay_lines(job):
    return [
        f"博主: {job.get('channel') or job.get('account') or '未知'}",
        f"粉丝: {job.get('subscribers') or '未获取'}",
        f"时间: {job.get('publishedAt') or '未获取'}",
        f"翻译: {_normalize_translator_label(job.get('translatorLabel'))}",
    ]


def _wrap_ass_text(text, max_chars):
    text = str(text or "").strip()
    if not text or len(text) <= max_chars:
        return text
    chunks = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars and char in " ，。！？、,.!?;；:":
            chunks.append(current.strip())
            current = ""
    if current:
        chunks.append(current.strip())
    if len(chunks) <= 1:
        chunks = [text[index:index + max_chars] for index in range(0, len(text), max_chars)]
    return "\n".join(chunks[:3])


def _split_ass_text_to_single_lines(text, max_chars, max_parts=4):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return []
    max_chars = max(8, int(max_chars or 40))
    max_parts = max(1, int(max_parts or 1))
    if len(text) <= max_chars:
        return [text]

    parts = []
    current = ""
    tokens = text.split(" ")
    for token in tokens:
        candidate = f"{current} {token}".strip() if current else token.strip()
        if not current or len(candidate) <= max_chars:
            current = candidate
            continue
        parts.append(current.strip())
        current = token.strip()
        while len(current) > max_chars:
            parts.append(current[:max_chars].strip())
            current = current[max_chars:].strip()
        if len(parts) >= max_parts:
            break
    if current and len(parts) < max_parts:
        parts.append(current.strip())
    return [part for part in parts[:max_parts] if part]


def _build_ass_file(job, segments, ass_file, audio_duration, video_info=None):
    ass_file = Path(ass_file)
    video_info = video_info or {}
    width = max(320, int(video_info.get("width") or 1080))
    height = max(320, int(video_info.get("height") or 1920))
    short_side = min(width, height)
    is_vertical = height > width
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    _, size_config = _subtitle_size_config(job.get("subtitleSize"))
    font_scale = float(size_config.get("scale") or 1)
    subtitle_floor = 56 if is_vertical else 48
    english_floor = 40 if is_vertical else 34
    info_floor = 36 if is_vertical else 30
    subtitle_font_size = int(max(subtitle_floor, min(112, int(short_side * 0.092))) * font_scale)
    english_font_size = int(max(english_floor, min(82, int(short_side * 0.052))) * font_scale)
    info_font_size = int(max(info_floor, min(72, int(short_side * 0.060))) * min(font_scale, 1.14))
    horizontal_margin = max(22, int(width * (0.046 if is_vertical else 0.055)))
    subtitle_margin_v = max(92 if is_vertical else 78, int(height * (0.092 if is_vertical else 0.086)))
    english_margin_v = max(34, int(subtitle_margin_v - english_font_size * 1.38))
    info_margin_v = max(28, int(height * 0.028))
    subtitle_outline = max(4, int(short_side * 0.0065))
    info_outline = max(3, int(short_side * 0.0055))
    subtitle_shadow = max(1, int(short_side * 0.0022))
    max_subtitle_chars = max(8, int(width / max(subtitle_font_size * (0.92 if is_vertical else 0.86), 1)))
    max_english_chars = max(12, int(width / max(english_font_size * (0.62 if is_vertical else 0.55), 1)))
    always_show_english_line = True
    has_translated_line = target_language != "en"

    overlay_text = "\\N".join(_escape_ass_text(line) for line in _author_overlay_lines(job))
    dialogue_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Subtitle,Microsoft YaHei,{subtitle_font_size},&H0000E6FF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{subtitle_outline},{subtitle_shadow},2,{horizontal_margin},{horizontal_margin},{subtitle_margin_v},1",
        f"Style: English,Arial,{english_font_size},&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{subtitle_outline},{subtitle_shadow},2,{horizontal_margin},{horizontal_margin},{english_margin_v},1",
        f"Style: Info,Microsoft YaHei,{info_font_size},&H00FFFFFF,&H000000FF,&H00111111,&H96000000,1,0,0,0,100,100,0,0,1,{info_outline},{subtitle_shadow},7,{horizontal_margin},{horizontal_margin},{info_margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{_format_ass_timestamp(0)},{_format_ass_timestamp(min(20, audio_duration or 20))},Info,,0,0,0,,{overlay_text}",
    ]
    for segment in segments:
        start = _format_ass_timestamp(segment["start"])
        end = _format_ass_timestamp(max(segment["end"], segment["start"] + 0.5))
        english_text = _escape_ass_text(segment.get("text") or "")
        if always_show_english_line and english_text:
            dialogue_lines.append(f"Dialogue: 0,{start},{end},English,,0,0,0,,{english_text}")
        if has_translated_line:
            wrapped_text = _wrap_ass_text(segment.get("subtitle") or "", max_subtitle_chars)
            text = _escape_ass_text(wrapped_text)
            if text:
                dialogue_lines.append(f"Dialogue: 1,{start},{end},Subtitle,,0,0,0,,{text}")
    ass_file.write_text("\n".join(dialogue_lines), encoding="utf-8")
    return ass_file


def _ffmpeg_subtitle_path(path):
    value = Path(path).resolve().as_posix()
    return value.replace(":", "\\:").replace("'", "\\'")


def _compatible_video_dimensions(width, height, max_long_side=1920, max_short_side=1080):
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    if width >= height:
        max_width, max_height = int(max_long_side), int(max_short_side)
    else:
        max_width, max_height = int(max_short_side), int(max_long_side)

    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return None

    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height


def _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=0, job_id=""):
    ffmpeg = _resolve_ffmpeg_command()
    subtitle_filter = f"subtitles='{_ffmpeg_subtitle_path(ass_file)}'"
    output_file = Path(output_file)
    tmp_output_file = output_file.with_name(f"{output_file.stem}.tmp{output_file.suffix}")
    backup_output_file = None
    if tmp_output_file.exists():
        tmp_output_file.unlink()
    if output_file.exists():
        backup_output_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
        if backup_output_file.exists():
            backup_output_file.unlink()
        output_file.replace(backup_output_file)

    job = get_youtube_workflow_job(job_id) or {}
    _, burn_config = _burn_profile_config(job.get("burnProfile"))
    video_info = _get_video_info(source_file)
    output_fps = float(video_info.get("fps") or 30.0)
    max_fps = float(burn_config.get("max_fps") or 60.0)
    if output_fps <= 0 or output_fps > max_fps:
        output_fps = max_fps

    video_filters = [subtitle_filter]
    target_dimensions = _compatible_video_dimensions(
        video_info.get("width"),
        video_info.get("height"),
        burn_config.get("max_long_side", 1920),
        burn_config.get("max_short_side", 1080),
    )
    if target_dimensions:
        target_width, target_height = target_dimensions
        video_filters.append(f"scale={target_width}:{target_height}:flags=lanczos")
        video_filters.append("setsar=1")
    video_filter = ",".join(video_filters)

    command = [
        ffmpeg,
        "-y",
        "-fflags", "+genpts",
        "-i", str(source_file),
        "-vf", video_filter,
        "-fps_mode", "cfr",
        "-r", f"{output_fps:.3f}".rstrip("0").rstrip("."),
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
        "-af", "aresample=async=1:first_pts=0",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(tmp_output_file),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines = []
    last_update = 0

    def read_stderr():
        if not process.stderr:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    if process.stdout:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("out_time_ms=") and duration:
                try:
                    out_seconds = int(line.split("=", 1)[1]) / 1000000
                except ValueError:
                    continue
                now = time.time()
                if now - last_update >= 1:
                    burn_progress = max(0.0, min(1.0, out_seconds / duration))
                    progress = 50 + burn_progress * 48
                    _update_translate_progress(
                        job_id,
                        round(progress, 1),
                        f"FFmpeg 正在烧录字幕 {min(100, burn_progress * 100):.1f}%",
                    )
                    last_update = now

    return_code = process.wait()
    stderr_thread.join(timeout=2)
    if return_code != 0:
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError("\n".join(stderr_lines[-30:]) or "FFmpeg 烧录失败")

    if not tmp_output_file.exists() or tmp_output_file.stat().st_size <= 0:
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成有效临时文件: {tmp_output_file}")

    tmp_output_file.replace(output_file)
    if backup_output_file and backup_output_file.exists():
        backup_output_file.unlink()
    if not output_file.exists() or output_file.stat().st_size <= 0:
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成最终 MP4: {output_file}")
    return output_file


def _download_youtube_video(job):
    download_dir = _ensure_dir(YOUTUBE_DOWNLOAD_DIR)
    video_key = re.sub(r"[^A-Za-z0-9_-]+", "_", job["videoId"] or job["id"])
    output_template = str(download_dir / f"{video_key}.%(ext)s")
    ffmpeg_command = _resolve_ffmpeg_command()
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，请先执行 `uv pip install -e .` 更新依赖。") from exc

    ydl_opts = {
        **_base_ytdlp_opts(),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "writethumbnail": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "quiet": True,
        "no_warnings": False,
        "ffmpeg_location": ffmpeg_command,
        "progress_hooks": [_make_download_progress_hook(job["id"])],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(job["url"], download=True)

    preferred = download_dir / f"{video_key}.mp4"
    if preferred.exists():
        return preferred
    video_file = _find_newest_video_file(download_dir, time.time() - 3600)
    if not video_file:
        raise RuntimeError(f"yt-dlp 已执行，但未在 {download_dir} 找到下载后的视频文件")
    return video_file


def _update_translate_progress(job_id, progress, message, step="subtitle"):
    if not job_id:
        return
    job = get_youtube_workflow_job(job_id) or {}
    if _normalize_process_version(job.get("processVersion")) == PROCESS_VERSION_EDITING and step == "subtitle":
        progress = 60 + (float(progress or 0) * 0.25)
    update_youtube_workflow_job(
        job_id,
        step=step,
        message=message,
        progress=progress,
        speed="",
        eta="",
    )


def _process_subtitles(job, source_file):
    processed_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR)
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    process_version = _normalize_process_version(job.get("processVersion"))
    video_key = job.get("videoId") or job.get("id") or Path(source_file).stem
    output_file = processed_dir / f"{video_key}_{process_version}_{language_meta['suffix']}.mp4"
    job_id = job.get("id")

    if SUBTITLE_COMMAND_TEMPLATE:
        _update_translate_progress(job_id, 10, "正在执行自定义字幕处理命令")
        previous_output_file = None
        if output_file.exists():
            previous_output_file = output_file.with_name(f"{output_file.stem}.previous{output_file.suffix}")
            if previous_output_file.exists():
                previous_output_file.unlink()
            output_file.replace(previous_output_file)
        command = _render_command_template(
            SUBTITLE_COMMAND_TEMPLATE,
            input=str(source_file),
            output=str(output_file),
            video_id=job["videoId"] or job["id"],
        )
        try:
            _run_command(command, cwd=BASE_DIR)
            if not output_file.exists():
                raise RuntimeError(f"字幕处理命令已执行，但未生成文件: {output_file}")
            if previous_output_file and previous_output_file.exists():
                previous_output_file.unlink()
        except Exception:
            if output_file.exists():
                output_file.unlink()
            if previous_output_file and previous_output_file.exists():
                previous_output_file.replace(output_file)
            raise
        _update_translate_progress(job_id, 98, "自定义字幕处理完成，正在保存结果")
        return {"path": output_file, "skipped": False}

    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_work")
    _update_translate_progress(job_id, 6, "正在读取视频信息")
    video_info = _get_video_info(source_file)
    try:
        segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir)
    except NoSpeechDetectedError as exc:
        _replace_file_with_backup(source_file, output_file)
        _update_translate_progress(job_id, 98, str(exc))
        return {"path": output_file, "skipped": True}
    _update_translate_progress(job_id, 34, f"已识别 {len(segments)} 段字幕，正在处理为{language_meta['label']}")
    translated_segments = _translate_segments(segments, target_language, job_id=job_id)
    _update_translate_progress(job_id, 46, f"{language_meta['label']}字幕已生成，正在构建自适应字幕样式")
    duration = video_info.get("duration") or max((segment.get("end") or 0) for segment in segments)
    ass_file = _build_ass_file(job, translated_segments, work_dir / f"{Path(source_file).stem}.ass", duration, video_info)
    _update_translate_progress(job_id, 50, f"正在使用 FFmpeg 烧录{language_meta['label']}字幕")
    result = _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=duration, job_id=job_id)
    _update_translate_progress(job_id, 98, "视频已生成，正在写入素材库")
    return {"path": result, "skipped": False}


