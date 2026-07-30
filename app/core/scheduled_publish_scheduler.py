"""本地定时发布任务的轮询、并发执行与关闭处理。"""


# 单机并发执行定时任务的上限。领取循环只做原子认领,具体发布在独立的 daemon
# 工作线程里并行推进(由下面的信号量限流),避免单个平台长超时(最长 1 小时)阻塞
# 其他到点任务。刻意不使用 ThreadPoolExecutor:它的工作线程在解释器退出时会被
# concurrent.futures._python_exit 串行 join,会把后端关停(Ctrl+C)卡到在跑的发布
# 跑完(最长 1 小时);daemon 线程则会被立即放弃,未完成的发布交由重启时的
# recover_interrupted_scheduled_publish_tasks 收口。同一账号的发布仍由
# _get_publish_account_lock 串行,这里只让不同视频/平台并行推进。
#
# 设计契约（D3，刻意不替换为 APScheduler）：
# - 部署形态：本地优先、单机单实例。APScheduler 同为进程内调度，崩溃/断电后同样不存活，
#   对本部署并无额外收益，反而引入依赖与 misfire 语义差异；故保留「DB 轮询认领」模型。
# - 轮询周期：_scheduled_publish_loop 每 10 秒认领一次到期任务（契约常量，改动需同步前端
#   「最早 1 分钟 granularity」预期）。
# - 认领原子性：_claim_due_scheduled_publish_task 用 BEGIN IMMEDIATE + UPDATE…WHERE
#   status='pending' + rowcount==1 保证同一任务不会被重复认领/重复触发。
# - 崩溃恢复：进程异常退出会留下 status='running' 的任务，下次 start 时由
#   recover_interrupted_scheduled_publish_tasks 统一收口（标 failed，提示人工核查）。
# - 时间基准：scheduled_at 为 naive 本地时间，单机固定时区（无 DST），见 service 层
#   _scheduled_now() 与 _parse_scheduled_publish_time 的注释。
SCHEDULED_PUBLISH_WORKERS = 4
_scheduled_publish_stop = threading.Event()
_scheduled_publish_thread = None
_scheduled_publish_slots = None
# 启动串行锁：确保「存活检查 + 恢复 + 信号量重建 + 起线程」原子完成，避免并发调用
# start_scheduled_publish_scheduler 时重建信号量或起出两个调度线程（R3）。
_scheduled_publish_start_lock = threading.Lock()


def fail_scheduled_publish_task(task_id, reason):
    now = _now_iso()
    message = clean_display_text(reason)
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scheduled_publish_tasks SET status = 'failed', message = ?, finished_at = ?, updated_at = ? WHERE id = ? AND status = 'running'",
            (message, now, now, task_id),
        )
        if cursor.rowcount != 1:
            return False
        cursor.execute("UPDATE scheduled_publish_targets SET status = 'failed', message = ?, finished_at = ?, updated_at = ? WHERE task_id = ? AND status IN ('pending', 'running')", (message, now, now, task_id))
        cursor.execute("UPDATE published_youtube_materials SET status = 'failed', message = ?, updated_at = ? WHERE publish_task_id = ? AND status IN ('pending', 'running')", (message, now, task_id))
    return True


def recover_interrupted_scheduled_publish_tasks():
    with _db_connect() as conn:
        task_ids = [row[0] for row in conn.execute("SELECT id FROM scheduled_publish_tasks WHERE status = 'running'").fetchall()]
    reason = "后端中断，任务执行结果未知，请人工核查平台后重新创建任务"
    for task_id in task_ids:
        fail_scheduled_publish_task(task_id, reason)
    return task_ids


def _run_scheduled_publish_task(task_id):
    try:
        run_scheduled_publish_task(task_id)
    except Exception as exc:
        backend_logger.exception("scheduled publish execution failed : task_id = %s | error_type = %s", task_id, type(exc).__name__)
        try:
            fail_scheduled_publish_task(task_id, f"执行异常：{exc}")
        except Exception as fail_exc:
            backend_logger.exception("scheduled publish failure finalization failed : task_id = %s | error_type = %s", task_id, type(fail_exc).__name__)
    finally:
        _scheduled_publish_slots.release()


def _scheduled_publish_loop():
    while not _scheduled_publish_stop.is_set():
        try:
            if _scheduled_publish_slots.acquire(blocking=False):
                task_id, submitted = "", False
                try:
                    task_id = _claim_due_scheduled_publish_task()
                    if task_id:
                        worker = threading.Thread(
                            target=_run_scheduled_publish_task,
                            args=(task_id,),
                            name="vidferry-scheduled-publish",
                            daemon=True,
                        )
                        worker.start()
                        submitted = True
                        continue
                finally:
                    if not submitted:
                        if task_id:
                            fail_scheduled_publish_task(task_id, "调度器未能启动发布执行")
                        _scheduled_publish_slots.release()
        except Exception as exc:
            backend_logger.exception("scheduled publish loop failed : error_type = %s", type(exc).__name__)
        _scheduled_publish_stop.wait(10)


def start_scheduled_publish_scheduler():
    global _scheduled_publish_thread, _scheduled_publish_slots
    with _scheduled_publish_start_lock:
        if _scheduled_publish_thread and _scheduled_publish_thread.is_alive():
            # 已在运行：直接返回，绝不重建信号量（否则会重置并发槽，短暂超额放行）。
            return
        recover_interrupted_scheduled_publish_tasks()
        _scheduled_publish_stop.clear()
        _scheduled_publish_slots = threading.BoundedSemaphore(SCHEDULED_PUBLISH_WORKERS)
        _scheduled_publish_thread = threading.Thread(target=_scheduled_publish_loop, name="vidferry-scheduled-dispatch", daemon=True)
        _scheduled_publish_thread.start()


def stop_scheduled_publish_scheduler():
    _scheduled_publish_stop.set()
    # 终止在跑的发布子进程：调度线程与 daemon 工作线程在关停时被放弃（不等待，避免被最长
    # 1 小时的发布卡死后端关停），但子进程必须显式终止，否则重启后孤儿完成上传、被恢复逻辑
    # 标 failed、用户重建任务 → 重复上传（R1）。
    try:
        terminate_inflight_publish_processes()
    except Exception as exc:
        backend_logger.warning("terminate inflight publish processes on stop failed : error_type = %s", type(exc).__name__)
    if _scheduled_publish_thread and _scheduled_publish_thread.is_alive():
        _scheduled_publish_thread.join()
