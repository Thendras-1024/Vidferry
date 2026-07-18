"""Google 初译后的中文字幕 LLM 语义修订。"""

from __future__ import annotations

import datetime
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT,
    SUBTITLE_LLM_REVIEW_ENABLED,
    SUBTITLE_REVIEW_BATCH_MAX_CHARS,
    SUBTITLE_REVIEW_CONCURRENCY,
    SUBTITLE_REVIEW_MAX_TOKENS,
    SUBTITLE_REVIEW_MODEL,
)
from app.core import llm_prompts
from app.core.llm_harness import call_json_contract, validate_subtitle_revision


def _normalize_chinese_subtitle(text):
    # 中文句号去除已前移到翻译阶段(subtitle_service._strip_chinese_period)，
    # 此处仅合并空白，避免与翻译后处理职责重叠；修订是否产出句号交由提示词约束。
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _log(job_id, message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"{timestamp} | SUBTITLE_REVIEW | job={job_id or '-'} | {message}", flush=True)


def _build_review_payload(reviewed, indexes, context):
    """构造单批修订 payload：当前 items + 前后各 2 段上下文。"""
    def payload_item(index):
        segment = reviewed[index]
        return {
            "index": index,
            "source": str(segment.get("text") or "").strip(),
            "initialSubtitle": str(segment.get("subtitle") or "").strip(),
        }

    return {
        "video": {
            "title": str(context.get("title") or "").strip(),
            "channel": str(context.get("channel") or "").strip(),
        },
        "previous": [payload_item(index) for index in range(max(0, indexes[0] - 2), indexes[0])],
        "items": [payload_item(index) for index in indexes],
        "following": [
            payload_item(index)
            for index in range(indexes[-1] + 1, min(len(reviewed), indexes[-1] + 3))
        ],
    }


def _review_single_batch(batch_number, total_batches, indexes, reviewed, context, job_id, telemetry):
    """处理单个修订批次。

    只读写 reviewed 中本批 indexes 对应的位置（不同批次 index 不重叠，线程安全）。
    返回批次诊断；失败时回退该批为初译（翻译阶段已去句号）。
    """
    expected_indexes = list(indexes)
    payload = _build_review_payload(reviewed, indexes, context)
    batch_started_at = time.time()
    attempts = []

    def record_attempt(event):
        if callable(telemetry):
            telemetry(event)
        attempts.append({
            "attempt": int(event.get("attempt") or len(attempts) + 1),
            "status": str(event.get("status") or "unknown"),
            "category": str(event.get("errorCategory") or event.get("error_category") or ""),
            "reason": " ".join(str(event.get("errorMessage") or "").split())[:300],
            "promptTokens": int(event.get("promptTokens") or event.get("prompt_tokens") or 0),
            "completionTokens": int(event.get("completionTokens") or event.get("completion_tokens") or 0),
            "totalTokens": int(event.get("totalTokens") or event.get("total_tokens") or event.get("tokens") or 0),
            "latencyMs": round(float(event.get("latencyMs") or event.get("latency_ms") or 0), 2),
        })
    _log(
        job_id,
        f"开始修订批次 {batch_number}/{total_batches}: segments={len(indexes)}, "
        f"index={indexes[0]}-{indexes[-1]}",
    )
    try:
        result, usage, metadata = call_json_contract(
            messages=llm_prompts.subtitle_review_messages(payload),
            contract_id="subtitle_revision",
            validator=lambda value: validate_subtitle_revision(value, expected_indexes),
            model=SUBTITLE_REVIEW_MODEL or LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=LLM_TIMEOUT,
            temperature=0.1,
            max_tokens=SUBTITLE_REVIEW_MAX_TOKENS,
            prompt_version=llm_prompts.SUBTITLE_REVIEW_PROMPT_VERSION,
            telemetry=record_attempt,
        )
        changed = 0
        for item in result.get("items") or []:
            index = item["index"]
            subtitle = _normalize_chinese_subtitle(item["subtitle"])
            if subtitle != _normalize_chinese_subtitle(reviewed[index].get("subtitle")):
                changed += 1
            reviewed[index]["subtitle"] = subtitle
        tokens = int(usage.get("totalTokens") or usage.get("tokens") or 0)
        _log(
            job_id,
            f"修订批次 {batch_number}/{total_batches} 完成: duration={time.time() - batch_started_at:.1f}s, "
            f"tokens={tokens}, attempts={int(metadata.get('attemptCount') or 1)}",
        )
        return {
            "number": batch_number,
            "indexes": expected_indexes,
            "status": "success",
            "changedCount": changed,
            "fallbackCount": 0,
            "tokens": tokens,
            "reason": "",
            "attempts": attempts,
        }
    except Exception as exc:
        for index in indexes:
            reviewed[index]["subtitle"] = _normalize_chinese_subtitle(reviewed[index].get("subtitle"))
        detail = " ".join(str(exc).split())[:300]

        def _json_risky(value):
            text = str(value or "")
            if '"' in text or "\n" in text or "\r" in text:
                return True
            return any(ord(ch) < 32 and ch != "\t" for ch in text)

        # 仅打印诊断摘要（index+长度+是否含破坏 JSON 的可疑字符），避免长 payload 刷屏；
        # 如需查看原文/初译全文，按 index 到转写文件数段定位。
        failed_items = [
            {
                "index": index,
                "srcLen": len(str(reviewed[index].get("text") or "")),
                "subLen": len(str(reviewed[index].get("subtitle") or "")),
                "risky": _json_risky(reviewed[index].get("text")) or _json_risky(reviewed[index].get("subtitle")),
            }
            for index in indexes
        ]
        _log(
            job_id,
            f"修订批次 {batch_number}/{total_batches} 失败，回退 Google 初译: "
            f"{exc.__class__.__name__}: {detail} | items={json.dumps(failed_items, ensure_ascii=False)}",
        )
        return {
            "number": batch_number,
            "indexes": expected_indexes,
            "status": "fallback",
            "changedCount": 0,
            "fallbackCount": len(indexes),
            "tokens": 0,
            "reason": f"{exc.__class__.__name__}: {detail}",
            "attempts": attempts,
        }


