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
    account_info = _check_named_publish_account(3, job["account"])
    source_path = Path(processed_file)
    video_filename = source_path.name
    video_file = Path(BASE_DIR / "videoFile" / video_filename)
    if not video_file.is_file():
        shutil.copy2(source_path, video_file)
    post_video_DouYin(
        job["title"] or "YouTube 视频",
        [video_filename],
        job["tags"],
        [account_info["filePath"]],
        enableTimer=False,
        thumbnail_path="",
        productLink="",
        productTitle="",
    )
    return f"douyin original publish {video_filename} --account {job['account']}"


def _publish_to_bilibili(job, processed_file):
    if not job["publishToBilibili"] or not job["bilibiliAccount"]:
        return ""
    account_info = _check_named_publish_account(5, job["bilibiliAccount"])
    task = _workflow_publish_task(job, processed_file, 5, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 5, account_info["filePath"])
    return " ".join(command)


def _publish_to_xiaohongshu(job, processed_file):
    if not job.get("publishToXiaohongshu") or not job.get("xiaohongshuAccount"):
        return ""
    account_info = _check_named_publish_account(1, job["xiaohongshuAccount"])
    task = _workflow_publish_task(job, processed_file, 1, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 1, account_info["filePath"])
    return " ".join(command)


def _publish_to_kuaishou(job, processed_file):
    if not job.get("publishToKuaishou") or not job.get("kuaishouAccount"):
        return ""
    account_info = _check_named_publish_account(4, job["kuaishouAccount"])
    task = _workflow_publish_task(job, processed_file, 4, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 4, account_info["filePath"])
    return " ".join(command)


def _publish_to_tencent(job, processed_file):
    if not job.get("publishToTencent") or not job.get("tencentAccount"):
        return ""
    if post_video_tencent is None:
        raise RuntimeError("后端未加载视频号发布模块，请检查依赖。")

    account_info = _check_named_publish_account(2, job["tencentAccount"])
    source_path = Path(processed_file)
    video_filename = source_path.name
    video_file = Path(BASE_DIR / "videoFile" / video_filename)
    if not video_file.is_file():
        shutil.copy2(source_path, video_file)

    post_video_tencent(
        job["title"] or "YouTube 视频",
        [video_filename],
        job["tags"],
        [account_info["filePath"]],
        enableTimer=False,
    )
    return f"videohao upload {video_filename} --account {job['tencentAccount']}"


def _publish_platform_account_file(platform_type, account_name):
    account_info = _check_named_publish_account(platform_type, account_name)
    return account_info["filePath"] if account_info else ""


def _publish_workflow_platform(job, processed_file, material, platform_type, account_name, command_factory):
    if not account_name:
        return ""
    command = command_factory(job, processed_file)
    if not command:
        return ""
    _mark_published_materials(
        [material.get("file_path") or material.get("storage_key")],
        platform_type=platform_type,
        title=job.get("title") or "YouTube 视频",
        account_count=1,
        account_file=_publish_platform_account_file(platform_type, account_name),
        account_name=account_name,
    )
    return command


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
        4: "kuaishou",
        3: "douyin",
        5: "bilibili",
    }.get(int(platform_type or 0), "")


def _workflow_publish_task(job, processed_file, platform_type, account_info):
    platform_type = int(platform_type or 0)
    title = job.get("title") or "YouTube 视频"
    description = job.get("description") or (job.get("url") if platform_type == 5 else "") or ""
    file_path = Path(processed_file)
    return {
        "platformType": platform_type,
        "platformName": platform_name(platform_type),
        "accountFile": account_info["filePath"],
        "accountPath": Path(BASE_DIR / "cookiesFile" / account_info["filePath"]),
        "absoluteFiles": [file_path],
        "fileList": [str(file_path)],
        "title": title,
        "description": description,
        "tags": job.get("tags") or [],
        "thumbnailPath": "",
        "productLink": "",
        "productTitle": "",
        "bilibiliTid": normalize_bilibili_tid(job.get("bilibiliTid")),
        "publishDatetimes": [_parse_publish_schedule(job.get("schedule"))],
        "headless": False,
        "debug": True,
    }


def _parse_publish_schedule(value):
    value = str(value or "").strip()
    if not value:
        return 0
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return value


