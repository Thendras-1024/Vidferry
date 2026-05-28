def _get_youtube_video_record(video_id):
    if not video_id:
        return None
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return _row_to_youtube_video(row) if row else None


def _resolve_downloaded_source_file(job):
    record = _get_youtube_video_record(job.get("videoId"))
    downloaded_path = Path((record or {}).get("downloadedFilePath") or "")
    if downloaded_path.is_file():
        return downloaded_path

    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM file_records
        WHERE source_video_id = ? AND source_type = 'youtube_download'
        ORDER BY upload_time DESC, id DESC
        LIMIT 1
        ''', (job.get("videoId") or "",))
        material = cursor.fetchone()
        if material:
            material_path = _material_file_path(dict(material))
            if material_path and material_path.is_file():
                return material_path

    raise RuntimeError("未找到已下载视频文件，请先执行下载。")


def run_youtube_download_job(job_id):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
        source_file = _download_youtube_video(job)
        finish_workflow_event(event_id, "success", "下载完成", output_file_path=source_file)
        material = _register_downloaded_video_material(source_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="下载完成，已绑定到素材库",
            source_file_path=str(source_file),
            processed_file_path=str(source_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def run_youtube_translate_job(job_id):
    event_id = None
    analysis_event_id = None
    editing_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle",
            message=f"正在准备{language_meta['label']}字幕处理任务",
            progress=2,
            speed="",
            eta="",
        )
        source_file = _resolve_downloaded_source_file(job)

        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="处理版本二：正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在启动转写和处理",
            step="subtitle",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 5,
        )
        subtitle_result = _process_subtitles(job, source_file)
        if process_version != PROCESS_VERSION_EDITING:
            maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )
        final_message = "未检测到可识别人声，已跳过字幕处理并保存到素材库" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库"
        if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
            final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
        elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
            final_message = f"{final_message}；未找到可拼接的高光片段"
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            processed_file_path=str(processed_file),
            publish_command=f"material_id={material.get('id')}",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(editing_event_id or event_id or analysis_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def run_youtube_analysis_job(job_id, source_file_override=""):
    event_id = None
    try:
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="analysis",
            message="正在准备处理版本二剪辑方案",
            progress=4,
            speed="",
            eta="",
        )
        source_file = Path(source_file_override) if source_file_override else _resolve_downloaded_source_file(job)
        event_id = start_workflow_event(job, "analysis", "开始生成发布文案与内容总结", input_file_path=source_file)
        update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            message="已找到下载视频，正在复用转写文本分析内容",
            progress=8,
        )
        result, usage = _run_analysis_from_transcript_job(job, source_file)
        finish_workflow_event(
            event_id,
            "success",
            "发布文案与内容总结已生成",
            cloud_usage={
                "provider": usage.get("provider") or "openai-compatible",
                "model": usage.get("model") or LLM_MODEL,
                "tokens": int(usage.get("tokens") or 0),
                "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                "promptTokens": int(usage.get("promptTokens") or 0),
                "completionTokens": int(usage.get("completionTokens") or 0),
                "latencyMs": float(usage.get("latencyMs") or 0),
            },
            metadata={"highlightCount": len(result.get("highlight_segments") or [])},
        )
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message="发布文案与内容总结已生成，可在视频线索中查看",
            progress=100,
            speed="",
            eta="",
        )
    except Exception as exc:
        finish_workflow_event(event_id, "failed", str(exc))
        try:
            failed_job = get_youtube_workflow_job(job_id)
            update_youtube_video_analysis_status(failed_job.get("videoId"), 3, _analysis_error_payload(exc, failed_job))
        except Exception as status_exc:
            print(f"更新分析失败状态失败: {status_exc}")
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
            speed="",
            eta="",
        )


def _publish_to_douyin(job, processed_file):
    if not job["publishToDouyin"] or not job["account"]:
        return ""
    command = [
        SAU_COMMAND,
        "douyin",
        "upload-video",
        "--account",
        job["account"],
        "--file",
        str(processed_file),
        "--title",
        job["title"] or "YouTube 视频",
        "--desc",
        job["description"] or "",
        "--tags",
        ",".join(job["tags"]),
    ]
    if job["schedule"]:
        command.extend(["--schedule", job["schedule"]])
    command.append("--headless")
    _run_command(command, cwd=BASE_DIR)
    return " ".join(command)


def _publish_to_bilibili(job, processed_file):
    if not job["publishToBilibili"] or not job["bilibiliAccount"]:
        return ""
    command = [
        SAU_COMMAND,
        "bilibili",
        "upload-video",
        "--account",
        job["bilibiliAccount"],
        "--file",
        str(processed_file),
        "--title",
        job["title"] or "YouTube 视频",
        "--desc",
        job["description"] or job["url"] or "",
        "--tid",
        str(normalize_bilibili_tid(job["bilibiliTid"])),
        "--tags",
        ",".join(job["tags"]),
    ]
    if job["schedule"]:
        command.extend(["--schedule", job["schedule"]])
    _run_command(command, cwd=BASE_DIR)
    return " ".join(command)


def _publish_center_to_bilibili(title, description, file_list, tags, account_list, tid=None, enable_timer=False, videos_per_day=1, daily_times=None, start_days=0):
    if ensure_biliup_binary is None:
        raise RuntimeError("后端未加载 B 站 biliup 运行时，请检查依赖。")

    biliup_binary = ensure_biliup_binary(force_check=False)
    files = [Path(BASE_DIR / "videoFile" / file) for file in file_list]
    account_files = [Path(BASE_DIR / "cookiesFile" / file) for file in account_list]
    if enable_timer:
        try:
            from utils.files_times import generate_schedule_time_next_day
            normalized_daily_times = []
            for item in daily_times or []:
                if isinstance(item, str) and ":" in item:
                    normalized_daily_times.append(int(item.split(":", 1)[0]))
                else:
                    normalized_daily_times.append(int(item))
            publish_datetimes = generate_schedule_time_next_day(len(files), videos_per_day, normalized_daily_times, start_days=start_days)
        except Exception:
            publish_datetimes = [0 for _ in files]
    else:
        publish_datetimes = [0 for _ in files]

    for index, file in enumerate(files):
        if not file.is_file():
            raise RuntimeError(f"B站发布文件不存在: {file}")
        for cookie in account_files:
            if not cookie.is_file():
                raise RuntimeError(f"B站 Cookie 文件不存在: {cookie}")
            command = [
                str(biliup_binary),
                "-u",
                str(cookie),
                "upload",
                str(file),
                "--title",
                title,
                "--desc",
                description or "",
                "--tid",
                str(normalize_bilibili_tid(tid)),
            ]
            if tags:
                command.extend(["--tag", ",".join(tags)])
            publish_datetime = publish_datetimes[index] if index < len(publish_datetimes) else 0
            if publish_datetime:
                command.extend(["--dtime", str(int(publish_datetime.timestamp()))])
            result = _run_command(command, cwd=BASE_DIR)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "").strip() or "B站发布失败")


def _format_publish_schedule(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _build_publish_datetimes(file_count, enable_timer=False, videos_per_day=1, daily_times=None, start_days=0):
    if not enable_timer:
        return [0 for _ in range(file_count)]
    try:
        from utils.files_times import generate_schedule_time_next_day
        normalized_daily_times = []
        for item in daily_times or []:
            if isinstance(item, str) and ":" in item:
                normalized_daily_times.append(int(item.split(":", 1)[0]))
            else:
                normalized_daily_times.append(int(item))
        return generate_schedule_time_next_day(file_count, videos_per_day, normalized_daily_times, start_days=start_days)
    except Exception:
        return [0 for _ in range(file_count)]


def _publish_platform_slug(platform_type):
    return {
        1: "xiaohongshu",
        3: "douyin",
        5: "bilibili",
    }.get(int(platform_type or 0), "")


def _is_cookie_invalid_error(message):
    text = str(message or "")
    return "cookie文件已失效" in text or "cookie文件不存在或已失效" in text or "Cookie 已失效" in text


def _mark_account_abnormal(platform_type, account_file, reason=""):
    if not account_file:
        return
    try:
        with sqlite3.connect(_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE user_info
                SET status = 0
                WHERE type = ? AND filePath = ?
                ''',
                (int(platform_type or 0), str(account_file)),
            )
            conn.commit()
        print(f"发布账号状态已标记异常: platform={platform_type}, account={account_file}, reason={reason}", flush=True)
    except Exception as exc:
        print(f"标记发布账号异常失败: {exc}", flush=True)


