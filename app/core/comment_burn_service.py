"""处理版本二的 YouTube 评论抓取、筛选、翻译与烧制素材准备。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as _comment_datetime, timezone as _comment_timezone
from pathlib import Path

from app.config import LLM_TIMEOUT, TEXT_LLM_API_KEY, TEXT_LLM_BASE_URL, TEXT_LLM_MODEL
from app.core import llm_prompts
from app.core.llm_harness import call_json_contract, contains_profanity


_logger = logging.getLogger("vidferry.backend")

COMMENT_BURN_VERSION = 4
COMMENT_LIMIT = 100
COMMENT_SELECTED_LIMIT = 20
COMMENT_SCREEN_BATCH_SIZE = 20
COMMENT_SCREEN_SELECTED_LIMIT = 5
COMMENT_SCREEN_CONCURRENCY = 2
COMMENT_SCREEN_TIMEOUT_SECONDS = min(LLM_TIMEOUT, 60)
COMMENT_AVATAR_DOWNLOAD_CONCURRENCY = 4
COMMENT_START_SECONDS = 25
COMMENT_DURATION_SECONDS = 11
COMMENT_GAP_SECONDS = 5
_URL_ONLY_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
_EMOJI_SHORTCODE_RE = re.compile(r":[a-z0-9][a-z0-9_-]*:", re.I)
_LOW_INFORMATION_RE = re.compile(
    r"^(?:wow+|omg+|lol+|lmao+|haha+|ha+|哇+|哇哦+|哇塞+|哈哈+|呵呵+|厉害+|牛+|棒+|大?赞+|대박+|헐+|와+|와우+)[!！?？~*…。.、\s]*$",
    re.I,
)
_TEXT_RE = re.compile(r"[A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]")
_HAN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff]")
_NON_CHINESE_LETTER_RE = re.compile(r"[A-Za-z\uac00-\ud7af\u0400-\u04ff]")
# Keep this deliberately narrow. Single characters are too ambiguous to reject a comment.
_COMMENT_PROFANITY_RE = re.compile(
    r"\b(?:motherfuck(?:er|ers|ing|ed)?|fuck(?:ing|ed|er|ers|s)?|bullshit|"
    r"shit(?:ty|ting|ted|s)?|bitch(?:es|y)?|assholes?)\b"
    r"|(?:操你妈|他妈的|傻逼|煞笔|草泥马|妈的|滚开|去死)",
    re.IGNORECASE,
)


def comment_burn_signature(job):
    payload = {
        "version": COMMENT_BURN_VERSION,
        "promptVersion": llm_prompts.COMMENT_BURN_PROMPT_VERSION,
        "videoId": str((job or {}).get("videoId") or ""),
        "url": str((job or {}).get("url") or ""),
        "translationMode": str((job or {}).get("commentTranslationMode") or "google_llm"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _comment_text(value):
    return " ".join(str(value or "").split()).strip()


def _comment_like_count(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _comment_time_text(item):
    try:
        return _comment_datetime.fromtimestamp(int((item or {}).get("timestamp")), _comment_timezone.utc).strftime("%Y-%m-%d")
    except (OSError, OverflowError, TypeError, ValueError):
        return _comment_text((item or {}).get("_time_text"))[:40]


def _comment_rejection_reason(item):
    if not isinstance(item, dict):
        return "评论数据格式无效"
    comment_id = str(item.get("id") or "").strip()
    author = _comment_text(item.get("author"))[:80]
    text = _comment_text(item.get("text"))
    if not comment_id:
        return "缺少评论标识"
    if not author or not text:
        return "评论信息不完整"
    if len(text) > 500:
        return "评论内容超过 500 字符"
    if _URL_ONLY_RE.fullmatch(text):
        return "纯链接评论"
    if not _TEXT_RE.search(text):
        return "无有效文本"
    if _EMOJI_SHORTCODE_RE.search(text):
        return "包含未解析 Emoji 短码"
    if _LOW_INFORMATION_RE.fullmatch(text):
        return "仅包含低信息语气词或感叹词"
    if _COMMENT_PROFANITY_RE.search(text):
        return "命中严格脏话规则"
    return ""


def _comment_candidate(item):
    if _comment_rejection_reason(item):
        return None
    if not isinstance(item, dict):
        return None
    comment_id = str(item.get("id") or "").strip()
    author = _comment_text(item.get("author"))[:80]
    text = _comment_text(item.get("text"))
    if not comment_id or not author or not text or len(text) > 500:
        return None
    if _URL_ONLY_RE.fullmatch(text) or not _TEXT_RE.search(text) or _COMMENT_PROFANITY_RE.search(text):
        return None
    return {
        "id": comment_id,
        "author": author,
        "text": text,
        "likeCount": _comment_like_count(item.get("like_count")),
        "timeText": _comment_time_text(item),
        "authorThumbnail": str(item.get("author_thumbnail") or "").strip(),
        "authorIsVerified": bool(item.get("author_is_verified")),
        "authorIsUploader": bool(item.get("author_is_uploader")),
        "isFavorited": bool(item.get("is_favorited")),
    }


def _comment_review_item(raw, index):
    raw = raw if isinstance(raw, dict) else {}
    text = _comment_text(raw.get("text"))
    return {
        "id": str(raw.get("id") or f"source-{index + 1}").strip(),
        "author": _comment_text(raw.get("author"))[:80] or "未知用户",
        "text": text[:500],
        "likeCount": _comment_like_count(raw.get("like_count")),
        "timeText": _comment_time_text(raw),
        "status": "pending",
        "filterReason": "等待筛选",
        "translationRequired": False,
        "translationZh": "",
    }


def normalize_comment_candidates(raw_comments, limit=COMMENT_LIMIT, stats=None, review_items=None):
    seen_texts, result = set(), []
    regex_filtered = 0
    for index, raw in enumerate((raw_comments or [])[:max(1, int(limit or COMMENT_LIMIT))]):
        review_item = _comment_review_item(raw, index)
        rejection_reason = _comment_rejection_reason(raw)
        if rejection_reason in {"包含未解析 Emoji 短码", "仅包含低信息语气词或感叹词", "命中严格脏话规则"}:
            regex_filtered += 1
        candidate = _comment_candidate(raw)
        if not candidate:
            review_item.update(status="rejected", filterReason=_comment_rejection_reason(raw))
            if isinstance(review_items, list):
                review_items.append(review_item)
            continue
        dedupe_key = candidate["text"].casefold()
        if dedupe_key in seen_texts:
            review_item.update(status="rejected", filterReason="与前序评论重复")
            if isinstance(review_items, list):
                review_items.append(review_item)
            continue
        seen_texts.add(dedupe_key)
        result.append(candidate)
        if isinstance(review_items, list):
            review_items.append(review_item)
    if isinstance(stats, dict):
        stats.update({"fetchedCount": len(raw_comments or []), "regexFilteredCount": regex_filtered, "candidateCount": len(result)})
    return result


def fetch_youtube_comment_candidates(url, stats=None, review_items=None):
    options_builder = globals().get("_base_ytdlp_opts")
    if not callable(options_builder):
        raise RuntimeError("yt-dlp 运行时尚未初始化")
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("yt-dlp 未安装") from exc
    options = options_builder()
    options.update({
        "skip_download": True,
        "getcomments": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {
                "comment_sort": ["top"],
                "max_comments": [str(COMMENT_LIMIT)],
            },
        },
    })
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return normalize_comment_candidates(info.get("comments") or [], stats=stats, review_items=review_items)


def _is_chinese_comment(text):
    value = str(text or "")
    if _JAPANESE_RE.search(value):
        return False
    han_count = len(_HAN_RE.findall(value))
    return han_count >= 2 and han_count >= len(_NON_CHINESE_LETTER_RE.findall(value))


def _validate_comment_review(value, candidates):
    if not isinstance(value, dict) or set(value) != {"comments"}:
        raise ValueError("评论筛选结果字段不合法")
    items = value.get("comments")
    if not isinstance(items, list) or len(items) > COMMENT_SELECTED_LIMIT:
        raise ValueError("评论筛选数量不合法")
    candidates_by_id = {item["id"]: item for item in candidates}
    selected, seen = [], set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {"id", "translationRequired", "translationZh"}:
            raise ValueError(f"comments[{index}] 字段不合法")
        comment_id = str(item.get("id") or "").strip()
        if comment_id not in candidates_by_id or comment_id in seen:
            raise ValueError(f"comments[{index}].id 不合法")
        required = item.get("translationRequired")
        translation = _comment_text(item.get("translationZh"))
        if not isinstance(required, bool):
            raise ValueError(f"comments[{index}].translationRequired 必须是布尔值")
        original = candidates_by_id[comment_id]
        if _is_chinese_comment(original["text"]):
            required, translation = False, ""
        elif not required or not translation or len(translation) > 280 or contains_profanity(translation):
            raise ValueError(f"comments[{index}] 翻译不合法")
        selected.append({
            **original,
            "translationRequired": required,
            "translationZh": translation if required else "",
        })
        seen.add(comment_id)
    return selected


def _validate_comment_screen(value, candidates):
    if not isinstance(value, dict) or set(value) != {"comments"}:
        raise ValueError("评论初筛结果字段不合法")
    known, seen, selected = {item["id"]: item for item in candidates}, set(), []
    for index, item in enumerate(value.get("comments") or []):
        if not isinstance(item, dict) or set(item) != {"id", "score"}:
            raise ValueError(f"comments[{index}] 字段不合法")
        comment_id = str(item.get("id") or "").strip()
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            raise ValueError(f"comments[{index}].score 不合法") from None
        if comment_id not in known or comment_id in seen or not 0 <= score <= 100:
            raise ValueError(f"comments[{index}] 不合法")
        selected.append({**known[comment_id], "_score": round(score, 2)})
        seen.add(comment_id)
    if len(selected) > COMMENT_SCREEN_SELECTED_LIMIT:
        raise ValueError("评论初筛数量超过限制")
    return selected


def _validate_comment_selection(value, candidates):
    if not isinstance(value, dict) or set(value) != {"comments"}:
        raise ValueError("评论最终筛选结果字段不合法")
    known, seen, selected = {item["id"]: item for item in candidates}, set(), []
    for index, item in enumerate(value.get("comments") or []):
        if not isinstance(item, dict) or set(item) != {"id"}:
            raise ValueError(f"comments[{index}] 字段不合法")
        comment_id = str(item.get("id") or "").strip()
        if comment_id not in known or comment_id in seen:
            raise ValueError(f"comments[{index}].id 不合法")
        selected.append(dict(known[comment_id]))
        seen.add(comment_id)
    if len(selected) > COMMENT_SELECTED_LIMIT:
        raise ValueError("评论最终筛选数量超过限制")
    return selected


def _empty_usage():
    return {"tokens": 0, "totalTokens": 0, "promptTokens": 0, "completionTokens": 0, "latencyMs": 0}


def _add_usage(total, usage):
    for key in ("tokens", "totalTokens", "promptTokens", "completionTokens"):
        total[key] += int((usage or {}).get(key) or 0)
    total["latencyMs"] += float((usage or {}).get("latencyMs") or 0)


def _screen_comment_batch(job, candidates, telemetry=None):
    result, usage, metadata = call_json_contract(
        messages=[
            {"role": "system", "content": llm_prompts.comment_screen_system_prompt()},
            {"role": "user", "content": llm_prompts.build_comment_screen_prompt(job, candidates)},
        ],
        contract_id="comment_screen",
        validator=lambda value: _validate_comment_screen(value, candidates),
        model=TEXT_LLM_MODEL,
        api_key=TEXT_LLM_API_KEY,
        base_url=TEXT_LLM_BASE_URL,
        timeout=COMMENT_SCREEN_TIMEOUT_SECONDS,
        temperature=0.1,
        max_tokens=600,
        prompt_version=llm_prompts.COMMENT_BURN_PROMPT_VERSION,
        telemetry=telemetry,
    )
    return result, usage, metadata


def _translate_comment_batch(comments):
    translator = globals().get("_translate_segments")
    if not callable(translator):
        from app.core.subtitle_service import _translate_segments as translator
    segments = [{"text": item["text"]} for item in comments]
    translated = translator(segments, "zh-CN")
    if len(translated) != len(comments):
        raise RuntimeError("评论初译数量不匹配")
    return [str(item.get("subtitle") or "").strip() for item in translated]


def _translate_selected_comments(job, comments, telemetry=None):
    translated, foreign = [], [item for item in comments if not _is_chinese_comment(item.get("text"))]
    translations, google_failed, google_failed_ids = {}, 0, []
    _logger.info("评论翻译开始 job_id=%s selected=%s foreign=%s mode=%s", job.get("id") or "", len(comments), len(foreign), job.get("commentTranslationMode") or "google_llm")
    for index in range(0, len(foreign), 5):
        batch = foreign[index:index + 5]
        try:
            for item, text in zip(batch, _translate_comment_batch(batch)):
                if text:
                    translations[item["id"]] = text
                else:
                    google_failed += 1
                    google_failed_ids.append(item["id"])
            _logger.info("评论 Google 初译完成 job_id=%s batch=%s/%s translated=%s", job.get("id") or "", index // 5 + 1, (len(foreign) + 4) // 5, len(batch))
        except Exception as exc:
            google_failed += len(batch)
            google_failed_ids.extend(item["id"] for item in batch)
            _logger.warning("评论 Google 初译失败 job_id=%s batch=%s/%s error=%s: %s", job.get("id") or "", index // 5 + 1, (len(foreign) + 4) // 5, exc.__class__.__name__, str(exc)[:160])
    review_metadata = {}
    if translations and job.get("commentTranslationMode") == "google_llm":
        reviewer = globals().get("review_translated_segments")
        if not callable(reviewer):
            from app.core.subtitle_review import review_translated_segments as reviewer
        review_input = [{"text": item["text"], "subtitle": translations[item["id"]]} for item in foreign if item["id"] in translations]
        try:
            reviewed = reviewer(review_input, "zh-CN", job=job, job_id=job.get("id") or "", telemetry=telemetry, review_metadata=review_metadata)
            for item, reviewed_item in zip((item for item in foreign if item["id"] in translations), reviewed):
                translations[item["id"]] = str(reviewed_item.get("subtitle") or translations[item["id"]]).strip()
            _logger.info("评论 LLM 修订完成 job_id=%s translated=%s fallback=%s", job.get("id") or "", len(translations), int(review_metadata.get("fallbackCount") or 0))
        except Exception as exc:
            review_metadata["fallbackCount"] = len(translations)
            _logger.warning("评论 LLM 修订失败，保留 Google 初译 job_id=%s translated=%s error=%s: %s", job.get("id") or "", len(translations), exc.__class__.__name__, str(exc)[:160])
    for item in comments:
        if _is_chinese_comment(item.get("text")):
            translated.append({**item, "translationRequired": False, "translationZh": ""})
        elif translations.get(item["id"]):
            translated.append({**item, "translationRequired": True, "translationZh": translations[item["id"]]})
    _logger.info("评论翻译结束 job_id=%s burned=%s google_failed=%s llm_fallback=%s", job.get("id") or "", len(translated), google_failed, int(review_metadata.get("fallbackCount") or 0))
    return translated, {
        "googleFailedCount": google_failed,
        "googleFailedIds": google_failed_ids,
        "llmFallbackCount": int(review_metadata.get("fallbackCount") or 0),
    }


def build_comment_review_items(review_items, generation_meta, comments):
    generation_meta = generation_meta or {}
    selected_ids = set(generation_meta.get("selectedIds") or [])
    screened_ids = set(generation_meta.get("screenedIds") or [])
    failed_batch_ids = set(generation_meta.get("failedBatchIds") or [])
    google_failed_ids = set((generation_meta.get("translation") or {}).get("googleFailedIds") or [])
    burned_by_id = {str(item.get("id") or ""): item for item in comments or []}
    result = []
    for original in review_items or []:
        item = dict(original)
        comment_id = str(item.get("id") or "")
        if item.get("status") == "rejected":
            result.append(item)
            continue
        burned = burned_by_id.get(comment_id)
        if burned:
            item.update(status="selected", filterReason="已选中并可烧制", translationRequired=bool(burned.get("translationRequired")), translationZh=str(burned.get("translationZh") or ""))
        elif comment_id in google_failed_ids:
            item.update(status="rejected", filterReason="Google 初译失败，无法烧制")
        elif comment_id in selected_ids:
            item.update(status="rejected", filterReason="翻译未生成，无法烧制")
        elif comment_id in screened_ids:
            item.update(status="rejected", filterReason="最终筛选未入选")
        elif comment_id in failed_batch_ids:
            item.update(status="rejected", filterReason="初筛批次失败")
        else:
            item.update(status="rejected", filterReason="初筛未入选")
        result.append(item)
    return result


def review_youtube_comment_candidates(job, candidates, telemetry=None):
    candidates = list(candidates or [])[:COMMENT_LIMIT]
    batches = [candidates[index:index + COMMENT_SCREEN_BATCH_SIZE] for index in range(0, len(candidates), COMMENT_SCREEN_BATCH_SIZE)]
    if not batches:
        raise RuntimeError("没有可筛选评论")
    usage = _empty_usage()
    _logger.info("评论初筛开始 job_id=%s candidates=%s batches=%s concurrency=%s", job.get("id") or "", len(candidates), len(batches), min(COMMENT_SCREEN_CONCURRENCY, len(batches)))
    screened_batches = [[] for _ in batches]
    batch_details = [{} for _ in batches]
    with ThreadPoolExecutor(max_workers=min(COMMENT_SCREEN_CONCURRENCY, len(batches)), thread_name_prefix="comment-screen") as executor:
        futures = {executor.submit(_screen_comment_batch, job, batch, telemetry): index for index, batch in enumerate(batches)}
        for future in as_completed(futures):
            index = futures[future]
            batch = batches[index]
            try:
                selected, batch_usage, _ = future.result()
                screened_batches[index] = selected
                _add_usage(usage, batch_usage)
                batch_details[index] = {"status": "success", "candidateCount": len(batch), "selectedCount": len(selected)}
                _logger.info("评论初筛批次完成 job_id=%s batch=%s/%s candidates=%s selected=%s", job.get("id") or "", index + 1, len(batches), len(batch), len(selected))
            except Exception as exc:
                batch_details[index] = {"status": "failed", "candidateCount": len(batch), "reason": str(exc)[:160]}
                _logger.warning("评论初筛批次失败 job_id=%s batch=%s/%s candidates=%s error=%s: %s", job.get("id") or "", index + 1, len(batches), len(batch), exc.__class__.__name__, str(exc)[:160])
    screened = [item for batch in screened_batches for item in batch]
    if not screened:
        raise RuntimeError("所有评论初筛批次均失败")
    try:
        _logger.info("评论最终筛选开始 job_id=%s screened=%s", job.get("id") or "", len(screened))
        result, final_usage, _ = call_json_contract(
            messages=[
                {"role": "system", "content": llm_prompts.comment_selection_system_prompt()},
                {"role": "user", "content": llm_prompts.build_comment_selection_prompt(job, screened)},
            ],
            contract_id="comment_selection",
            validator=lambda value: _validate_comment_selection(value, screened),
            model=TEXT_LLM_MODEL, api_key=TEXT_LLM_API_KEY, base_url=TEXT_LLM_BASE_URL,
            timeout=LLM_TIMEOUT, temperature=0.1, max_tokens=500,
            prompt_version=llm_prompts.COMMENT_BURN_PROMPT_VERSION, telemetry=telemetry,
        )
        _add_usage(usage, final_usage)
        final_fallback = False
        _logger.info("评论最终筛选完成 job_id=%s selected=%s", job.get("id") or "", len(result))
    except Exception as exc:
        result = [dict(item) for item in sorted(screened, key=lambda item: item["_score"], reverse=True)[:COMMENT_SELECTED_LIMIT]]
        final_fallback = True
        _logger.warning("评论最终筛选失败，按初筛评分回退 job_id=%s selected=%s error=%s: %s", job.get("id") or "", len(result), exc.__class__.__name__, str(exc)[:160])
    selected = [{key: value for key, value in item.items() if key != "_score"} for item in result]
    comments, translation_meta = _translate_selected_comments(job, selected, telemetry)
    _logger.info("评论筛选与翻译结束 job_id=%s screened=%s selected=%s translated=%s", job.get("id") or "", len(screened), len(selected), len(comments))
    return comments, usage, {
        "screenBatches": batch_details,
        "screenedCount": len(screened),
        "screenedIds": [item["id"] for item in screened],
        "failedBatchIds": [item["id"] for index, batch in enumerate(batches) if batch_details[index].get("status") == "failed" for item in batch],
        "selectedIds": [item["id"] for item in selected],
        "selectedCount": len(selected),
        "translatedCount": len(comments),
        "finalSelectionFallback": final_fallback,
        "translation": translation_meta,
    }


def schedule_comment_burn(snapshot, video_duration):
    result = dict(snapshot or {})
    selected = list(result.get("comments") or [])
    try:
        duration = max(0.0, float(video_duration or 0))
    except (TypeError, ValueError):
        duration = 0.0
    if not selected:
        result["scheduledCount"] = 0
        if result.get("status") in {"failed", "skipped", "disabled"}:
            return result
        result["status"] = "skipped"
        result["reason"] = result.get("reason") or "未获取到可烧制评论"
        return result
    scheduled = []
    for index, comment in enumerate(selected[:COMMENT_SELECTED_LIMIT]):
        start = COMMENT_START_SECONDS + index * (COMMENT_DURATION_SECONDS + COMMENT_GAP_SECONDS)
        end = start + COMMENT_DURATION_SECONDS
        if end > duration:
            break
        scheduled.append({**comment, "displayStart": start, "displayEnd": end})
    result["comments"] = scheduled
    result["scheduledCount"] = len(scheduled)
    result["status"] = "success" if scheduled else "skipped"
    result["reason"] = "" if scheduled else "视频时长不足以排布评论"
    return result


def _is_allowed_comment_avatar_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and hostname.endswith((".ggpht.com", ".googleusercontent.com"))


class _CommentAvatarRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        if not _is_allowed_comment_avatar_url(new_url):
            return None
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def _download_comment_avatar(url, target):
    if not _is_allowed_comment_avatar_url(url):
        return ""
    try:
        import cv2
        import numpy as np

        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(_CommentAvatarRedirectHandler())
        with opener.open(request, timeout=8) as response:
            data = response.read(2 * 1024 * 1024)
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return ""
        height, width = image.shape[:2]
        side = min(height, width)
        top, left = (height - side) // 2, (width - side) // 2
        image = cv2.resize(image[top:top + side, left:left + side], (160, 160), interpolation=cv2.INTER_AREA)
        alpha = np.zeros((160, 160), dtype=np.uint8)
        cv2.circle(alpha, (80, 80), 78, 255, thickness=-1, lineType=cv2.LINE_AA)
        output = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        output[:, :, 3] = alpha
        return str(target) if cv2.imwrite(str(target), output) else ""
    except Exception as exc:
        _logger.warning("评论头像下载失败 error=%s", exc.__class__.__name__)
        return ""


def prepare_comment_avatar_assets(snapshot, work_dir):
    work_dir = Path(work_dir)
    avatar_dir = work_dir / "comment_avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    comments = list((snapshot or {}).get("comments") or [])
    assets_by_index = {}
    with ThreadPoolExecutor(
        max_workers=min(COMMENT_AVATAR_DOWNLOAD_CONCURRENCY, len(comments) or 1),
        thread_name_prefix="comment-avatar",
    ) as executor:
        futures = {
            executor.submit(_download_comment_avatar, comment.get("authorThumbnail"), avatar_dir / f"avatar_{index}.png"): (index, comment)
            for index, comment in enumerate(comments, start=1)
        }
        for future in as_completed(futures):
            index, comment = futures[future]
            try:
                avatar_file = future.result()
            except Exception as exc:
                _logger.warning("评论头像下载任务失败 error=%s", exc.__class__.__name__)
                continue
            if avatar_file:
                assets_by_index[index] = {
                "path": avatar_file,
                "start": comment.get("displayStart"),
                "end": comment.get("displayEnd"),
                "text": comment.get("text") or "",
                "translationRequired": bool(comment.get("translationRequired")),
                "translationZh": comment.get("translationZh") or "",
                }
    return [assets_by_index[index] for index in sorted(assets_by_index)]
