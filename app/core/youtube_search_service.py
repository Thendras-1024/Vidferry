"""YouTube 视频搜索与元数据抓取:yt-dlp 搜索、网页兜底解析、订阅数与发布日期补全。"""

import datetime as _datetime

def _extract_yt_initial_data(content):
    marker = "var ytInitialData = "
    start = content.find(marker)
    if start == -1:
        marker = "ytInitialData = "
        start = content.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = content.find(";</script>", start)
    if end == -1:
        end = content.find(";</", start)
    if end == -1:
        return None
    try:
        return json.loads(content[start:end])
    except json.JSONDecodeError:
        return None


def _walk_dict(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dict(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dict(item)


def _text_from_runs(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "simpleText" in value:
            return value["simpleText"]
        if "runs" in value:
            return "".join(run.get("text", "") for run in value["runs"])
    return ""


def _fetch_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _fetch_text(url, timeout=18):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _search_youtube_with_ytdlp(query, limit):
    try:
        import yt_dlp
    except ImportError:
        return []

    ydl_opts = {
        **_base_ytdlp_opts(include_ffmpeg=True),
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": True,
    }
    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    for item in data.get("entries") or []:
        if not item:
            continue
        video_id = item.get("id")
        url = item.get("webpage_url") or item.get("url")
        if video_id and (not url or not url.startswith("http")):
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(str(video_id or "")):
            continue
        url = f"https://www.youtube.com/watch?v={video_id}"
        duration_seconds = _duration_seconds(item.get("duration"))
        results.append({
            "id": video_id or "",
            "title": item.get("title") or "",
            "channel": item.get("channel") or item.get("uploader") or "",
            "subscribers": _format_subscribers_w(item.get("channel_follower_count") or item.get("uploader_follower_count")),
            "publishedAt": _ytdlp_published_at(item),
            "url": url or "",
            "thumbnail": (item.get("thumbnail") or ""),
            "duration": item.get("duration_string") or _format_duration_seconds(duration_seconds),
            "durationSeconds": duration_seconds,
            "viewCount": int(item.get("view_count") or 0),
        })
    return results


_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _extract_youtube_video_id(url):
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if parsed.scheme.lower() != "https" or host not in _YOUTUBE_HOSTS or port not in (None, 443):
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        return video_id if _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id) else ""
    if host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            return video_id if _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id) else ""
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                video_id = parsed.path[len(prefix):].split("/")[0]
                return video_id if _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id) else ""
    return ""


def _is_allowed_youtube_host_url(url):
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme.lower() == "https"
        and host in _YOUTUBE_HOSTS
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def _validate_youtube_url(url):
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        raise ValueError("仅支持标准 YouTube HTTPS 视频链接")
    return f"https://www.youtube.com/watch?v={video_id}"


def _canonical_youtube_url(url, video_id=""):
    normalized_video_id = video_id if _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(str(video_id or "")) else _extract_youtube_video_id(url or "")
    if normalized_video_id:
        return f"https://www.youtube.com/watch?v={normalized_video_id}"
    return (url or "").strip()


