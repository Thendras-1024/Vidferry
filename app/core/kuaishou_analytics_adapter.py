"""快手官方接口与创作者中心只读采集适配器。"""

from __future__ import annotations

import hashlib as _ks_hashlib
import json as _ks_json
import os as _ks_os
import re as _ks_re
from datetime import datetime as _KsDateTime, timezone as _ks_timezone
from pathlib import Path as _KsPath

import requests as _ks_requests


_KS_PLATFORM_TYPE = 4
_KS_STATS_URL = "https://cp.kuaishou.com/statistics/article"
_KS_OFFICIAL_LIST_URL = "https://open.kuaishou.com/openapi/photo/list"
_KS_OFFICIAL_INFO_URL = "https://open.kuaishou.com/openapi/photo/info"
_KS_RATE_LIMIT_CODES = {100100402, 100100403, 100100404, 200100410}
_KS_METRIC_KEYS = {
    "播放": "views",
    "观看": "views",
    "点赞": "likes",
    "评论": "comments",
    "分享": "shares",
    "涨粉": "followersGained",
    "新增粉丝": "followersGained",
    "平均观看时长": "avgWatchDurationSeconds",
    "完播率": "completionRate",
}


class KuaishouAnalyticsError(RuntimeError):
    code = "KUAISHOU_ANALYTICS_ERROR"


class KuaishouOfficialUnavailableError(KuaishouAnalyticsError):
    code = "KUAISHOU_OFFICIAL_UNAVAILABLE"


class KuaishouAnalyticsStopError(KuaishouAnalyticsError):
    code = "KUAISHOU_ANALYTICS_STOPPED"


def _ks_public_error(exc, fallback):
    return f"{fallback}（{type(exc).__name__}）"


