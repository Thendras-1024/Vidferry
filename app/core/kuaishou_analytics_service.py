"""快手作品指标、历史快照与评论样本业务服务。"""

from __future__ import annotations

import json as _ksa_json
import threading as _ksa_threading
from datetime import date as _KsaDate, datetime as _KsaDateTime, timedelta as _KsaTimedelta


_KSA_PLATFORM = "kuaishou"
_KSA_PLATFORM_TYPE = 4
_KSA_CACHE_MINUTES = 10
_KSA_ACCOUNT_LOCKS = {}
_KSA_ACCOUNT_LOCKS_GUARD = _ksa_threading.Lock()


def _ksa_json_object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = _ksa_json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _ksa_iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _ksa_owner_id():
    owner_user_id = _agent_current_user_id()
    if not owner_user_id:
        raise PermissionError("快手数据查询缺少当前用户身份")
    return int(owner_user_id)


def _ksa_validate_platform(platform):
    if isinstance(platform, (list, tuple, set, dict)) or str(platform or "").strip().lower() != _KSA_PLATFORM:
        raise ValueError("platform 首版只接受单个字符串 kuaishou")
    return _KSA_PLATFORM


def _ksa_positive_int(value, default, maximum):
    try:
        normalized = int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit 必须是整数") from exc
    if normalized < 1:
        raise ValueError("limit 必须大于 0")
    return min(normalized, maximum)


def _ksa_parse_date(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, _KsaDateTime):
        return value.date()
    if isinstance(value, _KsaDate):
        return value
    try:
        return _KsaDate.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD") from exc


def _ksa_account(account_id, owner_user_id):
    try:
        account_id = int(account_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("accountId 必须是整数") from exc
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            "SELECT id, type, filePath, userName, status, owner_user_id FROM user_info WHERE id = ? AND owner_user_id = ? AND type = ?",
            (account_id, owner_user_id, _KSA_PLATFORM_TYPE),
        ).fetchone()
    if not row:
        raise PermissionError("快手账号不存在或不属于当前用户")
    if int(row["status"] or 0) != 1:
        raise KuaishouAnalyticsStopError("快手账号登录态已标记异常，请先重新连接")
    return dict(row)


def _ksa_lock(account_id):
    key = int(account_id)
    with _KSA_ACCOUNT_LOCKS_GUARD:
        if key not in _KSA_ACCOUNT_LOCKS:
            _KSA_ACCOUNT_LOCKS[key] = _ksa_threading.Lock()
        return _KSA_ACCOUNT_LOCKS[key]


