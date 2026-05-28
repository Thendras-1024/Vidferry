def run_async_function(type,id,status_queue,account_id=None):
    if type == '5':
        bilibili_cookie_gen(id, status_queue, account_id)
        return

    if not all([xiaohongshu_cookie_gen, get_tencent_cookie, douyin_cookie_gen, get_ks_cookie]):
        status_queue.put("500")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        match type:
            case '1':
                loop.run_until_complete(xiaohongshu_cookie_gen(id, status_queue, account_id))
            case '2':
                loop.run_until_complete(get_tencent_cookie(id,status_queue, account_id))
            case '3':
                loop.run_until_complete(douyin_cookie_gen(id,status_queue, account_id))
            case '4':
                loop.run_until_complete(get_ks_cookie(id,status_queue, account_id))
            case _:
                status_queue.put("500")
    except Exception as e:
        print(f"登录流程异常: {e}")
        status_queue.put("500")
    finally:
        loop.close()

# SSE 流生成器函数
def sse_stream(status_queue, queue_key=None):
    try:
        while True:
            if not status_queue.empty():
                msg = status_queue.get()
                yield f"data: {msg}\n\n"
                if msg in {"200", "500"}:
                    break
            else:
                # 避免 CPU 占满
                time.sleep(0.1)
    finally:
        if queue_key:
            print(f"清理队列: {queue_key}")
            active_queues.pop(queue_key, None)


_shutdown_marked = False
_previous_signal_handlers = {}


