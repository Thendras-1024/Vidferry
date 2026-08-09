"""多平台发布执行:发布任务构建、隔离子进程调用与账号失效处理。"""


from app.utils.time_util import _build_publish_datetimes, _format_publish_schedule, _parse_publish_schedule


def _publish_to_douyin(job, processed_file):
    if not job["publishToDouyin"] or not job["account"]:
        return ""
    account_info = _check_named_publish_account(3, job["account"], job.get("ownerUserId"))
    task = _workflow_publish_task(job, processed_file, 3, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 3, account_info["filePath"])
    return " ".join(command)


def _publish_to_bilibili(job, processed_file):
    if not job["publishToBilibili"] or not job["bilibiliAccount"]:
        return ""
    account_info = _check_named_publish_account(5, job["bilibiliAccount"], job.get("ownerUserId"))
    task = _workflow_publish_task(job, processed_file, 5, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 5, account_info["filePath"])
    return " ".join(command)


def _publish_to_xiaohongshu(job, processed_file):
    if not job.get("publishToXiaohongshu") or not job.get("xiaohongshuAccount"):
        return ""
    account_info = _check_named_publish_account(1, job["xiaohongshuAccount"], job.get("ownerUserId"))
    task = _workflow_publish_task(job, processed_file, 1, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 1, account_info["filePath"])
    return " ".join(command)


def _publish_to_kuaishou(job, processed_file):
    if not job.get("publishToKuaishou") or not job.get("kuaishouAccount"):
        return ""
    account_info = _check_named_publish_account(4, job["kuaishouAccount"], job.get("ownerUserId"))
    task = _workflow_publish_task(job, processed_file, 4, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 4, account_info["filePath"])
    return " ".join(command)


def _publish_to_tencent(job, processed_file):
    if not job.get("publishToTencent") or not job.get("tencentAccount"):
        return ""
    account_info = _check_named_publish_account(2, job["tencentAccount"], job.get("ownerUserId"))
    task = _workflow_publish_task(job, processed_file, 2, account_info)
    command = _workflow_publish_runner_command(task)
    _run_workflow_publish_command(command, 2, account_info["filePath"])
    return " ".join(command)


def _publish_platform_account_file(platform_type, account_name, owner_user_id=None):
    account_info = _check_named_publish_account(platform_type, account_name, owner_user_id)
    return account_info["filePath"] if account_info else ""


def _publish_workflow_platform(job, processed_file, material, platform_type, account_name):
    if not account_name:
        return None
    backend_logger.info("发布开始 job_id=%s platform_type=%s", job.get("id", ""), platform_type)
    publish_task_id = f"workflow:{job.get('id')}"
    file_path = material.get("file_path") or material.get("storage_key") or str(processed_file)
    try:
        account_info = _check_named_publish_account(platform_type, account_name, job.get("ownerUserId"))
    except Exception as exc:
        _mark_published_materials(
            [file_path],
            platform_type=platform_type,
            title=job.get("title") or "YouTube 视频",
            account_count=1,
            account_file="",
            publish_task_id=publish_task_id,
            status="failed",
            message=str(exc),
            account_name=account_name,
        )
        return {
            "platformType": platform_type,
            "platformName": platform_name(platform_type),
            "accountName": account_name,
            "status": "failed",
            "message": str(exc),
            "durationMs": 0,
        }

    task = _workflow_publish_task(job, processed_file, platform_type, account_info)
    task.update({
        "publishTaskId": publish_task_id,
        "accountName": account_name,
        "fileList": [file_path],
        "absoluteFiles": [Path(processed_file)],
        "timeoutSeconds": 3600,
    })
    result = _execute_publish_target(task)
    backend_logger.info("发布完成 job_id=%s platform_type=%s status=%s", job.get("id", ""), platform_type, result.get("status"))
    return result


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
            backend_logger.info("发布中心 B站发布开始 file_index=%s", index)
            result = _run_command(command, cwd=BASE_DIR)
            if result.returncode != 0:
                backend_logger.error("发布中心 B站发布失败 file_index=%s returncode=%s", index, result.returncode)
                raise RuntimeError((result.stderr or result.stdout or "").strip() or "B站发布失败")
            backend_logger.info("发布中心 B站发布完成 file_index=%s", index)


def _publish_platform_slug(platform_type):
    return {
        1: "xiaohongshu",
        2: "tencent",
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
        "accountPath": _safe_cookie_path(account_info["filePath"], owner_user_id=account_info.get("ownerUserId")),
        "absoluteFiles": [file_path],
        "fileList": [str(file_path)],
        "title": title,
        "description": description,
        "tags": job.get("tags") or [],
        "thumbnailPath": "",
        "productLink": "",
        "productTitle": "",
        "bilibiliTid": normalize_bilibili_tid(job.get("bilibiliTid")),
        "isDraft": bool(job.get("isDraft")) if platform_type == 2 else False,
        "publishDatetimes": [_parse_publish_schedule(job.get("schedule"))],
        "headless": False,
        "debug": True,
    }