def _run_isolated_publish_command(command, timeout=3600):
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        return subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [(exc.stdout or ""), (exc.stderr or "")] if part).strip()
        raise TimeoutError(output or f"平台发布超时: {' '.join(map(str, command))}") from exc


def _execute_publish_target(task):
    start_time = time.time()
    platform_type = int(task["platformType"])
    platform_slug = _publish_platform_slug(platform_type)
    publish_title = f"{task['title']}; description={task['description']}" if task["description"] else task["title"]
    result = {
        "publishTaskId": task.get("publishTaskId") or "",
        "platformType": platform_type,
        "platformName": task["platformName"],
        "accountName": task.get("accountName") or "",
        "publishedVideoIds": [],
        "status": "running",
        "message": "发布中",
        "durationMs": 0,
    }
    try:
        _mark_published_materials(
            task["fileList"],
            platform_type=platform_type,
            title=publish_title,
            account_count=1,
            account_file=task["accountFile"],
            publish_task_id=task.get("publishTaskId") or "",
            status="running",
            message="发布中",
            account_name=task.get("accountName") or "",
        )
        if not platform_slug:
            raise RuntimeError(f"{task['platformName']} 暂未接入稳定并发发布适配器")
        account_lock = _get_publish_account_lock(platform_type, task["accountFile"])
        with account_lock:
            for index, file_path in enumerate(task["absoluteFiles"]):
                command = [
                    sys.executable,
                    "-m",
                    "app.publish_runner",
                    "--platform",
                    platform_slug,
                    "--account-file",
                    str(task["accountPath"]),
                    "--file",
                    str(file_path),
                    "--title",
                    task["title"],
                    "--desc",
                    task["description"],
                    "--tags",
                    ",".join(task["tags"]),
                ]
                if task.get("headless"):
                    command.append("--headless")
                schedule = _format_publish_schedule(task["publishDatetimes"][index] if index < len(task["publishDatetimes"]) else 0)
                if schedule:
                    command.extend(["--schedule", schedule])
                if task.get("thumbnailPath"):
                    command.extend(["--thumbnail", task["thumbnailPath"]])
                if task.get("productLink"):
                    command.extend(["--product-link", task["productLink"]])
                if task.get("productTitle"):
                    command.extend(["--product-title", task["productTitle"]])
                if platform_type == 5:
                    command.extend(["--tid", str(normalize_bilibili_tid(task.get("bilibiliTid")))])
                process_result = _run_isolated_publish_command(command, timeout=task.get("timeoutSeconds") or 3600)
                if process_result.returncode != 0:
                    output = "\n".join(part for part in [(process_result.stderr or "").strip(), (process_result.stdout or "").strip()] if part)
                    raise RuntimeError(output or f"{task['platformName']} 发布失败")

        published_ids = _mark_published_materials(
            task["fileList"],
            platform_type=platform_type,
            title=publish_title,
            account_count=1,
            account_file=task["accountFile"],
            publish_task_id=task.get("publishTaskId") or "",
            status="success",
            message="发布成功",
            duration_ms=int((time.time() - start_time) * 1000),
            account_name=task.get("accountName") or "",
        )
        result.update({
            "publishedVideoIds": published_ids,
            "status": "success",
            "message": "发布成功",
        })
    except TimeoutError as exc:
        result.update({
            "status": "timeout",
            "message": str(exc),
        })
    except Exception as exc:
        if _is_cookie_invalid_error(str(exc)):
            _mark_account_abnormal(platform_type, task["accountFile"], str(exc))
        result.update({
            "status": "failed",
            "message": str(exc),
        })
    finally:
        result["durationMs"] = int((time.time() - start_time) * 1000)
        if result["status"] != "success":
            _mark_published_materials(
                task["fileList"],
                platform_type=platform_type,
                title=publish_title,
                account_count=1,
                account_file=task["accountFile"],
                publish_task_id=task.get("publishTaskId") or "",
                status=result["status"],
                message=result["message"],
                duration_ms=result["durationMs"],
                account_name=task.get("accountName") or "",
            )
    return result


