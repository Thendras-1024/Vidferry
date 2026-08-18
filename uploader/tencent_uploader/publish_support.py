"""视频号发布的确认、诊断与页面恢复辅助逻辑。"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlsplit, urlunsplit

from utils.humanize import human_delay, jitter_seconds


TENCENT_PUBLISH_RESULT_MARKER = "VIDFERRY_TENCENT_PUBLISH_RESULT="


class TencentPublishRecoveryRequired(RuntimeError):
    """上传页面在提交前失效，需要重建浏览器上下文。"""


def _safe_tencent_url(value):
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _tencent_work_candidates(payload):
    candidates = {}

    def visit(value):
        if isinstance(value, dict):
            work_id = str(value.get("objectId") or value.get("object_id") or "").strip()
            work_url = str(value.get("url") or "").strip()
            if work_id:
                candidates[work_id] = _safe_tencent_url(work_url) if work_url else ""
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return candidates


def format_tencent_publish_result(result):
    return TENCENT_PUBLISH_RESULT_MARKER + json.dumps({
        "platformWorkId": str((result or {}).get("platformWorkId") or ""),
        "platformWorkUrl": _safe_tencent_url((result or {}).get("platformWorkUrl") or ""),
    }, ensure_ascii=False)


class TencentPublishDiagnostics:
    def __init__(self):
        self.console_errors = []
        self.failed_requests = []

    def _on_console(self, message):
        if str(getattr(message, "type", "")) == "error":
            self.console_errors.append({"type": "error", "text": str(getattr(message, "text", ""))[:500]})

    def _on_request_failed(self, request):
        self.failed_requests.append({
            "method": str(getattr(request, "method", "")),
            "url": _safe_tencent_url(getattr(request, "url", "")),
            "failure": str(getattr(request, "failure", ""))[:300],
        })

    def attach(self, page):
        page.on("console", self._on_console)
        page.on("requestfailed", self._on_request_failed)

    def describe(self, stage, page):
        return {
            "stage": str(stage),
            "url": _safe_tencent_url(getattr(page, "url", "")),
            "consoleErrors": list(self.console_errors),
            "failedRequests": list(self.failed_requests),
            "pageErrors": [],
        }


async def wait_for_upload_complete(uploader, page, *, timeout_seconds, retry_limit, cover_stall_seconds):
    deadline = time.monotonic() + timeout_seconds
    retry_count = 0
    closed_count = 0
    cover_started_at = None
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(f"VF-PUBLISH-UPLOAD-TIMEOUT: 视频号上传等待超过 {timeout_seconds} 秒")
        try:
            upload_failed = await page.locator("div.status-msg.error").count()
            delete_button = await page.locator('div.media-status-content div.tag-inner:has-text("删除")').count()
            if upload_failed and delete_button:
                if retry_count >= retry_limit:
                    raise RuntimeError("VF-PUBLISH-UPLOAD-FAILED: 视频号上传失败，已停止自动重传。")
                retry_count += 1
                await uploader.handle_upload_error(page)
                continue

            cover = page.get_by_text("生成中", exact=True)
            cover_visible = bool(await cover.count() and await cover.is_visible())
            if cover_visible:
                cover_started_at = cover_started_at or time.monotonic()
                if time.monotonic() - cover_started_at >= cover_stall_seconds:
                    raise TencentPublishRecoveryRequired("视频号生成封面超时，需要重建页面。")
            else:
                cover_started_at = None
                button_class = await page.get_by_role("button", name="发表").get_attribute("class")
                if button_class and "weui-desktop-btn_disabled" not in button_class:
                    return
            await asyncio.sleep(jitter_seconds(2, min_seconds=1.5, max_seconds=3.5))
        except TencentPublishRecoveryRequired:
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            if "page, context or browser has been closed" in str(exc).lower():
                closed_count += 1
                if closed_count >= 5:
                    raise TencentPublishRecoveryRequired("视频号页面已关闭，需要重建页面。") from exc
            await asyncio.sleep(jitter_seconds(2, min_seconds=1.5, max_seconds=3.5))


async def submit_publish(uploader, page, *, confirm_timeout, observe_seconds, human_delay_fn=human_delay):
    if getattr(uploader, "is_draft", False):
        draft_button = page.locator('div.form-btns button:has-text("保存草稿")')
        if await draft_button.count():
            await draft_button.click()
        await page.wait_for_url("**/post/list**", timeout=5000)
        return {}

    submitted = {}
    listed = {}
    pending = []

    def on_response(response):
        async def collect():
            try:
                payload = await response.json()
            except Exception:
                return
            target = submitted if str(getattr(response.request, "method", "")).upper() == "POST" else listed
            target.update(_tencent_work_candidates(payload))
        pending.append(asyncio.create_task(collect()))

    page.on("response", on_response)
    try:
        button = page.locator('div.form-btns button:has-text("发表")')
        if await button.count():
            await human_delay_fn(1.5, 5)
            await button.click()
        await page.wait_for_url("**/post/list**", timeout=5000)
        await asyncio.sleep(observe_seconds)
        await page.reload(wait_until="domcontentloaded")
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for work_id in submitted.keys() & listed.keys():
            return {"platformWorkId": work_id, "platformWorkUrl": listed[work_id] or submitted[work_id]}
        raise RuntimeError("VF-PUBLISH-UNVERIFIED: 视频号发布后未能确认作品记录。")
    finally:
        page.remove_listener("response", on_response)