def _workflow_publish_runner_command(task):
    return _publish_runner_command(task, task["absoluteFiles"][0], 0)


def _publish_runner_command(task, file_path, index=0):
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
    if task["platformType"] == 5:
        command.extend(["--tid", str(normalize_bilibili_tid(task.get("bilibiliTid")))])
    if task["platformType"] == 2 and task.get("isDraft"):
        command.append("--draft")
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
        backend_logger.warning(
            "publish account marked abnormal : platform_type = %s reason = cookie_invalid",
            platform_type,
        )
    except Exception as exc:
        backend_logger.exception(
            "publish account mark abnormal failed : platform_type = %s error_type = %s",
            platform_type,
            type(exc).__name__,
        )


# 进程级「在跑的发布子进程」注册表。键为 pid。仅用于关停时终止孤儿发布进程（R1），
# 不参与正常流程的并发控制（同账号串行仍由 _get_publish_account_lock 负责）。
_inflight_publish_processes = {}
_inflight_publish_processes_lock = threading.Lock()


def _register_inflight_publish_process(process):
    if process is None:
        return
    with _inflight_publish_processes_lock:
        _inflight_publish_processes[process.pid] = process


def _unregister_inflight_publish_process(process):
    if process is None:
        return
    with _inflight_publish_processes_lock:
        _inflight_publish_processes.pop(process.pid, None)


def terminate_inflight_publish_processes():
    """关停钩子调用：终止仍在运行的发布子进程。已结束的进程 terminate() 为 no-op，
    因此正常跑完的发布不受影响；只有「后端被关停/重启时还在跑」的孤儿会被中断。"""
    with _inflight_publish_processes_lock:
        processes = list(_inflight_publish_processes.values())
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
                backend_logger.info("terminated inflight publish subprocess : pid = %s", process.pid)
        except Exception as exc:
            backend_logger.warning(
                "terminate inflight publish subprocess failed : pid = %s error_type = %s",
                getattr(process, "pid", "?"), type(exc).__name__,
            )


def _run_isolated_publish_command(command, timeout=3600):
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    print(f"启动平台发布子进程: {' '.join(map(str, command))}", flush=True)
    process = None
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
        # 登记到进程级注册表：关停时由 terminate_inflight_publish_processes 终止，
        # 避免后端重启后孤儿子进程继续完成上传、却被恢复逻辑标 failed → 用户重建 → 重复上传。
        _register_inflight_publish_process(process)
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
    finally:
        _unregister_inflight_publish_process(process)


def _run_workflow_publish_command(command, platform_type, account_file, timeout=3600):
    result = _run_isolated_publish_command(command, timeout=timeout)
    if result.returncode == 0:
        return result
    output = "\n".join(part for part in [(result.stderr or "").strip(), (result.stdout or "").strip()] if part)
    if _is_cookie_invalid_error(output):
        _mark_account_abnormal(platform_type, account_file, output)
    raise RuntimeError(_publish_command_failure(output, f"{platform_name(platform_type)} 发布失败"))