def _workflow_publish_runner_command(task):
    platform_slug = _publish_platform_slug(task["platformType"])
    if not platform_slug:
        raise RuntimeError(f"{task['platformName']} 暂未接入发布适配器")
    command = [
        sys.executable,
        "-m",
        "app.publish_runner",
        "--platform",
        platform_slug,
        "--account-file",
        str(task["accountPath"]),
        "--file",
        str(task["absoluteFiles"][0]),
        "--title",
        task["title"],
        "--desc",
        task["description"],
        "--tags",
        ",".join(task["tags"]),
    ]
    if task.get("headless"):
        command.append("--headless")
    if task.get("debug"):
        command.append("--debug")
    schedule = _format_publish_schedule(task["publishDatetimes"][0])
    if schedule:
        command.extend(["--schedule", schedule])
    if task.get("thumbnailPath"):
        command.extend(["--thumbnail", task["thumbnailPath"]])
    if task.get("productLink"):
        command.extend(["--product-link", task["productLink"]])
    if task.get("productTitle"):
        command.extend(["--product-title", task["productTitle"]])
    if task["platformType"] == 5:
        command.extend(["--tid", str(normalize_bilibili_tid(task.get("bilibiliTid")))])
    return command


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
    print(f"启动平台发布子进程: {' '.join(map(str, command))}", flush=True)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        output_lines = []
        started_at = time.time()
        while True:
            line = process.stdout.readline() if process.stdout else ""
            if line:
                output_lines.append(line)
                print(line.rstrip(), flush=True)
            if process.poll() is not None:
                if process.stdout:
                    rest = process.stdout.read()
                    if rest:
                        output_lines.append(rest)
                        print(rest.rstrip(), flush=True)
                break
            if time.time() - started_at > timeout:
                process.kill()
                output = "".join(output_lines).strip()
                raise TimeoutError(output or f"平台发布超时: {' '.join(map(str, command))}")
        output = "".join(output_lines)
        return subprocess.CompletedProcess(command, process.returncode, output, "")
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [(exc.stdout or ""), (exc.stderr or "")] if part).strip()
        raise TimeoutError(output or f"平台发布超时: {' '.join(map(str, command))}") from exc


def _run_workflow_publish_command(command, platform_type, account_file, timeout=3600):
    result = _run_isolated_publish_command(command, timeout=timeout)
    if result.returncode == 0:
        return result
    output = "\n".join(part for part in [(result.stderr or "").strip(), (result.stdout or "").strip()] if part)
    if _is_cookie_invalid_error(output):
        _mark_account_abnormal(platform_type, account_file, output)
    raise RuntimeError(output or f"{platform_name(platform_type)} 发布失败")


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
            if platform_type == 3:
                file_names = []
                for file_path in task["absoluteFiles"]:
                    source_path = Path(file_path)
                    video_filename = source_path.name
                    video_file = Path(BASE_DIR / "videoFile" / video_filename)
                    if not video_file.is_file():
                        shutil.copy2(source_path, video_file)
                    file_names.append(video_filename)
                post_video_DouYin(
                    task["title"],
                    file_names,
                    task["tags"],
                    [task["accountFile"]],
                    enableTimer=False,
                    thumbnail_path=task.get("thumbnailPath") or "",
                    productLink=task.get("productLink") or "",
                    productTitle=task.get("productTitle") or "",
                )
            else:
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
                    if task.get("debug"):
                        command.append("--debug")
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
            "debug": bool(data.get("debug", True)),
        })
    return tasks


def _publish_workflow_outputs(job_id, job, processed_file, material, workflow_event_id=None, skipped_subtitles=False, editing_result=None):
    latest_job = get_youtube_workflow_job(job_id)
    publish_commands = []
    publish_event_id = start_workflow_event(latest_job, "publish", "开始发布", input_file_path=processed_file)
    publish_specs = [
        (3, latest_job.get("account") or "", _publish_to_douyin),
        (5, latest_job.get("bilibiliAccount") or "", _publish_to_bilibili),
        (1, latest_job.get("xiaohongshuAccount") or "", _publish_to_xiaohongshu),
        (4, latest_job.get("kuaishouAccount") or "", _publish_to_kuaishou),
        (2, latest_job.get("tencentAccount") or "", _publish_to_tencent),
    ]
    for platform_type, account_name, command_factory in publish_specs:
        command = _publish_workflow_platform(latest_job, processed_file, material, platform_type, account_name, command_factory)
        if command:
            publish_commands.append(command)

    final_message = "任务完成"
    if not publish_commands:
        final_message = "任务完成，已保存到素材库，未配置发布平台账号所以未发布"
    process_version = _normalize_process_version(latest_job.get("processVersion"))
    if process_version == PROCESS_VERSION_EDITING and editing_result and not editing_result.get("skipped"):
        final_message = f"{final_message}；已拼接前三个高光片段到视频开头"
    elif process_version == PROCESS_VERSION_EDITING and editing_result and editing_result.get("skipped"):
        final_message = f"{final_message}；未找到可拼接的高光片段"
    if skipped_subtitles:
        final_message = f"{final_message}；未检测到可识别人声，已跳过字幕处理"

    finish_workflow_event(publish_event_id, "success", final_message, output_file_path=processed_file)
    if workflow_event_id:
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
    return publish_commands


