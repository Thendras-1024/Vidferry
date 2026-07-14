"""YouTube 视频搜索与元数据抓取:yt-dlp 搜索、网页兜底解析、订阅数与发布日期补全。"""


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
        results.append({
            "id": video_id or "",
            "title": item.get("title") or "",
            "channel": item.get("channel") or item.get("uploader") or "",
            "subscribers": _format_count(item.get("channel_follower_count")),
            "publishedAt": _parse_upload_date(item.get("upload_date")),
            "url": url or "",
            "thumbnail": (item.get("thumbnail") or ""),
            "duration": item.get("duration_string") or "",
        })
    return results


def _extract_youtube_video_id(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0]
    return ""


def _canonical_youtube_url(url, video_id=""):
    normalized_video_id = video_id or _extract_youtube_video_id(url or "")
    if normalized_video_id:
        return f"https://www.youtube.com/watch?v={normalized_video_id}"
    return (url or "").strip()


def _video_from_ytdlp_info(item, fallback_url=""):
    video_id = item.get("id") or _extract_youtube_video_id(fallback_url)
    url = item.get("webpage_url") or item.get("original_url") or fallback_url
    if video_id and (not url or not str(url).startswith("http")):
        url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id or "",
        "title": item.get("title") or "",
        "channel": item.get("channel") or item.get("uploader") or "",
        "subscribers": _format_subscribers_w(item.get("channel_follower_count")),
        "publishedAt": _parse_upload_date(item.get("upload_date")) or _format_iso_date(item.get("release_date") or ""),
        "url": url or "",
        "thumbnail": item.get("thumbnail") or "",
        "duration": item.get("duration_string") or "",
    }


def _import_youtube_video_by_url(url):
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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    video = _video_from_ytdlp_info(info or {}, url)
    if not video.get("id") or not video.get("url"):
        raise RuntimeError("未能识别 YouTube 视频链接。")
    return _enrich_video_from_watch_page(video)


def _search_youtube_fallback(query, limit):
    queries = [query] + [q for q in YOUTUBE_FALLBACK_QUERIES if q != query]
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

    return video


def _dedupe_videos(videos, limit):
    filtered = []
    seen = set()
    for video in videos:
        url = video.get("url") or ""
        video_id = video.get("id") or url
        title = video.get("title") or ""
        if not video_id or video_id in seen:
            continue
        if not re.search(r"China|Chinese|Beijing|Shanghai|Shenzhen|Chongqing|Guangzhou|Chengdu|Guilin|Wuhan|Xi", title, re.I):
            continue
        if re.search(r"NYC|New York|accountant", title, re.I):
            continue
        seen.add(video_id)
        filtered.append(video)
        if len(filtered) >= limit:
            break
    return filtered


def _enrich_videos(videos):
    return [_enrich_video_from_watch_page(video) for video in videos]


def _row_to_youtube_search_job(row):
    item = dict(row)
    return {
        "jobId": item.get("id") or "",
        "query": item.get("query") or "",
        "requested": int(item.get("requested") or 0),
        "found": int(item.get("found") or 0),
        "created": int(item.get("created_count") or 0),
        "duplicate": int(item.get("duplicate_count") or 0),
        "skipped": int(item.get("skipped_count") or 0),
        "failed": int(item.get("failed_count") or 0),
        "status": item.get("status") or "queued",
        "message": item.get("message") or "",
        "source": item.get("source") or "",
        "createdAt": item.get("created_at") or "",
        "startedAt": item.get("started_at") or "",
        "finishedAt": item.get("finished_at") or "",
        "updatedAt": item.get("updated_at") or "",
    }


def create_youtube_search_job(query, requested):
    init_youtube_video_table()
    job_id = uuid.uuid4().hex
    timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect(row_factory=True) as conn:
        conn.execute('''
        INSERT INTO youtube_search_jobs (
            id, query, requested, status, message, created_at, updated_at
        )
        VALUES (?, ?, ?, 'queued', ?, ?, ?)
        ''', (job_id, query, requested, "查询任务已提交", timestamp, timestamp))
    return get_youtube_search_job(job_id)


def get_youtube_search_job(job_id):
    init_youtube_video_table()
    with _db_connect(row_factory=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_search_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    if not row:
        raise LookupError("查询任务不存在")
    return _row_to_youtube_search_job(row)


def _claim_youtube_search_job(job_id):
    timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
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
    timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
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


def _record_youtube_search_item(cursor, job, ordinal, video, decision, error=""):
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
    timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
    cursor.execute(f'''
    UPDATE youtube_search_jobs
    SET found = found + 1,
        {count_column} = {count_column} + 1,
        message = ?,
        updated_at = ?
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
        result = _save_one_youtube_video_with_cursor(
            cursor,
            video,
            job["query"],
            job["createdAt"],
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
    timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
    with _db_connect() as conn:
        conn.execute('''
        UPDATE youtube_search_jobs
        SET status = ?, message = ?, finished_at = ?, updated_at = ?
        WHERE id = ? AND status = 'running'
        ''', (status, message, timestamp, timestamp, job_id))


def run_youtube_search_job(job_id):
    job = _claim_youtube_search_job(job_id)
    if not job:
        return

    try:
        try:
            videos = _search_youtube_with_ytdlp(job["query"], job["requested"])
        except Exception:
            backend_logger.exception("YouTube 异步查询 yt-dlp 失败，准备使用网页兜底 job_id=%s", job_id)
            videos = []
        source = "yt-dlp"
        if not videos:
            videos = _search_youtube_fallback(job["query"], job["requested"])
            source = "youtube-search-page"
        videos = _dedupe_videos(videos, job["requested"])
        _update_youtube_search_source(job_id, source)

        for ordinal, video in enumerate(videos, start=1):
            try:
                enriched = _enrich_video_from_watch_page(video)
                _process_youtube_search_candidate(job_id, ordinal, enriched)
            except Exception as exc:
                backend_logger.exception(
                    "YouTube 异步查询候选处理失败 job_id=%s ordinal=%s",
                    job_id,
                    ordinal,
                )
                _record_youtube_search_failure(job_id, ordinal, video, exc)

        current = get_youtube_search_job(job_id)
        message = f"查询完成，实际检索 {current['found']} 条"
        _finish_youtube_search_job(job_id, "success", message)
        backend_logger.info(
            "YouTube 异步查询完成 job_id=%s source=%s found=%s created=%s duplicate=%s skipped=%s failed=%s",
            job_id,
            source,
            current["found"],
            current["created"],
            current["duplicate"],
            current["skipped"],
            current["failed"],
        )
    except Exception as exc:
        backend_logger.exception("YouTube 异步查询失败 job_id=%s", job_id)
        _finish_youtube_search_job(job_id, "failed", f"查询失败: {str(exc)}")

