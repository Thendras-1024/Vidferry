"""字幕处理服务:音频提取、Whisper 转写、翻译、ASS 字幕生成与 FFmpeg 烧录。"""

from app.core.llm_harness import redact_profanity
from app.core.subtitle_review import review_translated_segments


# 词级时间戳仅用于把较长转写段拆为可读的短语，不暴露为用户配置。
CUE_SOFT_PAUSE_SECONDS = 0.45
CUE_HARD_PAUSE_SECONDS = 0.8
CUE_MIN_DURATION_SECONDS = 1.2
CUE_TARGET_DURATION_SECONDS = 3.8
CUE_MAX_DURATION_SECONDS = 5.0
CUE_MIN_VISIBLE_WORDS = 2
CUE_MAX_SPACED_CHARS = 42
CUE_MAX_CJK_CHARS = 18


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


def _watermark_enabled(job):
    return bool((job or {}).get("watermarkEnabled"))


def _watermark_text(job):
    return _normalize_watermark_text((job or {}).get("watermarkText")) or DEFAULT_WATERMARK_TEXT


def _watermark_burns_with_subtitles(job):
    return _watermark_enabled(job) and _normalize_process_version(job.get("processVersion")) != PROCESS_VERSION_EDITING


def _subtitle_stage_log(level, message, *args):
    logger = globals().get("backend_logger")
    if logger:
        getattr(logger, level)(message, *args)


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

    has_audio = bool(re.search(r"Stream #.*?: Audio:", output))
    color_info = {}
    video_line_match = re.search(r"Stream #.*?: Video:.*", output)
    video_line = video_line_match.group(0) if video_line_match else ""
    color_triplet = re.search(r",\s*([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)(?:,|\))", video_line, re.IGNORECASE)
    if color_triplet:
        color_info = {
            "space": color_triplet.group(1),
            "primaries": color_triplet.group(2),
            "transfer": color_triplet.group(3),
        }
    elif re.search(r",\s*bt709(?:,|\))", video_line, re.IGNORECASE):
        color_info = {"space": "bt709", "primaries": "bt709", "transfer": "bt709"}
    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "has_audio": has_audio,
        "color": color_info,
    }