def _duration_seconds(value):
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _format_duration_seconds(value):
    seconds = int(round(_duration_seconds(value)))
    if seconds <= 0:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _ytdlp_published_at(item):
    for key in ("upload_date", "release_date"):
        value = _parse_upload_date(item.get(key))
        if value:
            return value
    for key in ("timestamp", "release_timestamp"):
        try:
            value = float(item.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return _datetime.datetime.fromtimestamp(value, tz=_datetime.timezone.utc).date().isoformat()
    return ""


def _channel_subscribers(channel_url):
    if not channel_url or not _is_allowed_youtube_host_url(channel_url):
        return ""
    try:
        import yt_dlp

        ydl_opts = {
            **_base_ytdlp_opts(),
            "extract_flat": True,
            "ignoreerrors": True,
            "noplaylist": False,
            "playlistend": 1,
            "quiet": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            channel = ydl.extract_info(channel_url, download=False) or {}
        return _format_subscribers_w(channel.get("channel_follower_count"))
    except Exception:
        backend_logger.info(
            "YouTube channel subscribers unavailable : channelUrl = %s",
            channel_url,
        )
        return ""


def _co_creators(item):
    creators = item.get("creators") or []
    if isinstance(creators, str):
        creators = [creator.strip() for creator in creators.split(",")]
    return [str(creator).strip() for creator in creators if str(creator).strip()]


def _video_from_ytdlp_info(item, fallback_url=""):
    video_id = item.get("id") or _extract_youtube_video_id(fallback_url)
    url = item.get("webpage_url") or item.get("original_url") or fallback_url
    if video_id and (not url or not str(url).startswith("http")):
        url = f"https://www.youtube.com/watch?v={video_id}"
    if not _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(str(video_id or "")):
        video_id = ""
    url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    subscribers = _format_subscribers_w(item.get("channel_follower_count") or item.get("uploader_follower_count"))
    creators = _co_creators(item)
    if not subscribers:
        subscribers = _channel_subscribers(item.get("channel_url") or item.get("uploader_url"))
    if not subscribers and len(creators) > 1:
        subscribers = "存在联合创作者"
    return {
        "id": video_id or "",
        "title": item.get("title") or "",
        "channel": item.get("channel") or item.get("uploader") or "",
        "subscribers": subscribers,
        "publishedAt": _ytdlp_published_at(item),
        "url": url or "",
        "thumbnail": item.get("thumbnail") or "",
        "duration": item.get("duration_string") or _format_duration_seconds(item.get("duration")),
        "durationSeconds": _duration_seconds(item.get("duration")),
        "viewCount": int(item.get("view_count") or 0),
    }


def _import_youtube_video_by_url(url, *, quick_metadata=False):
    url = _validate_youtube_url(url)
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("未安装 yt-dlp，请先安装依赖。") from exc

    ydl_opts = {
        **_base_ytdlp_opts(include_ffmpeg=True),
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": False,
    }
    if quick_metadata:
        ydl_opts.update({"socket_timeout": 8, "retries": 0, "extractor_retries": 0})
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    video = _video_from_ytdlp_info(info or {}, url)
    if not video.get("id") or not video.get("url"):
        raise RuntimeError("未能识别 YouTube 视频链接。")
    return _enrich_video_from_watch_page(video)


def _search_youtube_fallback(query, limit):
    queries = [query]
    videos = []
    seen = set()

    for current_query in queries:
        if len(videos) >= limit:
            break
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(current_query)
        try:
            content = _fetch_text(url)
        except Exception:
            continue
        initial_data = _extract_yt_initial_data(content)
        if not initial_data:
            continue
        for node in _walk_dict(initial_data):
            renderer = node.get("videoRenderer")
            if not renderer:
                continue
            video_id = renderer.get("videoId")
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            title = _text_from_runs(renderer.get("title"))
            owner = _text_from_runs(renderer.get("ownerText"))
            published = _text_from_runs(renderer.get("publishedTimeText"))
            thumbnails = renderer.get("thumbnail", {}).get("thumbnails") or []
            videos.append({
                "id": video_id,
                "title": html.unescape(title),
                "channel": html.unescape(owner),
                "subscribers": "",
                "publishedAt": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": thumbnails[-1].get("url", "") if thumbnails else "",
                "duration": _text_from_runs(renderer.get("lengthText")),
            })
            if len(videos) >= limit:
                break

    for video in videos:
        if video["channel"]:
            continue
        try:
            encoded = urllib.parse.quote(video["url"], safe="")
            meta = _fetch_json(f"https://www.youtube.com/oembed?url={encoded}&format=json", timeout=8)
            video["title"] = video["title"] or meta.get("title", "")
            video["channel"] = meta.get("author_name", "")
        except Exception:
            pass
    return videos


def _enrich_video_from_watch_page(video):
    url = video.get("url")
    if not url:
        return video
    try:
        content = _fetch_text(url, timeout=12)
    except Exception:
        return video

    if not video.get("subscribers"):
        subscriber_match = re.search(
            r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"',
            content
        )
        if not subscriber_match:
            subscriber_match = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', content)
        if subscriber_match:
            video["subscribers"] = _format_subscribers_w(html.unescape(subscriber_match.group(1)))

    if not video.get("publishedAt") or " ago" in str(video.get("publishedAt")):
        publish_match = re.search(r'"publishDate":"([^"]+)"', content)
        if not publish_match:
            publish_match = re.search(r'"uploadDate":"([^"]+)"', content)
        if publish_match:
            video["publishedAt"] = _format_iso_date(publish_match.group(1))

    if not video.get("channel"):
        owner_match = re.search(r'"ownerChannelName":"([^"]+)"', content)
        if owner_match:
            video["channel"] = html.unescape(owner_match.group(1))

    duration_match = re.search(r'"lengthSeconds":"(\d+)"', content)
    if duration_match:
        seconds = int(duration_match.group(1))
        video["durationSeconds"] = seconds
        if not video.get("duration"):
            video["duration"] = f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    return video


def _enrich_video_metadata(video, job_id="", *, quick_metadata=False):
    """复用单链接导入的完整 yt-dlp 提取，网页解析仅作为降级。"""
    video_id = video.get("id") or _extract_youtube_video_id(video.get("url") or "")
    backend_logger.info(
        "YouTube metadata extraction started : jobId = %s | videoId = %s",
        job_id,
        video_id,
    )
    try:
        enriched = _import_youtube_video_by_url(video.get("url") or "", quick_metadata=quick_metadata)
        backend_logger.info(
            "YouTube metadata extraction completed : jobId = %s | videoId = %s | subscribers = %s | publishedAt = %s | duration = %s",
            job_id,
            enriched.get("id") or video_id,
            bool(enriched.get("subscribers")),
            bool(enriched.get("publishedAt")),
            bool(enriched.get("duration")),
        )
        return _merge_video_metadata(video, enriched)
    except Exception:
        backend_logger.exception(
            "YouTube metadata extraction failed : jobId = %s | videoId = %s | fallback = watch-page",
            job_id,
            video_id,
        )
        return _enrich_video_from_watch_page(video)


def _merge_video_metadata(search_item, detail_item):
    """详情接口偶尔缺少搜索摘要字段，按字段保留两者中可用的数据。"""
    merged = dict(search_item or {})
    for key, value in (detail_item or {}).items():
        if value not in (None, "", 0, 0.0, []):
            merged[key] = value
    duration_seconds = _duration_seconds(merged.get("durationSeconds") or merged.get("duration"))
    merged["durationSeconds"] = duration_seconds
    if not merged.get("duration"):
        merged["duration"] = _format_duration_seconds(duration_seconds)
    if not merged.get("publishedAt"):
        merged["publishedAt"] = _ytdlp_published_at(detail_item or search_item or {})
    return merged


def _dedupe_videos(videos, limit):
    filtered = []
    seen = set()
    for video in videos:
        url = video.get("url") or ""
        video_id = video.get("id") or url
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        filtered.append(video)
        if len(filtered) >= limit:
            break
    return filtered


def _enrich_videos(videos):
    return [_enrich_video_metadata(video) for video in videos]


def _row_to_youtube_search_job(row):
    item = dict(row)
    return {
        "jobId": item.get("id") or "",
        "ownerUserId": int(item.get("owner_user_id") or 0),
        "query": item.get("query") or "",
        "requested": int(item.get("requested") or 0),
        "found": int(item.get("found") or 0),
        "created": int(item.get("created_count") or 0),
        "duplicate": int(item.get("duplicate_count") or 0),
        "skipped": int(item.get("skipped_count") or 0),
        "failed": int(item.get("failed_count") or 0),
        "durationFiltered": int(item.get("duration_filtered_count") or 0),
        "groupId": item.get("group_id"),
        "groupName": item.get("group_name_snapshot") or "",
        "durationMinSeconds": item.get("duration_min_seconds"),
        "durationMaxSeconds": item.get("duration_max_seconds"),
        "status": item.get("status") or "queued",
        "message": item.get("message") or "",
        "source": item.get("source") or "",
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "finishedAt": item.get("finished_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def _normalize_duration_range(min_seconds=None, max_seconds=None):
    def normalize(value, field):
        if value in (None, ""):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是整数") from exc
        if normalized < 0:
            raise ValueError(f"{field} 不能小于 0")
        return normalized

    minimum = normalize(min_seconds, "durationMinSeconds")
    maximum = normalize(max_seconds, "durationMaxSeconds")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("视频时长最小值不能大于最大值")
    return minimum, maximum


def _candidate_duration_seconds(video):
    try:
        seconds = float(video.get("durationSeconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds > 0:
        return seconds
    parsed = _duration_text_to_seconds(video.get("duration"))
    return float(parsed or 0)


def _duration_matches_search_job(video, job):
    minimum = job.get("durationMinSeconds")
    maximum = job.get("durationMaxSeconds")
    if minimum is None and maximum is None:
        return True
    seconds = _candidate_duration_seconds(video)
    if seconds <= 0:
        return False
    if minimum is not None and seconds < float(minimum):
        return False
    if maximum is not None and seconds > float(maximum):
        return False
    return True


def create_youtube_search_job(query, requested, owner_user_id, group_id=None, duration_min_seconds=None, duration_max_seconds=None):
    init_youtube_video_table()
    duration_min_seconds, duration_max_seconds = _normalize_duration_range(duration_min_seconds, duration_max_seconds)
    job_id = uuid.uuid4().hex
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        target_group = _resolve_youtube_group(cursor, owner_user_id, group_id)
        cursor.execute('''
        INSERT INTO youtube_search_jobs (
            id, query, requested, status, message, owner_user_id, group_id, group_name_snapshot,
            duration_min_seconds, duration_max_seconds, created_at, updated_at
        )
        VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_id, query, requested, "查询任务已提交", owner_user_id, target_group["id"], target_group["name"],
            duration_min_seconds, duration_max_seconds, timestamp, timestamp,
        ))
    return get_youtube_search_job(job_id, owner_user_id)


def get_youtube_search_job(job_id, owner_user_id=None):
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        if owner_user_id is None:
            cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ?", (job_id,))
        else:
            cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ? AND owner_user_id = ?", (job_id, owner_user_id))
        row = cursor.fetchone()
    if not row:
        raise LookupError("查询任务不存在")
    return _row_to_youtube_search_job(row)


def _claim_youtube_search_job(job_id):
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute('''
        UPDATE youtube_search_jobs
        SET status = 'running', message = ?, started_at = ?, updated_at = ?
        WHERE id = ? AND status = 'queued'
        ''', ("正在向 YouTube 请求候选视频", timestamp, timestamp, job_id))
        if cursor.rowcount == 0:
            return None
        cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ?", (job_id,))
        return _row_to_youtube_search_job(cursor.fetchone())


def _update_youtube_search_source(job_id, source):
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect() as conn:
        conn.execute('''
        UPDATE youtube_search_jobs
        SET source = ?, message = ?, updated_at = ?
        WHERE id = ? AND status = 'running'
        ''', (source, "正在逐条处理候选视频", timestamp, job_id))


def _existing_youtube_search_item(cursor, job_id, ordinal, video_id):
    if video_id:
        cursor.execute('''
        SELECT decision FROM youtube_search_job_items
        WHERE job_id = ? AND (ordinal = ? OR video_id = ?)
        LIMIT 1
        ''', (job_id, ordinal, video_id))
    else:
        cursor.execute('''
        SELECT decision FROM youtube_search_job_items
        WHERE job_id = ? AND ordinal = ?
        LIMIT 1
        ''', (job_id, ordinal))
    return cursor.fetchone()


def _record_youtube_search_item(cursor, job, ordinal, video, decision, error="", duration_filtered=False):
    video_id = str(video.get("id") or "").strip()
    if _existing_youtube_search_item(cursor, job["jobId"], ordinal, video_id):
        return False

    cursor.execute('''
    INSERT INTO youtube_search_job_items (
        job_id, ordinal, video_id, title, decision, error
    )
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        job["jobId"],
        ordinal,
        video_id,
        str(video.get("title") or "")[:500],
        decision,
        str(error or "")[:1000],
    ))
    count_column = {
        "created": "created_count",
        "duplicate": "duplicate_count",
        "skipped": "skipped_count",
        "failed": "failed_count",
    }[decision]
    found = int(job.get("found") or 0) + 1
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    duration_filtered_sql = ", duration_filtered_count = duration_filtered_count + 1" if duration_filtered else ""
    cursor.execute(f'''
    UPDATE youtube_search_jobs
    SET found = found + 1,
        {count_column} = {count_column} + 1,
        message = ?,
        updated_at = ?
        {duration_filtered_sql}
    WHERE id = ? AND status = 'running'
    ''', (f"已检索 {found} / {job['requested']}", timestamp, job["jobId"]))
    return cursor.rowcount > 0


def _process_youtube_search_candidate(job_id, ordinal, video):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row or row["status"] != "running":
            return None
        job = _row_to_youtube_search_job(row)
        video_id = str(video.get("id") or "").strip()
        if _existing_youtube_search_item(cursor, job_id, ordinal, video_id):
            return None
        if not _duration_matches_search_job(video, job):
            _record_youtube_search_item(
                cursor,
                job,
                ordinal,
                video,
                "skipped",
                "视频时长不在所选范围内或时长未知",
                duration_filtered=True,
            )
            return "skipped"
        result = _save_one_youtube_video_with_cursor(
            cursor,
            video,
            job["query"],
            job["ownerUserId"],
            job["createdAt"],
            job["groupId"],
        )
        _record_youtube_search_item(cursor, job, ordinal, video, result["decision"])
        return result["decision"]


def _record_youtube_search_failure(job_id, ordinal, video, error):
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row or row["status"] != "running":
            return False
        job = _row_to_youtube_search_job(row)
        return _record_youtube_search_item(cursor, job, ordinal, video, "failed", error)


def _finish_youtube_search_job(job_id, status, message):
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect() as conn:
        conn.execute('''
        UPDATE youtube_search_jobs
        SET status = ?, message = ?, finished_at = ?, updated_at = ?
        WHERE id = ? AND status = 'running'
        ''', (status, message, timestamp, timestamp, job_id))


def fail_youtube_search_job(job_id, message):
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect() as conn:
        conn.execute('''
        UPDATE youtube_search_jobs
        SET status = 'failed', message = ?, finished_at = ?, updated_at = ?
        WHERE id = ? AND status IN ('queued', 'running')
        ''', (str(message or "查询任务失败")[:1000], timestamp, timestamp, job_id))
    return get_youtube_search_job(job_id)


def recover_interrupted_youtube_search_jobs():
    init_youtube_video_table()
    timestamp = _datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM youtube_search_jobs WHERE status IN ('queued', 'running')")
        job_ids = [row["id"] for row in cursor.fetchall()]
        if job_ids:
            cursor.execute('''
            UPDATE youtube_search_jobs
            SET status = 'failed', message = ?, finished_at = ?, updated_at = ?
            WHERE status IN ('queued', 'running')
            ''', ("应用重启后查询任务已中断，请重新查询", timestamp, timestamp))
    return job_ids


def run_youtube_search_job(job_id):
    job = _claim_youtube_search_job(job_id)
    if not job:
        return

    try:
        try:
            videos = _search_youtube_with_ytdlp(job["query"], job["requested"])
        except Exception:
            backend_logger.exception("YouTube search yt-dlp failed : jobId = %s | fallback = search-page", job_id)
            videos = []
        source = "yt-dlp"
        if not videos:
            videos = _search_youtube_fallback(job["query"], job["requested"])
            source = "youtube-search-page"
        videos = _dedupe_videos(videos, job["requested"])
        backend_logger.info(
            "YouTube search candidates ready : jobId = %s | source = %s | count = %s",
            job_id,
            source,
            len(videos),
        )
        _update_youtube_search_source(job_id, source)

        for ordinal, video in enumerate(videos, start=1):
            try:
                enriched = _enrich_video_metadata(video, job_id)
                decision = _process_youtube_search_candidate(job_id, ordinal, enriched)
                backend_logger.info(
                    "YouTube search candidate processed : jobId = %s | ordinal = %s | videoId = %s | decision = %s",
                    job_id,
                    ordinal,
                    enriched.get("id") or video.get("id") or "",
                    decision or "already-processed",
                )
            except Exception as exc:
                backend_logger.exception(
                    "YouTube search candidate failed : jobId = %s | ordinal = %s",
                    job_id,
                    ordinal,
                )
                _record_youtube_search_failure(job_id, ordinal, video, exc)

        current = get_youtube_search_job(job_id)
        message = f"查询完成，实际检索 {current['found']} 条"
        _finish_youtube_search_job(job_id, "success", message)
        backend_logger.info(
            "YouTube search completed : jobId = %s | groupId = %s | durationRange = %s-%s | source = %s | found = %s | created = %s | duplicate = %s | skipped = %s | failed = %s",
            job_id,
            current.get("groupId") or "",
            current.get("durationMinSeconds") if current.get("durationMinSeconds") is not None else "",
            current.get("durationMaxSeconds") if current.get("durationMaxSeconds") is not None else "",
            source,
            current["found"],
            current["created"],
            current["duplicate"],
            current["skipped"],
            current["failed"],
        )
    except Exception as exc:
        backend_logger.exception("YouTube search failed : jobId = %s", job_id)
        _finish_youtube_search_job(job_id, "failed", f"查询失败: {str(exc)}")