def _ksa_record(record_id, owner_user_id, selected_account_id=None):
    try:
        record_id = int(record_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("publishRecordId 必须是整数") from exc
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            """
            SELECT p.* FROM published_youtube_materials p
            WHERE p.id = ? AND p.platform_type = ? AND p.deleted_at IS NULL
            """,
            (record_id, _KSA_PLATFORM_TYPE),
        ).fetchone()
        if not row:
            raise ValueError("快手发布记录不存在")
        record = dict(row)
        if record.get("account_id"):
            if selected_account_id and int(selected_account_id) != int(record["account_id"]):
                raise ValueError("选择的账号与发布记录已绑定账号不一致")
            account = conn.execute(
                "SELECT id, type, filePath, userName, status, owner_user_id FROM user_info WHERE id = ? AND owner_user_id = ? AND type = ?",
                (record["account_id"], owner_user_id, _KSA_PLATFORM_TYPE),
            ).fetchone()
            if not account:
                raise PermissionError("发布记录账号不属于当前用户")
            return record, dict(account), None
        candidates = conn.execute(
            """
            SELECT id, type, filePath, userName, status, owner_user_id FROM user_info
            WHERE owner_user_id = ? AND type = ? AND (filePath = ? OR userName = ?)
            ORDER BY id
            """,
            (owner_user_id, _KSA_PLATFORM_TYPE, record.get("account_file") or "", record.get("account_name") or ""),
        ).fetchall()
        candidates = [dict(item) for item in candidates]
        global_candidates = conn.execute(
            "SELECT id, owner_user_id FROM user_info WHERE type = ? AND (filePath = ? OR userName = ?)",
            (_KSA_PLATFORM_TYPE, record.get("account_file") or "", record.get("account_name") or ""),
        ).fetchall()
        if selected_account_id:
            selected_account_id = int(selected_account_id)
            selected = next((item for item in candidates if int(item["id"]) == selected_account_id), None)
            if not selected:
                raise PermissionError("选择的快手账号不属于该发布记录候选")
            conn.execute("UPDATE published_youtube_materials SET account_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (selected["id"], record_id))
            record["account_id"] = selected["id"]
            return record, selected, None
        if len(candidates) == 1 and len(global_candidates) == 1:
            conn.execute("UPDATE published_youtube_materials SET account_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (candidates[0]["id"], record_id))
            record["account_id"] = candidates[0]["id"]
            return record, candidates[0], None
    choices = [{"accountId": item["id"], "accountName": item.get("userName") or "未命名账号"} for item in candidates]
    return record, None, {
        "needsClarification": True,
        "reason": "发布记录未能唯一匹配快手账号",
        "candidates": choices,
    }


def _ksa_collect_works(account, owner_user_id, from_date, to_date, limit):
    try:
        return kuaishou_official_list_works(account, owner_user_id, from_date, to_date, limit)
    except KuaishouOfficialUnavailableError:
        return kuaishou_creator_list_works(account, owner_user_id, from_date, to_date, limit)


def _ksa_collect_one(account, owner_user_id, work_id, published_at=None):
    try:
        return kuaishou_official_get_work(account, owner_user_id, work_id)
    except KuaishouOfficialUnavailableError:
        center = published_at.date() if isinstance(published_at, _KsaDateTime) else _KsaDate.today()
        works = kuaishou_creator_list_works(
            account, owner_user_id, center - _KsaTimedelta(days=2), center + _KsaTimedelta(days=2), 100,
        )
        return next((item for item in works if item["platformWorkId"] == str(work_id)), None)


def _ksa_title_values(record):
    values = []
    for value in (record.get("publish_title"), record.get("title")):
        text = str(value or "").strip()
        if "; description=" in text:
            text = text.split("; description=", 1)[0].strip()
        if text and text not in values:
            values.append(text)
    return values


def _ksa_bind_record(record, account, owner_user_id, selected_work_id=None):
    if record.get("platform_work_id"):
        if selected_work_id and str(selected_work_id) != str(record["platform_work_id"]):
            raise ValueError("选择的作品与发布记录已绑定作品不一致")
        return record, None
    published_at = _ks_parse_datetime(record.get("published_at") or record.get("updated_at")) or _KsaDateTime.now()
    works = _ksa_collect_works(
        account, owner_user_id, published_at.date() - _KsaTimedelta(days=1), published_at.date() + _KsaTimedelta(days=1), 30,
    )
    titles = set(_ksa_title_values(record))
    matches = []
    for work in works:
        if work["title"] not in titles or not work["publishedAt"]:
            continue
        if abs((work["publishedAt"] - published_at).total_seconds()) <= 24 * 3600:
            matches.append(work)
    if selected_work_id:
        selected = next((item for item in works if item["platformWorkId"] == str(selected_work_id)), None)
        if not selected:
            raise ValueError("选择的快手作品不在当前候选范围内")
        matches = [selected]
    if len(matches) != 1:
        return record, {
            "needsClarification": True,
            "reason": "历史快手作品未能唯一匹配，请选择具体作品" if matches else "未找到标题与发布时间都匹配的快手作品",
            "candidates": [
                {
                    "platformWorkId": item["platformWorkId"],
                    "title": item["title"],
                    "publishedAt": _ksa_iso(item["publishedAt"]),
                }
                for item in (matches or works[:10])
            ],
        }
    work = matches[0]
    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE published_youtube_materials
            SET account_id = ?, platform_work_id = ?, platform_work_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (account["id"], work["platformWorkId"], work["platformWorkUrl"], record["id"]),
        )
    record.update({
        "account_id": account["id"],
        "platform_work_id": work["platformWorkId"],
        "platform_work_url": work["platformWorkUrl"],
    })
    return record, None


def _ksa_snapshot_row(row):
    if not row:
        return None
    item = dict(row)
    return {
        "platformWorkId": item.get("platform_work_id") or "",
        "platformWorkUrl": item.get("platform_work_url") or "",
        "title": item.get("title") or "",
        "publishedAt": _ksa_iso(item.get("published_at")),
        "capturedAt": _ksa_iso(item.get("captured_at")),
        "source": item.get("source") or "",
        "metrics": _ksa_json_object(item.get("metrics")),
        "publishRecordId": item.get("publish_record_id"),
    }


def _ksa_latest_snapshots(owner_user_id, account_id, work_id=None, recent_only=False, from_date=None, to_date=None):
    conditions = ["owner_user_id = ?", "platform_type = ?", "account_id = ?"]
    params = [owner_user_id, _KSA_PLATFORM_TYPE, account_id]
    if work_id:
        conditions.append("platform_work_id = ?")
        params.append(str(work_id))
    if recent_only:
        conditions.append("captured_at >= CURRENT_TIMESTAMP - INTERVAL '10 minutes'")
    if from_date:
        conditions.append("published_at::date >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("published_at::date <= ?")
        params.append(to_date)
    with _db_connect(row_factory=True) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT ON (platform_work_id) * FROM platform_metric_snapshots
            WHERE {' AND '.join(conditions)}
            ORDER BY platform_work_id, captured_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
    return [_ksa_snapshot_row(row) for row in rows]


def _ksa_previous_snapshot(owner_user_id, account_id, work_id, captured_at):
    captured_at = _ks_parse_datetime(captured_at) or captured_at
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            """
            SELECT * FROM platform_metric_snapshots
            WHERE owner_user_id = ? AND platform_type = ? AND account_id = ?
              AND platform_work_id = ? AND captured_at < ?
            ORDER BY captured_at DESC, id DESC LIMIT 1
            """,
            (owner_user_id, _KSA_PLATFORM_TYPE, account_id, work_id, captured_at),
        ).fetchone()
    return _ksa_snapshot_row(row)


def _ksa_save_snapshot(owner_user_id, account_id, work, publish_record_id=None):
    with _db_connect(row_factory=True) as conn:
        row = conn.execute(
            """
            INSERT INTO platform_metric_snapshots (
                owner_user_id, platform_type, account_id, publish_record_id, platform_work_id,
                platform_work_url, title, published_at, source, metrics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS jsonb)) RETURNING *
            """,
            (
                owner_user_id, _KSA_PLATFORM_TYPE, account_id, publish_record_id, work["platformWorkId"],
                work.get("platformWorkUrl") or "", work.get("title") or "", work.get("publishedAt"),
                work.get("source") or "creator_center", _ksa_json.dumps(work.get("metrics") or {}, ensure_ascii=False),
            ),
        ).fetchone()
    return _ksa_snapshot_row(row)


def _ksa_metric_delta(current, previous):
    previous = previous or {}
    result = {}
    for key, value in (current or {}).items():
        old = previous.get(key)
        result[key] = value - old if isinstance(value, (int, float)) and isinstance(old, (int, float)) else None
    return result


def _ksa_derived(item):
    metrics = item.get("metrics") or {}
    views = metrics.get("views")
    published_at = _ks_parse_datetime(item.get("publishedAt"))
    days = max(1.0, ((_KsaDateTime.now() - published_at).total_seconds() / 86400)) if published_at else None
    def rate(key):
        value = metrics.get(key)
        return value / views if isinstance(value, (int, float)) and isinstance(views, (int, float)) and views > 0 else None
    likes = metrics.get("likes") if isinstance(metrics.get("likes"), (int, float)) else 0
    comments = metrics.get("comments") if isinstance(metrics.get("comments"), (int, float)) else 0
    shares = metrics.get("shares") if isinstance(metrics.get("shares"), (int, float)) else 0
    return {
        "viewsPerDay": views / days if isinstance(views, (int, float)) and days else None,
        "likeRate": rate("likes"),
        "commentRate": rate("comments"),
        "engagementRate": (likes + comments + shares) / views if isinstance(views, (int, float)) and views > 0 else None,
    }


def _ksa_local_context(owner_user_id, account, work):
    with _db_connect(row_factory=True) as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.video_id, p.publish_title, p.title, p.published_at, p.platform_work_id,
                   y.analysis_result, y.publish_draft
            FROM published_youtube_materials p
            LEFT JOIN youtube_videos y ON y.video_id = p.video_id
            WHERE p.platform_type = ? AND p.deleted_at IS NULL
              AND p.account_id = ?
              AND (p.platform_work_id = ? OR p.platform_work_id IS NULL)
            ORDER BY p.id DESC
            """,
            (_KSA_PLATFORM_TYPE, account["id"], work["platformWorkId"]),
        ).fetchall()
    matches = []
    for row in rows:
        item = dict(row)
        if item.get("platform_work_id") == work["platformWorkId"]:
            matches.append(item)
            continue
        published_at = _ks_parse_datetime(item.get("published_at"))
        if work.get("title") in _ksa_title_values(item) and published_at and work.get("publishedAt"):
            if abs((work["publishedAt"] - published_at).total_seconds()) <= 24 * 3600:
                matches.append(item)
    if len(matches) != 1:
        return {"localVideoLinked": False, "contentSummary": None, "publishTitle": None, "tags": []}
    match = matches[0]
    if not match.get("platform_work_id"):
        with _db_connect() as conn:
            conn.execute(
                "UPDATE published_youtube_materials SET account_id = ?, platform_work_id = ?, platform_work_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (account["id"], work["platformWorkId"], work.get("platformWorkUrl") or "", match["id"]),
            )
    analysis = _ksa_json_object(match.get("analysis_result"))
    draft = _ksa_json_object(match.get("publish_draft"))
    summary = analysis.get("summary") or analysis.get("contentSummary") or analysis.get("description")
    return {
        "localVideoLinked": True,
        "publishRecordId": match["id"],
        "videoId": match.get("video_id") or "",
        "contentSummary": summary or None,
        "publishTitle": draft.get("title") or match.get("publish_title") or None,
        "tags": draft.get("tags") if isinstance(draft.get("tags"), list) else [],
    }


def confirm_kuaishou_published_work(task):
    """发布成功后单次确认作品；不能唯一匹配时保持未绑定。"""
    if int(task.get("platformType") or 0) != _KSA_PLATFORM_TYPE:
        return None
    owner_user_id = task.get("ownerUserId")
    account_id = task.get("accountId")
    if not owner_user_id or not account_id:
        return None
    account = {
        "id": int(account_id),
        "filePath": task.get("accountFile") or "",
        "userName": task.get("accountName") or "",
    }
    now = _KsaDateTime.now()
    titles = {
        str(task.get("title") or "").strip(),
        str(task.get("description") or "").strip(),
    } - {""}
    with _ksa_lock(account["id"]):
        works = _ksa_collect_works(
            account, int(owner_user_id), now.date() - _KsaTimedelta(days=1), now.date() + _KsaTimedelta(days=1), 30,
        )
    matches = [
        work for work in works
        if work.get("title") in titles and work.get("publishedAt")
        and abs((now - work["publishedAt"]).total_seconds()) <= 12 * 3600
        and not work.get("pending")
    ]
    return matches[0] if len(matches) == 1 else None


def get_published_video_metrics(platform, publish_record_id, account_id=None, platform_work_id=None):
    _ksa_validate_platform(platform)
    owner_user_id = _ksa_owner_id()
    init_database_tables()
    record, account, clarification = _ksa_record(publish_record_id, owner_user_id, account_id)
    if clarification:
        return {"platform": _KSA_PLATFORM, "publishRecordId": record["id"], **clarification}
    with _ksa_lock(account["id"]):
        record, clarification = _ksa_bind_record(record, account, owner_user_id, platform_work_id)
        if clarification:
            return {"platform": _KSA_PLATFORM, "publishRecordId": record["id"], **clarification}
        cached = _ksa_latest_snapshots(owner_user_id, account["id"], record["platform_work_id"], recent_only=True)
        if cached:
            current = cached[0]
            cache_hit = True
        else:
            work = _ksa_collect_one(account, owner_user_id, record["platform_work_id"], _ks_parse_datetime(record.get("published_at")))
            if not work:
                raise KuaishouAnalyticsStopError("未在快手账号下找到对应作品")
            current = _ksa_save_snapshot(owner_user_id, account["id"], work, record["id"])
            cache_hit = False
        previous = _ksa_previous_snapshot(owner_user_id, account["id"], current["platformWorkId"], current["capturedAt"])
    return {
        "platform": _KSA_PLATFORM,
        "accountId": account["id"],
        "accountName": account.get("userName") or "",
        "publishRecordId": record["id"],
        "current": {**current, "derived": _ksa_derived(current)},
        "delta": _ksa_metric_delta(current["metrics"], (previous or {}).get("metrics")),
        "cacheHit": cache_hit,
    }


def list_account_video_metrics(platform, account_id, from_date=None, to_date=None, limit=None):
    _ksa_validate_platform(platform)
    owner_user_id = _ksa_owner_id()
    init_database_tables()
    account = _ksa_account(account_id, owner_user_id)
    today = _KsaDate.today()
    to_date = _ksa_parse_date(to_date, today)
    from_date = _ksa_parse_date(from_date, to_date - _KsaTimedelta(days=29))
    if from_date > to_date:
        raise ValueError("fromDate 不能晚于 toDate")
    if (to_date - from_date).days > 89:
        raise ValueError("日期范围最长 90 天")
    limit = _ksa_positive_int(limit, 50, 100)
    with _ksa_lock(account["id"]):
        cached = _ksa_latest_snapshots(owner_user_id, account["id"], recent_only=True, from_date=from_date, to_date=to_date)
        cache_hit = bool(cached)
        if cached:
            snapshots = cached[:limit]
            truncated = len(cached) > limit
        else:
            works = _ksa_collect_works(account, owner_user_id, from_date, to_date, limit)
            truncated = len(works) > limit
            snapshots = []
            for work in works[:limit]:
                local = _ksa_local_context(owner_user_id, account, work)
                snapshots.append(_ksa_save_snapshot(owner_user_id, account["id"], work, local.get("publishRecordId")))
    items = []
    for snapshot in snapshots:
        work = {
            "platformWorkId": snapshot["platformWorkId"], "platformWorkUrl": snapshot["platformWorkUrl"],
            "title": snapshot["title"], "publishedAt": _ks_parse_datetime(snapshot["publishedAt"]),
        }
        context = _ksa_local_context(owner_user_id, account, work)
        items.append({**snapshot, **context, "derived": _ksa_derived(snapshot)})
    ranked = sorted(items, key=lambda item: ((item["derived"].get("engagementRate") or -1), (item["metrics"].get("views") or -1)), reverse=True)
    return {
        "platform": _KSA_PLATFORM,
        "accountId": account["id"],
        "accountName": account.get("userName") or "",
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
        "sampleSize": len(items),
        "truncated": truncated,
        "cacheHit": cache_hit,
        "items": items,
        "bestPerforming": ranked[:3],
        "weakerPerforming": list(reversed(ranked[-3:])),
    }


def get_published_video_comments(platform, publish_record_id, limit=None):
    _ksa_validate_platform(platform)
    owner_user_id = _ksa_owner_id()
    init_database_tables()
    limit = _ksa_positive_int(limit, 20, 50)
    record, account, clarification = _ksa_record(publish_record_id, owner_user_id)
    if clarification:
        return {"platform": _KSA_PLATFORM, "publishRecordId": record["id"], **clarification}
    with _ksa_lock(account["id"]):
        record, clarification = _ksa_bind_record(record, account, owner_user_id)
        if clarification:
            return {"platform": _KSA_PLATFORM, "publishRecordId": record["id"], **clarification}
        work_url = record.get("platform_work_url") or ""
        if not work_url.startswith("https://cp.kuaishou.com/"):
            published_at = _ks_parse_datetime(record.get("published_at")) or _KsaDateTime.now()
            works = kuaishou_creator_list_works(
                account, owner_user_id, published_at.date() - _KsaTimedelta(days=2), published_at.date() + _KsaTimedelta(days=2), 100,
            )
            match = next((item for item in works if item["platformWorkId"] == record["platform_work_id"]), None)
            if not match:
                raise KuaishouAnalyticsStopError("未在快手创作者中心找到对应作品")
            work_url = match["platformWorkUrl"]
        comments = kuaishou_creator_get_comments(account, owner_user_id, work_url, limit)
        with _db_connect(row_factory=True) as conn:
            for comment in comments:
                conn.execute(
                    """
                    INSERT INTO platform_comment_samples (
                        owner_user_id, platform_type, account_id, publish_record_id, platform_work_id,
                        platform_comment_id, body, like_count, comment_published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (owner_user_id, platform_type, account_id, platform_work_id, platform_comment_id)
                    DO UPDATE SET body = EXCLUDED.body, like_count = EXCLUDED.like_count,
                                  comment_published_at = EXCLUDED.comment_published_at, captured_at = CURRENT_TIMESTAMP
                    """,
                    (
                        owner_user_id, _KSA_PLATFORM_TYPE, account["id"], record["id"], record["platform_work_id"],
                        comment["platformCommentId"], comment["body"], comment.get("likeCount"), comment.get("publishedAt"),
                    ),
                )
            rows = conn.execute(
                """
                SELECT platform_comment_id, body, like_count, comment_published_at, captured_at
                FROM platform_comment_samples
                WHERE owner_user_id = ? AND platform_type = ? AND account_id = ? AND platform_work_id = ?
                ORDER BY COALESCE(like_count, 0) DESC, captured_at DESC LIMIT ?
                """,
                (owner_user_id, _KSA_PLATFORM_TYPE, account["id"], record["platform_work_id"], limit),
            ).fetchall()
    return {
        "platform": _KSA_PLATFORM,
        "accountId": account["id"],
        "publishRecordId": record["id"],
        "platformWorkId": record["platform_work_id"],
        "sampleSize": len(rows),
        "items": [
            {
                "commentId": row["platform_comment_id"],
                "body": row["body"],
                "likeCount": row["like_count"],
                "publishedAt": _ksa_iso(row["comment_published_at"]),
                "capturedAt": _ksa_iso(row["captured_at"]),
            }
            for row in rows
        ],
    }