def _build_publish_tasks(data, targets, file_list, publish_task_id=""):
    title = _safe_text(data.get("title"))
    description = _safe_text(data.get("description"))
    tags = _normalize_publish_tags(data.get("tags"))
    thumbnail_path = _safe_text(data.get("thumbnail"))
    product_link = _safe_text(data.get("productLink"))
    product_title = _safe_text(data.get("productTitle"))
    fallback_bilibili_tid = normalize_bilibili_tid(data.get("bilibiliTid"))
    publish_datetimes = _build_publish_datetimes(
        len(file_list),
        enable_timer=bool(data.get("enableTimer")),
        videos_per_day=data.get("videosPerDay") or 1,
        daily_times=data.get("dailyTimes"),
        start_days=data.get("startDays") or 0,
    )
    absolute_files = [Path(BASE_DIR / "videoFile" / file_path) for file_path in file_list]
    tasks = []
    for target in targets:
        account_file = _safe_text(target.get("accountFile"))
        platform_type = int(target.get("platformType") or 0)
        target_product_link = _safe_text(target.get("productLink")) if platform_type == 3 else product_link
        target_product_title = _safe_text(target.get("productTitle")) if platform_type == 3 else product_title
        target_bilibili_tid = normalize_bilibili_tid(target.get("bilibiliTid") or fallback_bilibili_tid) if platform_type == 5 else ""
        tasks.append({
            "publishTaskId": publish_task_id,
            "platformType": platform_type,
            "platformName": target.get("platformName") or platform_name(platform_type),
            "accountName": target.get("accountName") or "",
            "accountFile": account_file,
            "accountPath": Path(BASE_DIR / "cookiesFile" / account_file),
            "fileList": file_list,
            "absoluteFiles": absolute_files,
            "title": title,
            "description": description,
            "tags": tags,
            "thumbnailPath": thumbnail_path,
            "productLink": target_product_link,
            "productTitle": target_product_title,
            "bilibiliTid": target_bilibili_tid,
            "publishDatetimes": publish_datetimes,
            "timeoutSeconds": int(data.get("publishTimeoutSeconds") or 3600),
            "headless": bool(data.get("headless", False)),
        })
    return tasks