def _processed_material_for_workflow(job):
    record = _get_youtube_video_record(job.get("videoId")) or {}
    processed_path = Path(record.get("processedFilePath") or "")
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        material = _find_latest_processed_material(cursor, job.get("videoId") or "", _normalize_process_version(job.get("processVersion")))
        if not material:
            material = _find_latest_youtube_material(cursor, job.get("videoId") or "", "youtube_processed")
    if material:
        material_path = _material_file_path(material)
        if material_path and material_path.is_file():
            return material_path, _row_to_material(material)
    if processed_path.is_file():
        return processed_path, _save_processed_video_to_material(processed_path, job)
    raise RuntimeError("未找到处理后视频，请先完成处理。")


def _video_has_processed_output(record):
    if not record:
        return False
    translate_status = int(record.get("translateStatus") or 0)
    if translate_status not in (1, 2):
        return False
    processed_path = Path(record.get("processedFilePath") or "")
    if processed_path.is_file():
        return True
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        material = _find_latest_youtube_material(cursor, record.get("id") or record.get("videoId") or "", "youtube_processed")
    if not material:
        return False
    material_path = _material_file_path(material)
    return bool(material_path and material_path.is_file())


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
    try:
        initial_job = get_youtube_workflow_job(job_id) or {}
        _, language_meta = _subtitle_language_meta(initial_job.get("subtitleLanguage"))
        process_version = _normalize_process_version(initial_job.get("processVersion"))
        video_record = _get_youtube_video_record(initial_job.get("videoId")) or {}
        if _video_has_processed_output(video_record):
            job = update_youtube_workflow_job(
                job_id,
                status="running",
                step="publish",
                message="已存在处理后视频，正在直接发布",
                progress=92,
                speed="",
                eta="",
            )
            workflow_event_id = start_workflow_event(job, "workflow", "从待发布状态继续发布")
            processed_file, material = _processed_material_for_workflow(job)
            update_youtube_workflow_job(
                job_id,
                processed_file_path=str(processed_file),
                step="publish",
                message="已复用处理后视频，准备发布",
                progress=96,
                speed="",
                eta="",
            )
            _publish_workflow_outputs(job_id, job, processed_file, material, workflow_event_id=workflow_event_id)
            return

        can_reuse_download = int(video_record.get("downloadStatus") or 0) == 1
        job = update_youtube_workflow_job(
            job_id,
            status="running",
            step="subtitle" if can_reuse_download else "download",
            message="已存在下载视频，正在准备处理" if can_reuse_download else "正在使用 yt-dlp 下载视频",
            progress=4 if can_reuse_download else 0,
            speed="",
            eta="",
        )
        workflow_event_id = start_workflow_event(job, "workflow", "完整工作流开始")
        if can_reuse_download:
            source_file = _resolve_downloaded_source_file(job)
            job = update_youtube_workflow_job(
                job_id,
                source_file_path=str(source_file),
                step="subtitle",
                message="已复用下载视频，正在准备处理",
                progress=6,
                speed="",
                eta="",
            )
        else:
            download_event_id = start_workflow_event(job, "download", "开始下载 YouTube 原视频")
            source_file = _download_youtube_video(job)
            finish_workflow_event(download_event_id, "success", "下载完成", output_file_path=source_file)
            _register_downloaded_video_material(source_file, job)
            update_youtube_video_artifacts(
                job["videoId"],
                download_status=1,
                downloaded_file_path=str(source_file),
            )

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

        _publish_workflow_outputs(
            job_id,
            job,
            processed_file,
            material,
            workflow_event_id=workflow_event_id,
            skipped_subtitles=skipped_subtitles,
            editing_result=editing_result,
        )
    except Exception as exc:
        finish_workflow_event(editing_event_id or subtitle_event_id or analysis_event_id or download_event_id or workflow_event_id, "failed", str(exc))
        if workflow_event_id:
            finish_workflow_event(workflow_event_id, "failed", str(exc))
        update_youtube_workflow_job(
            job_id,
            status="failed",
            step="failed",
            message=str(exc),
        )