def _ks_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "").replace("，", "")
    match = _ks_re.search(r"(-?\d+(?:\.\d+)?)\s*([万亿wW]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"万", "w"}:
        number *= 10_000
    elif unit == "亿":
        number *= 100_000_000
    return int(number) if number.is_integer() else number


def _ks_percent(value):
    number = _ks_number(value)
    if number is None:
        return None
    return number / 100 if "%" in str(value) else float(number)


def _ks_parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, _KsDateTime):
        return value.replace(tzinfo=None)
    if isinstance(value, (int, float)) or str(value).isdigit():
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return _KsDateTime.fromtimestamp(timestamp, tz=_ks_timezone.utc).replace(tzinfo=None)
    text = str(value).strip().replace("/", "-")
    try:
        parsed = _KsDateTime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(_ks_timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            parsed = _KsDateTime.strptime(text, fmt)
            if fmt.startswith("%m"):
                parsed = parsed.replace(year=_KsDateTime.now().year)
            return parsed
        except ValueError:
            continue
    return None


def _ks_normalize_metrics(raw):
    raw = raw if isinstance(raw, dict) else {}
    aliases = {
        "views": ("views", "viewCount", "view_count", "playCount", "play_count"),
        "likes": ("likes", "likeCount", "like_count", "realLikeCount"),
        "comments": ("comments", "commentCount", "comment_count"),
        "shares": ("shares", "shareCount", "share_count", "forwardCount"),
        "followersGained": ("followersGained", "followCount", "newFansCount"),
        "avgWatchDurationSeconds": ("avgWatchDurationSeconds", "avgWatchDuration", "playDuration"),
        "completionRate": ("completionRate", "finishRate"),
    }
    result = {}
    for key, candidates in aliases.items():
        value = next((raw.get(candidate) for candidate in candidates if raw.get(candidate) is not None), None)
        result[key] = _ks_percent(value) if key == "completionRate" else _ks_number(value)
    return result


def _ks_metrics_from_text(text):
    source = str(text or "")
    metrics = {key: None for key in _ks_normalize_metrics({})}
    for label, key in sorted(_KS_METRIC_KEYS.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"{_ks_re.escape(label)}\s*[:：]?\s*(-?\d+(?:\.\d+)?\s*(?:万|亿|w|W|%)?)"
        match = _ks_re.search(pattern, source)
        if not match or metrics[key] is not None:
            continue
        metrics[key] = _ks_percent(match.group(1)) if key == "completionRate" else _ks_number(match.group(1))
    return metrics


def _ks_normalize_work(raw, source):
    raw = raw if isinstance(raw, dict) else {}
    work_id = next((raw.get(key) for key in ("photoId", "photo_id", "id", "workId") if raw.get(key)), "")
    caption = next((raw.get(key) for key in ("caption", "title", "name") if raw.get(key)), "")
    work_url = next((raw.get(key) for key in ("workUrl", "photoUrl", "shareUrl", "url") if raw.get(key)), "")
    published_at = next((raw.get(key) for key in ("createTime", "create_time", "publishedAt", "timestamp") if raw.get(key) is not None), None)
    metrics = _ks_normalize_metrics(raw.get("metrics") or raw)
    return {
        "platformWorkId": str(work_id or ""),
        "platformWorkUrl": str(work_url or ""),
        "title": str(caption or "").strip(),
        "publishedAt": _ks_parse_datetime(published_at),
        "pending": bool(raw.get("pending") or raw.get("status") in {"pending", 1}),
        "source": source,
        "metrics": metrics,
    }


def _ks_token_sidecar(account, owner_user_id):
    cookie_path = _safe_cookie_path(account["filePath"], owner_user_id=owner_user_id)
    target = cookie_path.with_name(f"{cookie_path.name}.kuaishou-open.json").resolve()
    if target.parent != cookie_path.parent:
        raise KuaishouOfficialUnavailableError("快手官方 Token 路径无效")
    return target


def _ks_load_official_auth(account, owner_user_id):
    app_id = str(_ks_os.environ.get("KUAISHOU_OPEN_APP_ID") or "").strip()
    if not app_id:
        raise KuaishouOfficialUnavailableError("未配置快手开放平台应用")
    sidecar = _ks_token_sidecar(account, owner_user_id)
    if not sidecar.is_file() or sidecar.stat().st_size > 64 * 1024:
        raise KuaishouOfficialUnavailableError("账号未授权快手作品读取能力")
    try:
        payload = _ks_json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise KuaishouOfficialUnavailableError(_ks_public_error(exc, "快手授权文件无效")) from exc
    token = str(payload.get("accessToken") or payload.get("access_token") or "").strip()
    scopes = payload.get("scopes") or payload.get("scope") or []
    if isinstance(scopes, str):
        scopes = [item for item in _ks_re.split(r"[\s,]+", scopes) if item]
    expires_at = _ks_parse_datetime(payload.get("expiresAt") or payload.get("expires_at"))
    if not token or (expires_at and expires_at <= _KsDateTime.utcnow()):
        raise KuaishouOfficialUnavailableError("快手官方授权缺失或已过期")
    if scopes and "user_video_info" not in scopes:
        raise KuaishouOfficialUnavailableError("快手官方授权缺少 user_video_info")
    return app_id, token


def _ks_official_get(url, params):
    try:
        response = _ks_requests.get(url, params=params, timeout=(5, 20))
        response.raise_for_status()
        payload = response.json()
    except (_ks_requests.RequestException, ValueError) as exc:
        raise KuaishouAnalyticsStopError(_ks_public_error(exc, "快手官方接口请求失败，未自动重试")) from exc
    code = payload.get("result") if isinstance(payload, dict) else None
    if code in _KS_RATE_LIMIT_CODES or response.status_code == 429:
        raise KuaishouAnalyticsStopError("快手官方接口已限流，采集已停止")
    if code not in (None, 0, 1, "0", "1", "success", "SUCCESS"):
        message = str(payload.get("error_msg") or payload.get("message") or "快手官方接口返回错误")[:160]
        raise KuaishouAnalyticsStopError(message)
    return payload


def _ks_payload_data(payload):
    data = payload.get("data") if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def kuaishou_official_list_works(account, owner_user_id, from_date, to_date, limit):
    app_id, token = _ks_load_official_auth(account, owner_user_id)
    cursor = ""
    works = []
    while len(works) < limit + 1:
        payload = _ks_official_get(_KS_OFFICIAL_LIST_URL, {
            "app_id": app_id, "access_token": token, "count": min(20, limit + 1 - len(works)), "cursor": cursor,
        })
        data = _ks_payload_data(payload)
        rows = data.get("video_list") or data.get("photo_list") or data.get("list") or []
        for row in rows if isinstance(rows, list) else []:
            work = _ks_normalize_work(row, "official_api")
            if work["publishedAt"] and not (from_date <= work["publishedAt"].date() <= to_date):
                continue
            works.append(work)
        next_cursor = str(data.get("cursor") or data.get("next_cursor") or "")
        if not rows or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return works[:limit + 1]


def kuaishou_official_get_work(account, owner_user_id, work_id):
    app_id, token = _ks_load_official_auth(account, owner_user_id)
    payload = _ks_official_get(_KS_OFFICIAL_INFO_URL, {
        "app_id": app_id, "access_token": token, "photo_id": str(work_id),
    })
    data = _ks_payload_data(payload)
    row = data.get("video_info") or data.get("photo_info") or data
    return _ks_normalize_work(row, "official_api")


def _ks_creator_state(page):
    url = str(page.url or "").lower()
    body = page.locator("body").inner_text(timeout=10_000)[:20_000]
    if "passport.kuaishou.com" in url or ("登录" in body and "扫码" in body):
        raise KuaishouAnalyticsStopError("快手账号登录态已失效，请在账号管理中重新连接")
    if any(text in body for text in ("验证码", "安全验证", "完成验证")):
        raise KuaishouAnalyticsStopError("快手要求安全验证，采集已停止，请在可见浏览器中处理")
    if any(text in body for text in ("访问频繁", "操作频繁", "请求过于频繁", "稍后再试")):
        raise KuaishouAnalyticsStopError("快手触发限流或风控，采集已停止")


def _ks_creator_extract_rows(page):
    raw_rows = page.evaluate("""
    () => Array.from(document.querySelectorAll('a[href]')).map((link) => {
      const href = link.href || '';
      const match = href.match(/(?:photo|work|video|article)[\\/=]([A-Za-z0-9_-]{6,})/i)
        || href.match(/[?&](?:photoId|photo_id|workId)=([^&]+)/i);
      if (!match) return null;
      let row = link;
      for (let i = 0; i < 5 && row.parentElement; i += 1) {
        if ((row.parentElement.innerText || '').length <= 1800) row = row.parentElement;
      }
      return { photoId: decodeURIComponent(match[1]), workUrl: href,
        caption: (link.innerText || '').trim(), text: (row.innerText || '').trim() };
    }).filter(Boolean)
    """)
    works = []
    seen = set()
    for row in raw_rows if isinstance(raw_rows, list) else []:
        work_id = str(row.get("photoId") or "")
        if not work_id or work_id in seen:
            continue
        seen.add(work_id)
        text = str(row.get("text") or "")
        date_match = _ks_re.search(r"(?:20\d{2}[-/.])?\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", text)
        row["createTime"] = date_match.group(0) if date_match else None
        row["metrics"] = _ks_metrics_from_text(text)
        works.append(_ks_normalize_work(row, "creator_center"))
    return works


def _ks_launch_creator(account, owner_user_id):
    from conf import LOCAL_CHROME_PATH as _ks_chrome_path
    from patchright.sync_api import sync_playwright as _ks_sync_playwright

    cookie_path = _safe_cookie_path(account["filePath"], owner_user_id=owner_user_id)
    if not cookie_path.is_file():
        raise KuaishouAnalyticsStopError("快手账号登录态文件不存在")
    playwright = _ks_sync_playwright().start()
    try:
        kwargs = {"headless": False}
        if _ks_chrome_path:
            kwargs["executable_path"] = _ks_chrome_path
        else:
            kwargs["channel"] = "chrome"
        browser = playwright.chromium.launch(**kwargs)
        context = browser.new_context(storage_state=str(cookie_path))
        page = context.new_page()
        return playwright, browser, context, page
    except Exception:
        playwright.stop()
        raise


def kuaishou_creator_list_works(account, owner_user_id, from_date, to_date, limit):
    playwright = browser = context = None
    try:
        playwright, browser, context, page = _ks_launch_creator(account, owner_user_id)
        page.goto(_KS_STATS_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1000)
        _ks_creator_state(page)
        works = []
        seen = set()
        for _ in range(10):
            for work in _ks_creator_extract_rows(page):
                if work["platformWorkId"] in seen:
                    continue
                if work["publishedAt"] and not (from_date <= work["publishedAt"].date() <= to_date):
                    continue
                seen.add(work["platformWorkId"])
                works.append(work)
            if len(works) >= limit + 1:
                break
            next_button = page.get_by_text("下一页", exact=True)
            if not next_button.count() or next_button.is_disabled():
                break
            next_button.click()
            page.wait_for_timeout(800)
            _ks_creator_state(page)
        if not works:
            raise KuaishouAnalyticsStopError("快手创作者中心页面结构已变化，未读取到作品数据")
        return works[:limit + 1]
    except KuaishouAnalyticsError:
        raise
    except Exception as exc:
        raise KuaishouAnalyticsStopError(_ks_public_error(exc, "快手创作者中心读取失败")) from exc
    finally:
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()


def kuaishou_creator_get_comments(account, owner_user_id, work_url, limit):
    if not str(work_url or "").startswith("https://cp.kuaishou.com/"):
        raise KuaishouAnalyticsStopError("缺少可在创作者中心打开的快手作品地址")
    playwright = browser = context = None
    try:
        playwright, browser, context, page = _ks_launch_creator(account, owner_user_id)
        page.goto(work_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1000)
        _ks_creator_state(page)
        raw = page.evaluate("""
        () => Array.from(document.querySelectorAll('[class*="comment"], [role="listitem"]')).map((row, index) => {
          const content = row.querySelector('[class*="content"], [class*="text"]');
          if (!content || content.children.length) return null;
          const text = (content.innerText || '').trim();
          if (!text) return null;
          const source = (row.innerText || '').trim();
          const id = row.getAttribute('data-comment-id') || row.getAttribute('data-id') || '';
          return { id, text, source, index };
        }).filter(Boolean)
        """)
        comments = []
        for item in raw if isinstance(raw, list) else []:
            body = str(item.get("text") or "").strip()[:1000]
            if not body:
                continue
            source = str(item.get("source") or "")
            like_match = _ks_re.search(r"点赞\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:万|w|W)?)", source)
            date_match = _ks_re.search(r"(?:20\d{2}[-/.])?\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2})?", source)
            comment_id = str(item.get("id") or "") or _ks_hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
            comments.append({
                "platformCommentId": comment_id,
                "body": body,
                "likeCount": _ks_number(like_match.group(1)) if like_match else None,
                "publishedAt": _ks_parse_datetime(date_match.group(0)) if date_match else None,
            })
            if len(comments) >= limit:
                break
        if not comments:
            raise KuaishouAnalyticsStopError("作品评论不可见或页面结构已变化，未读取到评论正文")
        return comments
    except KuaishouAnalyticsError:
        raise
    except Exception as exc:
        raise KuaishouAnalyticsStopError(_ks_public_error(exc, "快手评论读取失败")) from exc
    finally:
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