def _run_publish_tasks(tasks):
    if not tasks:
        return []
    max_workers = max(1, min(len(tasks), 3))
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_execute_publish_target, task): task for task in tasks}
        for future in as_completed(future_map):
            results.append(future.result())
    order = {int(task["platformType"]): index for index, task in enumerate(tasks)}
    results.sort(key=lambda item: order.get(int(item.get("platformType") or 0), 999))
    return results


def _publish_payload(data):
    if not data:
        raise ValueError("请求数据不能为空")
    file_list = data.get("fileList", [])
    if not file_list:
        raise ValueError("文件列表不能为空")
    if not _safe_text(data.get("title")):
        raise ValueError("标题不能为空")
    targets = normalize_publish_targets(data)
    file_list, publish_materials = _validate_publish_processed_files(file_list)
    publish_material = publish_materials[0]
    _assert_publish_targets_available(publish_material, targets)
    publish_task_id = uuid.uuid4().hex
    tasks = _build_publish_tasks(data, targets, file_list, publish_task_id=publish_task_id)
    for task in tasks:
        publish_title = f"{task['title']}; description={task['description']}" if task["description"] else task["title"]
        _mark_published_materials(
            task["fileList"],
            platform_type=task["platformType"],
            title=publish_title,
            account_count=1,
            account_file=task["accountFile"],
            publish_task_id=publish_task_id,
            status="pending",
            message="等待发布",
            account_name=task.get("accountName") or "",
        )
    results = _run_publish_tasks(tasks)
    published_video_ids = []
    for item in results:
        published_video_ids.extend(item.get("publishedVideoIds") or [])
    success_count = sum(1 for item in results if item["status"] == "success")
    failed_count = len(results) - success_count
    return {
        "publishedVideoIds": list(dict.fromkeys(published_video_ids)),
        "publishTaskId": publish_task_id,
        "results": results,
        "hasFailures": failed_count > 0,
        "successCount": success_count,
        "failedCount": failed_count,
    }