def _publish_command_failure(output, fallback="发布失败"):
    """保留明确发布错误码；未知故障仅返回最后一条原始输出。"""
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for line in reversed(lines):
        marker = line.find("VF-PUBLISH-")
        if marker >= 0:
            return line[marker:]
    return lines[-1] if lines else fallback


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
    running_claimed = False
    external_started = False
    external_succeeded = False
    command_failed = False
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
            retry_of_task_id=task.get("retryOfTaskId") or "",
            retry_of_record_id=task.get("retryOfRecordId"),
            retry_source=task.get("retrySource") or "",
        )
        running_claimed = True
        if not platform_slug:
            raise RuntimeError(f"{task['platformName']} 暂未接入发布适配器")
        account_lock = _get_publish_account_lock(platform_type, task["accountFile"])
        with account_lock:
            for index, file_path in enumerate(task["absoluteFiles"]):
                command = _publish_runner_command(task, file_path, index)
                external_started = True
                process_result = _run_isolated_publish_command(command, timeout=task.get("timeoutSeconds") or 3600)
                if process_result.returncode != 0:
                    command_failed = True
                    output = "\n".join(part for part in [(process_result.stderr or "").strip(), (process_result.stdout or "").strip()] if part)
                    raise RuntimeError(_publish_command_failure(output, f"{task['platformName']} 发布失败"))

        external_succeeded = True
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
            retry_of_task_id=task.get("retryOfTaskId") or "",
            retry_of_record_id=task.get("retryOfRecordId"),
            retry_source=task.get("retrySource") or "",
        )
        result.update({
            "publishedVideoIds": published_ids,
            "status": "success",
            "message": "发布成功",
        })
    except TimeoutError as exc:
        backend_logger.exception("publish platform result uncertain after timeout : platform_type=%s", platform_type)
        result.update({
            "status": "unknown" if external_started else "timeout",
            "message": ("平台执行超时，结果待核验：" + str(exc)) if external_started else str(exc),
        })
    except WorkflowConflictError:
        # Reservation conflicts happen before platform execution and must not
        # overwrite the other task's record or enter failure finalization.
        raise
    except Exception as exc:
        if _is_cookie_invalid_error(str(exc)):
            _mark_account_abnormal(platform_type, task["accountFile"], str(exc))
        if external_succeeded or (external_started and not command_failed):
            result.update({
                "status": "unknown",
                "message": "平台命令已完成，但本地成功状态保存失败，需人工核验：" + str(exc),
            })
            backend_logger.exception("publish succeeded but local persistence failed : platform_type=%s", platform_type)
        else:
            backend_logger.exception("publish target failed : platform_type=%s", platform_type)
            result.update({
                "status": "failed",
                "message": str(exc),
            })
    finally:
        result["durationMs"] = int((time.time() - start_time) * 1000)
        if running_claimed and result["status"] != "success":
            try:
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
                    retry_of_task_id=task.get("retryOfTaskId") or "",
                    retry_of_record_id=task.get("retryOfRecordId"),
                    retry_source=task.get("retrySource") or "",
                )
            except Exception:
                backend_logger.exception("publish final status persistence failed : platform_type=%s", platform_type)
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
        owner_user_id = target.get("ownerUserId")
        platform_type = int(target.get("platformType") or 0)
        target_tags = _normalize_publish_tags(target.get("tags")) if "tags" in target else fallback_tags
        if platform_type == 3:
            target_tags = target_tags[:5]
        target_product_link = _safe_text(target.get("productLink")) if platform_type == 3 else product_link
        target_product_title = _safe_text(target.get("productTitle")) if platform_type == 3 else product_title
        target_bilibili_tid = normalize_bilibili_tid(target.get("bilibiliTid") or fallback_bilibili_tid) if platform_type == 5 else ""
        target_is_draft = bool(target.get("isDraft") or data.get("isDraft")) if platform_type == 2 else False
        tasks.append({
            "publishTaskId": publish_task_id,
            "platformType": platform_type,
            "platformName": target.get("platformName") or platform_name(platform_type),
            "accountName": target.get("accountName") or "",
            "accountFile": account_file,
            "accountPath": _safe_cookie_path(account_file, owner_user_id=owner_user_id),
            "ownerUserId": owner_user_id,
            "fileList": file_list,
            "absoluteFiles": absolute_files,
            "title": title,
            "description": description,
            "tags": target_tags,
            "thumbnailPath": thumbnail_path,
            "productLink": target_product_link,
            "productTitle": target_product_title,
            "bilibiliTid": target_bilibili_tid,
            "isDraft": target_is_draft,
            "publishDatetimes": publish_datetimes,
            "timeoutSeconds": int(data.get("publishTimeoutSeconds") or 3600),
            "headless": bool(data.get("headless", False)),
            "debug": bool(data.get("debug", True)),
            "retryOfTaskId": _safe_text(data.get("retryOfTaskId")),
            "retryOfRecordId": target.get("retryOfRecordId"),
            "retrySource": _safe_text(data.get("retrySource")),
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


def _mark_publish_tasks_pending(tasks):
    return reserve_publish_tasks_pending(tasks or [])


def _summarize_publish_results(results):
    # 发布中心与定时发布共用：由各目标执行结果聚合成功/失败计数与已发布视频。
    results = list(results or [])
    published_video_ids = []
    for item in results:
        published_video_ids.extend(item.get("publishedVideoIds") or [])
    success_count = sum(1 for item in results if item.get("status") == "success")
    unknown_count = sum(1 for item in results if item.get("status") == "unknown")
    failed_count = sum(1 for item in results if item.get("status") in {"failed", "timeout"})
    return {
        "publishedVideoIds": list(dict.fromkeys(published_video_ids)),
        "successCount": success_count,
        "failedCount": failed_count,
        "unknownCount": unknown_count,
        "hasFailures": failed_count > 0 or unknown_count > 0,
        "hasUnknown": unknown_count > 0,
    }


def _publish_payload(data):
    if not data:
        raise ValueError("请求数据不能为空")
    file_list = data.get("fileList", [])
    if not file_list:
        raise ValueError("文件列表不能为空")
    if not _safe_text(data.get("title")):
        raise ValueError("标题不能为空")
    targets = normalize_publish_targets(data)
    _check_accounts_for_publish(targets)
    file_list, publish_materials = _validate_publish_processed_files(file_list)
    publish_material = publish_materials[0]
    _assert_publish_targets_available(publish_material, targets)
    # Agent 质检是可选能力；普通发布只保留来源内容风险确认。
    agent_guard = validate_prepublish_guard_or_raise(
        data, file_list, targets, publish_materials, check_agent=False
    )
    publish_task_id = uuid.uuid4().hex
    tasks = _build_publish_tasks(data, targets, file_list, publish_task_id=publish_task_id)
    _mark_publish_tasks_pending(tasks)
    results = _run_publish_tasks(tasks)
    return {
        **_summarize_publish_results(results),
        "publishTaskId": publish_task_id,
        "results": results,
        "agentGuard": agent_guard,
    }