def review_translated_segments(segments, target_language, job=None, job_id="", progress_callback=None, telemetry=None, review_metadata=None):
    reviewed = [dict(segment) for segment in (segments or [])]
    metadata = review_metadata if isinstance(review_metadata, dict) else None
    def mark(status, fallback=0, batches=0, changed=0, tokens=0, batch_details=None):
        if metadata is not None:
            metadata.update({
                "status": status, "fallbackCount": int(fallback or 0), "batchCount": int(batches or 0),
                "changedCount": int(changed or 0), "totalTokens": int(tokens or 0),
                "model": SUBTITLE_REVIEW_MODEL or LLM_MODEL or "",
                "batches": list(batch_details or []),
            })
    if target_language != "zh-CN":
        _log(job_id, f"跳过 LLM 修订: target_language={target_language}")
        mark("skipped_target_language")
        return reviewed

    def normalize_all():
        for segment in reviewed:
            segment["subtitle"] = _normalize_chinese_subtitle(segment.get("subtitle"))
        return reviewed

    if not SUBTITLE_LLM_REVIEW_ENABLED:
        _log(job_id, "LLM 修订已关闭，使用 Google 初译")
        mark("disabled")
        return normalize_all()
    if not reviewed:
        _log(job_id, "没有可修订的字幕")
        mark("empty")
        return reviewed
    if not SUBTITLE_REVIEW_MODEL or not LLM_API_KEY or not LLM_BASE_URL:
        _log(job_id, "LLM 配置不完整，使用 Google 初译")
        mark("unavailable")
        return normalize_all()

    max_chars = SUBTITLE_REVIEW_BATCH_MAX_CHARS
    batches = []
    current = []
    current_chars = 0
    for index, segment in enumerate(reviewed):
        item_chars = len(str(segment.get("text") or "")) + len(str(segment.get("subtitle") or ""))
        if current and current_chars + item_chars > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(index)
        current_chars += item_chars
    if current:
        batches.append(current)

    context = job if isinstance(job, dict) else {}
    total_batches = len(batches)
    concurrency = max(1, min(SUBTITLE_REVIEW_CONCURRENCY, total_batches))
    total_segments = len(reviewed)
    started_at = time.time()
    changed_count = 0
    fallback_count = 0
    total_tokens = 0
    completed_segments = 0
    batch_details = []
    _log(
        job_id,
        f"开始 LLM 修订: model={SUBTITLE_REVIEW_MODEL or LLM_MODEL}, segments={total_segments}, "
        f"batches={total_batches}, concurrency={concurrency}, batch_max_chars={max_chars}",
    )

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="subtitle-review") as executor:
        future_to_batch = {
            executor.submit(
                _review_single_batch,
                batch_number, total_batches, indexes, reviewed, context, job_id, telemetry,
            ): indexes
            for batch_number, indexes in enumerate(batches, start=1)
        }
        for future in as_completed(future_to_batch):
            indexes = future_to_batch[future]
            batch = future.result()
            batch_details.append(batch)
            changed_count += int(batch.get("changedCount") or 0)
            fallback_count += int(batch.get("fallbackCount") or 0)
            total_tokens += int(batch.get("tokens") or 0)
            completed_segments += len(indexes)
            if progress_callback:
                progress_callback(completed_segments, total_segments)

    _log(
        job_id,
        f"LLM 修订结束: duration={time.time() - started_at:.1f}s, changed={changed_count}, "
        f"fallback={fallback_count}, tokens={total_tokens}",
    )
    mark("success", fallback_count, total_batches, changed_count, total_tokens, batch_details)
    return reviewed