def _transcribe_audio(audio_file, progress_callback=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("未安装 faster-whisper，请先安装依赖后再执行字幕处理。") from exc

    model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    if progress_callback:
        progress_callback(f"正在加载 Whisper {model_size} 模型（{device} / {compute_type}）")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(audio_file),
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
    except Exception as exc:
        raise RuntimeError(f"ASR_TRANSCRIPTION_FAILED: {exc.__class__.__name__}") from exc
    result = []
    last_progress_at = 0.0
    try:
        for segment in segments:
            text = segment.text.strip()
            if text:
                words = []
                raw_words = list(getattr(segment, "words", None) or [])
                valid_words = bool(raw_words)
                for word in raw_words:
                    try:
                        value = str(getattr(word, "word", "") or "").strip()
                        start = float(getattr(word, "start", None))
                        end = float(getattr(word, "end", None))
                    except (TypeError, ValueError):
                        valid_words = False
                        break
                    if not value or start < 0 or end <= start:
                        valid_words = False
                        break
                    item = {"word": value, "start": start, "end": end}
                    probability = getattr(word, "probability", None)
                    if probability is not None:
                        try:
                            item["probability"] = float(probability)
                        except (TypeError, ValueError):
                            pass
                    words.append(item)
                result.append({
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                    "words": words if valid_words else [],
                })
            if progress_callback and time.time() - last_progress_at >= 15:
                last_progress_at = time.time()
                progress_callback(f"正在进行语音识别，已识别 {len(result)} 段字幕")
    except Exception as exc:
        raise RuntimeError(f"ASR_TRANSCRIPTION_FAILED: {exc.__class__.__name__}") from exc
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

    _update_translate_progress(job_id, progress_base, "正在提取 16 kHz 单声道音频")
    _subtitle_stage_log("info", "字幕处理阶段开始 : job_id = %s | video_id = %s | stage = audio_extract", job_id or "", video_id or "")
    try:
        audio_file = _extract_audio_for_whisper(source_file, work_dir)
    except Exception as exc:
        _subtitle_stage_log("exception", "字幕处理阶段失败 : job_id = %s | video_id = %s | stage = audio_extract", job_id or "", video_id or "")
        raise RuntimeError(f"AUDIO_EXTRACTION_FAILED: {exc.__class__.__name__}") from exc
    recognition_progress = max(progress_base + 10, 20)
    _update_translate_progress(job_id, recognition_progress, "音频准备完成，正在加载语音识别模型")
    _subtitle_stage_log("info", "字幕处理阶段开始 : job_id = %s | video_id = %s | stage = asr", job_id or "", video_id or "")
    segments, language = _transcribe_audio(
        audio_file,
        progress_callback=lambda message: _update_translate_progress(job_id, recognition_progress, message),
    )
    payload = {
        "schemaVersion": 2,
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
    _subtitle_stage_log(
        "info",
        "字幕处理阶段完成 : job_id = %s | video_id = %s | stage = asr | segments = %s | language = %s",
        job_id or "", video_id or "", len(segments), language or "",
    )
    _update_translate_progress(job_id, progress_done, f"已识别 {len(segments)} 段字幕")
    return segments, language, transcript_file


def _strip_chinese_period(text):
    """翻译后确定性去掉中文句号与全角句点，保证初译无句号；该处理不依赖 LLM 修订。"""
    text = str(text or "")
    return text.replace("。", "").replace("．", "")


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
    max_chars = TRANSLATION_BATCH_MAX_CHARS
    request_timeout = TRANSLATION_REQUEST_TIMEOUT
    fallback_line_limit = TRANSLATION_FALLBACK_LINE_LIMIT

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
            subtitle_text = line or translated[index]["text"]
            if target_language == "zh-CN":
                subtitle_text = _strip_chinese_period(subtitle_text)
            translated[index]["subtitle"] = subtitle_text
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


def _strip_periods_after_review(segments, target_language):
    """修订完成后兜底去句号：防止 LLM 违反提示词产出句号，与 LLM 行为解耦；成本可忽略。"""
    if target_language != "zh-CN":
        return segments
    for segment in segments or []:
        segment["subtitle"] = _strip_chinese_period(segment.get("subtitle"))
    return segments


def _redact_generated_subtitles(segments, target_language):
    if target_language != "zh-CN":
        return segments
    for segment in segments or []:
        segment["subtitle"] = redact_profanity(segment.get("subtitle"))
    return segments


def _author_overlay_lines(job):
    return [
        f"博主: {job.get('channel') or job.get('account') or '未知'}",
        f"粉丝: {job.get('subscribers') or '未获取'}",
        f"时间: {job.get('publishedAt') or '未获取'}",
        f"翻译: {_normalize_translator_label(job.get('translatorLabel'))}",
    ]


def _is_cjk_language(language):
    return str(language or "").lower().startswith(("zh", "ja", "ko"))


def _join_cue_words(words, language):
    values = [str(item.get("word") or "").strip() for item in words]
    values = [value for value in values if value]
    return "".join(values) if _is_cjk_language(language) else " ".join(values)


def _visible_text_length(text):
    return len("".join(str(text or "").split()))


def _valid_segment_words(segment):
    words = []
    previous_end = -1.0
    for raw_word in (segment or {}).get("words") or []:
        if not isinstance(raw_word, dict):
            return []
        try:
            word = str(raw_word.get("word") or "").strip()
            start = float(raw_word.get("start"))
            end = float(raw_word.get("end"))
        except (TypeError, ValueError):
            return []
        if not word or start < 0 or end <= start or start + 0.001 < previous_end:
            return []
        item = {"word": word, "start": start, "end": end}
        if raw_word.get("probability") is not None:
            try:
                item["probability"] = float(raw_word["probability"])
            except (TypeError, ValueError):
                pass
        words.append(item)
        previous_end = end
    return words


def _cue_from_words(words, segment_index, source_text, language):
    if not words:
        return None
    start = float(words[0]["start"])
    end = float(words[-1]["end"])
    return {
        "start": start,
        "end": end,
        "text": _join_cue_words(words, language),
        "sourceSegmentIndex": segment_index,
        "sourceText": source_text,
        "words": words,
    }


def _fallback_subtitle_cue(segment, segment_index):
    start = max(0.0, float(segment.get("start") or 0))
    end = max(float(segment.get("end") or 0), start + 0.5)
    return {
        "start": start,
        "end": end,
        "text": str(segment.get("text") or "").strip(),
        "sourceSegmentIndex": segment_index,
        "sourceText": str(segment.get("text") or "").strip(),
        "words": [],
    }


def _finalize_cue_timings(cues):
    for index, cue in enumerate(cues):
        start = max(0.0, float(cue.get("start") or 0))
        end = max(float(cue.get("end") or 0), start + 0.5)
        next_start = None
        if index + 1 < len(cues):
            next_start = float(cues[index + 1].get("start") or 0)
        if next_start is not None and next_start > start and end > next_start:
            end = next_start
        cue["start"] = start
        cue["end"] = max(end, start + 0.01)
    return cues


def _build_subtitle_cues(segments, language):
    """把 Whisper 原始段落拆为可独立显示的短语时间轴。"""
    cues = []
    max_chars = CUE_MAX_CJK_CHARS if _is_cjk_language(language) else CUE_MAX_SPACED_CHARS
    sentence_endings = ".!?。！？"

    for segment_index, segment in enumerate(segments or []):
        words = _valid_segment_words(segment)
        source_text = str((segment or {}).get("text") or "").strip()
        if not words:
            fallback = _fallback_subtitle_cue(segment or {}, segment_index)
            if fallback["text"]:
                cues.append(fallback)
            continue

        current = []
        for word_index, word in enumerate(words):
            if current and float(word["end"]) - float(current[0]["start"]) > CUE_MAX_DURATION_SECONDS:
                cue = _cue_from_words(current, segment_index, source_text, language)
                if cue and cue["text"]:
                    cues.append(cue)
                current = []
            current.append(word)
            next_word = words[word_index + 1] if word_index + 1 < len(words) else None
            current_text = _join_cue_words(current, language)
            duration = float(current[-1]["end"]) - float(current[0]["start"])
            gap = float(next_word["start"]) - float(current[-1]["end"]) if next_word else 0.0
            sentence_end = current_text.rstrip().endswith(tuple(sentence_endings))
            should_break = (
                not next_word
                or sentence_end
                or gap >= CUE_HARD_PAUSE_SECONDS
                or duration >= CUE_MAX_DURATION_SECONDS
                or _visible_text_length(current_text) >= max_chars
                or (
                    len(current) >= CUE_MIN_VISIBLE_WORDS
                    and duration >= CUE_MIN_DURATION_SECONDS
                    and (gap >= CUE_SOFT_PAUSE_SECONDS or duration >= CUE_TARGET_DURATION_SECONDS)
                )
            )
            if should_break:
                cue = _cue_from_words(current, segment_index, source_text, language)
                if cue and cue["text"]:
                    cues.append(cue)
                current = []
    return _finalize_cue_timings(cues)


def _translation_split_points(text, target_index, minimum, maximum):
    preferred = []
    for index, char in enumerate(text):
        if minimum <= index + 1 <= maximum and char in "，。！？；：、,.!?;:":
            preferred.append(index + 1)
    if preferred:
        return min(preferred, key=lambda point: abs(point - target_index))
    return max(minimum, min(target_index, maximum))


def _allocate_translated_cues(cues, translated_text):
    """按原文短语权重分配整句译文；无法保证每段非空时返回 None。"""
    text = " ".join(str(translated_text or "").split())
    if not cues or not text or _visible_text_length(text) < len(cues):
        return None
    if len(cues) == 1:
        return [text]

    weights = [max(1, _visible_text_length(cue.get("text"))) for cue in cues]
    total_weight = sum(weights)
    parts = []
    cursor = 0
    completed_weight = 0
    for index, weight in enumerate(weights[:-1]):
        completed_weight += weight
        remaining_parts = len(cues) - index - 1
        target = round(len(text) * completed_weight / total_weight)
        split_at = _translation_split_points(
            text,
            target,
            cursor + 1,
            len(text) - remaining_parts,
        )
        part = text[cursor:split_at].strip()
        if not part:
            return None
        parts.append(part)
        cursor = split_at
    final_part = text[cursor:].strip()
    if not final_part:
        return None
    parts.append(final_part)
    return parts


def _split_translated_subtitle(text, max_visible_chars):
    """把超长译文拆成单行短句，优先保留标点作为断句位置。"""
    text = " ".join(str(text or "").split())
    max_visible_chars = max(1, int(max_visible_chars or 1))
    if _visible_text_length(text) <= max_visible_chars:
        return [text] if text else []

    parts = []
    while text:
        visible_chars = 0
        split_at = 0
        punctuation_at = 0
        for index, char in enumerate(text):
            if not char.isspace():
                visible_chars += 1
            if visible_chars > max_visible_chars:
                break
            split_at = index + 1
            if char in "，。！？；：、,.!?;:":
                punctuation_at = split_at
        if punctuation_at and _visible_text_length(text[:punctuation_at]) >= 2:
            split_at = punctuation_at
        if split_at <= 0:
            split_at = 1
        remainder = text[split_at:].strip()
        if _visible_text_length(remainder) == 1 and remainder in "，。！？；：、,.!?;:" and split_at > 1:
            split_at -= 1
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return [part for part in parts if part]


def _source_text_parts(cue, part_weights, language):
    """按译文比例分配英文词；没有足够词时，后续 cue 不重复英文。"""
    count = len(part_weights)
    words = list(cue.get("words") or [])
    if not words:
        return [(str(cue.get("text") or ""), [])] + [("", [])] * (count - 1)
    if len(words) < count:
        return [
            (_join_cue_words(words[index:index + 1], language), words[index:index + 1])
            if index < len(words) else ("", [])
            for index in range(count)
        ]

    total_weight = max(1, sum(part_weights))
    source_parts = []
    cursor = 0
    completed_weight = 0
    for index, weight in enumerate(part_weights):
        completed_weight += weight
        remaining_parts = count - index - 1
        target = round(len(words) * completed_weight / total_weight)
        word_end = min(len(words) - remaining_parts, max(cursor + 1, target)) if cursor < len(words) else cursor
        part_words = words[cursor:word_end]
        source_parts.append((_join_cue_words(part_words, language), part_words))
        cursor = word_end
    return source_parts


def _split_rendered_cue(cue, subtitles, language):
    if len(subtitles) <= 1:
        item = dict(cue)
        item["subtitle"] = subtitles[0] if subtitles else ""
        return [item]

    weights = [max(1, _visible_text_length(subtitle)) for subtitle in subtitles]
    total_weight = sum(weights)
    start = float(cue.get("start") or 0)
    end = max(start, float(cue.get("end") or start))
    duration = end - start
    source_parts = _source_text_parts(cue, weights, language)
    rendered = []
    completed_weight = 0
    for index, (subtitle, weight) in enumerate(zip(subtitles, weights)):
        completed_weight += weight
        item = dict(cue)
        item["start"] = start + duration * (completed_weight - weight) / total_weight
        item["end"] = end if index == len(subtitles) - 1 else start + duration * completed_weight / total_weight
        item["text"], item["words"] = source_parts[index]
        item["subtitle"] = subtitle
        rendered.append(item)
    return rendered


def _assign_translated_cues(cues, translated_segments, language, max_single_line_chars=0):
    """把按原段落翻译的结果可靠地映射回短语 cue。"""
    by_source = {}
    for cue in cues or []:
        by_source.setdefault(cue.get("sourceSegmentIndex"), []).append(cue)

    rendered = []
    for source_index, source_cues in by_source.items():
        source = translated_segments[source_index] if source_index is not None and source_index < len(translated_segments or []) else {}
        translated_text = str(source.get("subtitle") or "").strip()
        active_cues = list(source_cues)
        allocated = _allocate_translated_cues(active_cues, translated_text)

        if not allocated or len(allocated) != len(active_cues):
            print(
                f"字幕译文分配失败，已回退原始段落: segment={source_index}",
                flush=True,
            )
            fallback = _fallback_subtitle_cue(source or (source_cues[0] if source_cues else {}), source_index)
            active_cues = [fallback]
            allocated = [translated_text or fallback["text"]]

        for cue, subtitle in zip(active_cues, allocated):
            subtitles = _split_translated_subtitle(subtitle, max_single_line_chars) if max_single_line_chars else [subtitle]
            rendered.extend(_split_rendered_cue(cue, subtitles, language))
    return rendered


def _subtitle_render_layout(job, video_info):
    video_info = video_info or {}
    width = max(320, int(video_info.get("width") or 1080))
    height = max(320, int(video_info.get("height") or 1920))
    short_side = min(width, height)
    is_vertical = height > width
    _, size_config = _subtitle_size_config(job.get("subtitleSize"))
    font_scale = float(size_config.get("scale") or 1)
    subtitle_floor = 56 if is_vertical else 48
    subtitle_font_size = int(max(subtitle_floor, min(112, int(short_side * 0.092))) * font_scale)
    horizontal_margin = max(22, int(width * (0.046 if is_vertical else 0.055)))
    usable_width = max(1, width - 2 * horizontal_margin)
    single_line_capacity = max(1, int(usable_width / max(subtitle_font_size * 0.92, 1)))
    return {
        "width": width,
        "height": height,
        "shortSide": short_side,
        "isVertical": is_vertical,
        "fontScale": font_scale,
        "subtitleFontSize": subtitle_font_size,
        "horizontalMargin": horizontal_margin,
        "singleLineCapacity": single_line_capacity,
    }


def _build_ass_file(job, segments, ass_file, audio_duration, video_info=None, include_subtitles=True):
    ass_file = Path(ass_file)
    layout = _subtitle_render_layout(job, video_info)
    width = layout["width"]
    height = layout["height"]
    short_side = layout["shortSide"]
    is_vertical = layout["isVertical"]
    target_language, language_meta = _subtitle_language_meta(job.get("subtitleLanguage"))
    font_scale = layout["fontScale"]
    subtitle_font_size = layout["subtitleFontSize"]
    english_floor = 40 if is_vertical else 34
    info_floor = 36 if is_vertical else 30
    english_font_size = int(max(english_floor, min(82, int(short_side * 0.052))) * font_scale)
    info_font_size = int(max(info_floor, min(72, int(short_side * 0.060))) * min(font_scale, 1.14))
    horizontal_margin = layout["horizontalMargin"]
    subtitle_margin_v = max(92 if is_vertical else 78, int(height * (0.092 if is_vertical else 0.086)))
    english_margin_v = max(34, int(subtitle_margin_v - english_font_size * 1.38))
    info_margin_v = max(28, int(height * 0.028))
    subtitle_outline = max(4, int(short_side * 0.0065))
    info_outline = max(3, int(short_side * 0.0055))
    subtitle_shadow = max(1, int(short_side * 0.0022))
    watermark_font_size = max(20, min(54, int(short_side * 0.032)))
    watermark_margin = max(20, int(width * 0.042))
    watermark_margin_v = max(40, int(height * 0.070))
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
        f"Style: Watermark,Microsoft YaHei,{watermark_font_size},&HD9FFFFFF,&H000000FF,&HE6000000,&H00000000,0,0,0,0,100,100,0,-15,1,1,0,9,{watermark_margin},{watermark_margin},{watermark_margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if include_subtitles:
        dialogue_lines.append(f"Dialogue: 1,{_format_ass_timestamp(0)},{_format_ass_timestamp(min(20, audio_duration or 20))},Info,,0,0,0,,{overlay_text}")
        for segment in segments:
            start = _format_ass_timestamp(segment["start"])
            end = _format_ass_timestamp(max(segment["end"], segment["start"] + 0.5))
            english_text = _escape_ass_text(segment.get("text") or "")
            if always_show_english_line and english_text:
                dialogue_lines.append(f"Dialogue: 0,{start},{end},English,,0,0,0,,{english_text}")
            if has_translated_line:
                subtitle_text = " ".join(str(segment.get("subtitle") or "").split())
                text = _escape_ass_text(subtitle_text)
                if text:
                    dialogue_lines.append(f"Dialogue: 1,{start},{end},Subtitle,,0,0,0,,{text}")
    if _watermark_enabled(job) and (not include_subtitles or _watermark_burns_with_subtitles(job)):
        dialogue_lines.append(
            f"Dialogue: 2,{_format_ass_timestamp(0)},{_format_ass_timestamp(max(0.1, audio_duration or 0.1))},Watermark,,0,0,0,,{_escape_ass_text(_watermark_text(job))}"
        )
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

    # 宽高对齐到偶数:FFmpeg 的 libx264 编码 yuv420p 时要求宽高均为偶数
    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height


def _ffmpeg_error_summary(lines):
    tail = [" ".join(str(line).split()) for line in (lines or []) if str(line).strip()][-2:]
    return " | ".join(tail)[:240] or "FFmpeg 未返回错误摘要"


def _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=0, job_id="", progress_label="字幕"):
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
    video_id = job.get("videoId") or ""
    source_size = f"{int(video_info.get('width') or 0)}x{int(video_info.get('height') or 0)}"
    target_size = f"{target_width}x{target_height}" if target_dimensions else source_size
    burn_started_at = time.monotonic()
    _subtitle_stage_log(
        "info",
        "字幕烧录开始 : job_id = %s | video_id = %s | type = %s | duration_seconds = %.1f | source_size = %s | target_size = %s | preset = %s",
        job_id or "", video_id, progress_label, float(duration or video_info.get("duration") or 0),
        source_size, target_size, burn_config["preset"],
    )

    command = [
        ffmpeg,
        "-y",
        "-fflags", "+genpts",
        "-i", str(source_file),
        "-vf", video_filter,
        "-fps_mode", "cfr",
        "-r", f"{output_fps:.3f}".rstrip("0").rstrip("."),
        *video_encode_args(burn_config),
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
                        f"FFmpeg 正在烧录{progress_label} {min(100, burn_progress * 100):.1f}%",
                    )
                    last_update = now

    return_code = process.wait()
    stderr_thread.join(timeout=2)
    elapsed_seconds = time.monotonic() - burn_started_at
    if return_code != 0:
        error_summary = _ffmpeg_error_summary(stderr_lines)
        _subtitle_stage_log(
            "error",
            "字幕烧录失败 : job_id = %s | video_id = %s | type = %s | return_code = %s | elapsed_seconds = %.1f | error = %s",
            job_id or "", video_id, progress_label, return_code, elapsed_seconds, error_summary,
        )
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError("\n".join(stderr_lines[-30:]) or "FFmpeg 烧录失败")

    if not tmp_output_file.exists() or tmp_output_file.stat().st_size <= 0:
        _subtitle_stage_log(
            "error",
            "字幕烧录失败 : job_id = %s | video_id = %s | type = %s | return_code = %s | elapsed_seconds = %.1f | error = 临时输出文件无效",
            job_id or "", video_id, progress_label, return_code, elapsed_seconds,
        )
        if tmp_output_file.exists():
            tmp_output_file.unlink()
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成有效临时文件: {tmp_output_file}")

    tmp_output_file.replace(output_file)
    if backup_output_file and backup_output_file.exists():
        backup_output_file.unlink()
    if not output_file.exists() or output_file.stat().st_size <= 0:
        _subtitle_stage_log(
            "error",
            "字幕烧录失败 : job_id = %s | video_id = %s | type = %s | return_code = %s | elapsed_seconds = %.1f | error = 最终输出文件无效",
            job_id or "", video_id, progress_label, return_code, elapsed_seconds,
        )
        if backup_output_file and backup_output_file.exists() and not output_file.exists():
            backup_output_file.replace(output_file)
        raise RuntimeError(f"FFmpeg 已执行，但未生成最终 MP4: {output_file}")
    _subtitle_stage_log(
        "info",
        "字幕烧录完成 : job_id = %s | video_id = %s | type = %s | elapsed_seconds = %.1f | output_size_mb = %.1f",
        job_id or "", video_id, progress_label, elapsed_seconds, output_file.stat().st_size / 1024 / 1024,
    )
    return output_file


def _apply_watermark_to_mp4(media_file, job):
    if not _watermark_enabled(job):
        return Path(media_file)
    media_file = Path(media_file)
    video_info = _get_video_info(media_file)
    duration = video_info.get("duration") or 0.1
    ass_file = media_file.with_name(f"{media_file.stem}_watermark.ass")
    output_file = media_file.with_name(f"{media_file.stem}.watermarked{media_file.suffix}")
    _build_ass_file(job, [], ass_file, duration, video_info, include_subtitles=False)
    _burn_subtitles_to_mp4(media_file, ass_file, output_file, duration=duration, job_id=job.get("id") or "", progress_label="水印")
    output_file.replace(media_file)
    return media_file


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


def _process_subtitles(job, source_file, telemetry=None, before_burn=None):
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
        if _watermark_burns_with_subtitles(job):
            _update_translate_progress(job_id, 92, "自定义字幕处理完成，正在烧录水印")
            _apply_watermark_to_mp4(output_file, job)
        _update_translate_progress(job_id, 98, "自定义字幕处理完成，正在保存结果")
        return {"path": output_file, "skipped": False}

    work_dir = _ensure_dir(processed_dir / f"{Path(source_file).stem}_work")
    _update_translate_progress(job_id, 6, "正在读取视频信息")
    video_info = _get_video_info(source_file)
    try:
        segments, language, transcript_file = _get_or_create_transcript(job, source_file, work_dir)
    except NoSpeechDetectedError as exc:
        _replace_file_with_backup(source_file, output_file)
        if _watermark_burns_with_subtitles(job):
            _update_translate_progress(job_id, 92, "未检测到人声，正在烧录水印")
            _apply_watermark_to_mp4(output_file, job)
        _update_translate_progress(job_id, 98, str(exc))
        return {"path": output_file, "skipped": True}
    cues = _build_subtitle_cues(segments, language)
    _update_translate_progress(
        job_id,
        34,
        f"已识别 {len(segments)} 段字幕，已切分为 {len(cues)} 条短语，正在处理为{language_meta['label']}",
    )
    try:
        translated_segments = _translate_segments(segments, target_language, job_id=job_id)
    except Exception as exc:
        raise RuntimeError(f"SUBTITLE_TRANSLATION_FAILED: {exc.__class__.__name__}") from exc
    initial_segments = [dict(segment) for segment in translated_segments]
    review_metadata = {}
    translated_segments = review_translated_segments(
        translated_segments,
        target_language,
        job=job,
        job_id=job_id,
        progress_callback=lambda completed, total: _update_translate_progress(
            job_id,
            45,
            f"正在修订中文字幕 {completed}/{total} 段",
        ),
        telemetry=telemetry,
        review_metadata=review_metadata,
    )
    if review_metadata.get("fallbackCount"):
        review_metadata["status"] = "partial_fallback"
    save_subtitle_audit_snapshot(
        job,
        initial_segments,
        [dict(segment) for segment in translated_segments],
        review_metadata,
    )
    translated_segments = _strip_periods_after_review(translated_segments, target_language)
    translated_segments = _redact_generated_subtitles(translated_segments, target_language)
    if target_language == "en":
        rendered_segments = cues
    else:
        rendered_segments = _assign_translated_cues(
            cues,
            translated_segments,
            language,
            max_single_line_chars=(
                _subtitle_render_layout(job, video_info)["singleLineCapacity"]
                if target_language == "zh-CN" else 0
            ),
        )
    _update_translate_progress(job_id, 46, f"{language_meta['label']}字幕已生成，正在构建自适应字幕样式")
    duration = video_info.get("duration") or max((segment.get("end") or 0) for segment in segments)
    ass_file = _build_ass_file(job, rendered_segments, work_dir / f"{Path(source_file).stem}.ass", duration, video_info)
    _update_translate_progress(job_id, 50, f"正在使用 FFmpeg 烧录{language_meta['label']}字幕")
    if before_burn:
        before_burn(ass_file)
    try:
        result = _burn_subtitles_to_mp4(source_file, ass_file, output_file, duration=duration, job_id=job_id)
    except Exception as exc:
        raise RuntimeError(f"SUBTITLE_BURN_FAILED: {exc.__class__.__name__}") from exc
    _update_translate_progress(job_id, 98, "视频已生成，正在写入素材库")
    return {"path": result, "skipped": False}