def run_youtube_workflow(job_id):
    workflow_event_id = None
    download_event_id = None
    analysis_event_id = None
    editing_event_id = None
    subtitle_event_id = None
    publish_event_id = None
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="download",
            message="正在使用 yt-dlp 下载视频",
            progress=0,
            speed="",
            eta="",
        )
        workflow_event_id = start_workflow_event(job, "workflow", "完整工作流开始")
        download_event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
        source_file = _download_youtube_video(job)
        finish_workflow_event(download_event_id, "success", "下载完成", output_file_path=source_file)
        update_youtube_video_artifacts(
            job["videoId"],
            download_status=1,
            downloaded_file_path=str(source_file),
        )

        process_version = _normalize_process_version(job.get("processVersion"))
        analysis_result = None
        editing_result = None
        if process_version == PROCESS_VERSION_EDITING:
            analysis_event_id = start_workflow_event(job, "analysis", "处理版本二：开始生成剪辑方案", input_file_path=source_file)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="analysis",
                message="视频已下载，正在提取震惊点和中外对比高光片段",
                progress=10,
                speed="",
                eta="",
            )
            analysis_result, usage = _process_editing_plan(job, source_file)
            finish_workflow_event(
                analysis_event_id,
                "success",
                "处理版本二剪辑方案已生成",
                output_file_path="",
                cloud_usage={
                    "provider": usage.get("provider") or "openai-compatible",
                    "model": usage.get("model") or LLM_MODEL,
                    "tokens": int(usage.get("tokens") or 0),
                    "totalTokens": int(usage.get("totalTokens") or usage.get("tokens") or 0),
                    "promptTokens": int(usage.get("promptTokens") or 0),
                    "completionTokens": int(usage.get("completionTokens") or 0),
                    "latencyMs": float(usage.get("latencyMs") or 0),
                },
                metadata={"highlightCount": len(analysis_result.get("highlight_segments") or [])},
            )

        job = update_youtube_workflow_job(
            job_id,
            source_file_path=str(source_file),
            step="subtitle",
            message=f"视频已下载，正在处理{language_meta['label']}字幕",
            progress=60 if process_version == PROCESS_VERSION_EDITING else 8,
            speed="",
            eta="",
        )
        subtitle_event_id = start_workflow_event(job, "subtitle", f"开始{language_meta['label']}字幕处理", input_file_path=source_file)
        subtitle_result = _process_subtitles(job, source_file)
        maybe_start_youtube_analysis_job(job, source_file)
        processed_file = subtitle_result["path"]
        finish_workflow_event(subtitle_event_id, "success", f"{language_meta['label']}字幕处理完成", output_file_path=processed_file)
        skipped_subtitles = bool(subtitle_result.get("skipped"))

        if process_version == PROCESS_VERSION_EDITING:
            editing_event_id = start_workflow_event(job, "editing", "处理版本二：开始拼接高光开头", input_file_path=processed_file)
            editing_work_dir = _ensure_dir(YOUTUBE_PROCESSED_DIR / f"{Path(processed_file).stem}_editing_intro_work")
            editing_result = _build_editing_intro_video(job, source_file, processed_file, analysis_result or {}, editing_work_dir)
            processed_file = editing_result["path"]
            highlight_count = len(editing_result.get("segments") or [])
            editing_message = (
                f"处理版本二高光开头已生成，已拼接 {highlight_count} 个片段"
                if not editing_result.get("skipped")
                else f"处理版本二未拼接高光开头：{editing_result.get('reason') or '无可用片段'}"
            )
            finish_workflow_event(
                editing_event_id,
                "success",
                editing_message,
                output_file_path=processed_file,
                metadata={"highlightCount": highlight_count},
            )

        material = _save_processed_video_to_material(processed_file, job)
        update_youtube_workflow_job(
            job_id,
            processed_file_path=str(processed_file),
            step="publish",
            message="未检测到可识别人声，已跳过字幕处理并保存到素材库，准备发布" if skipped_subtitles else f"{language_meta['label']}字幕视频已生成并保存到素材库，准备发布",
            progress=96,
            speed="",
            eta="",
        )
        update_youtube_video_artifacts(
            job["videoId"],
            translate_status=2 if skipped_subtitles else 1,
            processed_file_path=str(processed_file),
        )

        latest_job = get_youtube_workflow_job(job_id)
        publish_commands = []
        publish_event_id = start_workflow_event(latest_job, "publish", "开始发布", input_file_path=processed_file)
        douyin_command = _publish_to_douyin(latest_job, processed_file)
        if douyin_command:
            publish_commands.append(douyin_command)
            _mark_published_materials(
                [material.get("file_path") or material.get("storage_key")],
                platform_type=3,
                title=latest_job.get("title") or "YouTube 视频",
                account_count=1,
                account_file=latest_job.get("account") or "",
            )
        bilibili_command = _publish_to_bilibili(latest_job, processed_file)
        if bilibili_command:
            publish_commands.append(bilibili_command)
            _mark_published_materials(
                [material.get("file_path") or material.get("storage_key")],
                platform_type=5,
                title=latest_job.get("title") or "YouTube 视频",
                account_count=1,
                account_file=latest_job.get("bilibiliAccount") or "",
            )
        final_message = "任务完成"
        if not publish_commands:
            final_message = "任务完成，已保存到素材库，未配置抖音账号所以未发布"
        if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
            final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
        elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
            final_message = f"{final_message}；未找到可拼接的高光片段"
        if skipped_subtitles:
            final_message = f"{final_message}；未检测到可识别人声，已跳过字幕处理"
        finish_workflow_event(publish_event_id, "success", final_message, output_file_path=processed_file)
        finish_workflow_event(workflow_event_id, "success", final_message, output_file_path=processed_file)
        update_youtube_workflow_job(
            job_id,
            status="success",
            step="done",
            message=final_message,
            publish_command="\n".join(publish_commands),
            progress=100,
            speed="",
            eta="",
        )
        if publish_commands:
            update_youtube_video_artifacts(job["videoId"], publish_status=1)
    except Exception as exc:
        finish_workflow_event(publish_event_id or editing_event_id or subtitle_event_id or analysis_event_id or download_event_id or workflow_event_id, "failed", str(exc))
        if workflow_event_id:
            finish_workflow_event(workflow_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
        )


