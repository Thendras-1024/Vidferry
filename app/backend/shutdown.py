def _mark_shutdown_once():
    global _shutdown_marked
    if _shutdown_marked:
        return
    _shutdown_marked = True
    try:
        interrupted = mark_shutdown_interrupted_jobs()
        if interrupted:
            print(f"已标记 {len(interrupted)} 个后端关闭中断任务")
    except Exception as exc:
        print(f"标记后端关闭中断任务失败: {exc}")


def _handle_shutdown_signal(signum, frame):
    _mark_shutdown_once()
    previous = _previous_signal_handlers.get(signum)
    if callable(previous):
        previous(signum, frame)
        return
    raise SystemExit(0)


def install_workflow_shutdown_handlers():
    atexit.register(_mark_shutdown_once)
    for signal_name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        try:
            _previous_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_shutdown_signal)
        except Exception as exc:
            print(f"注册 {signal_name} 关闭处理失败: {exc}")


