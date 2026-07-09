"""多平台发布执行:发布任务构建、隔离子进程调用与账号失效处理。"""


from app.utils.time_util import _build_publish_datetimes, _format_publish_schedule, _parse_publish_schedule


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
        (job["tags"] or [])[:5],
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
    publish_datetimes = _build_publish_datetimes(
        len(files),
        enable_timer=enable_timer,
        videos_per_day=videos_per_day,
        daily_times=daily_times,
        start_days=start_days,
    )

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
    return (
        "cookie文件已失效" in text
        or "cookie文件不存在或已失效" in text
        or "Cookie 已失效" in text
        or "VF-PUBLISH-COOKIE-INVALID" in text
        or "请重新连接账号" in text
    )


def _mark_account_abnormal(platform_type, account_file, reason=""):
    if not account_file:
        return
    try:
        with _db_connect() as conn:
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
            raise RuntimeError(f"{task['platformName']} 暂未接入发布适配器")
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
    fallback_tags = _normalize_publish_tags(data.get("tags"))
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
        target_tags = _normalize_publish_tags(target.get("tags")) if "tags" in target else fallback_tags
        if platform_type == 3:
            target_tags = target_tags[:5]
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
            "tags": target_tags,
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


def _run_publish_tasks(tasks):
    results = []
    task_list = list(tasks or [])
    for index, task in enumerate(task_list):
        results.append(_execute_publish_target(task))
        if index < len(task_list) - 1:
            from utils.humanize import jitter_seconds
            time.sleep(jitter_seconds(3.5, ratio=0.43, min_seconds=2, max_seconds=5))
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
    agent_guard = validate_prepublish_guard_or_raise(data, file_list, targets, publish_materials)
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
        "agentGuard": agent_guard,
    }
