"""登录流程调度与 SSE 流式输出辅助函数。"""

from app.utils.sse_util import build_sse_stream


class _LoginStatusQueue:
    def __init__(self, queue, account_id, owner_user_id):
        self._queue = queue
        self._account_id = account_id
        self._owner_user_id = owner_user_id

    def put(self, message, *args, **kwargs):
        self._queue.put(message, *args, **kwargs)
        if message == "200" and self._account_id is not None:
            try:
                resolve_publish_cookie_invalid_notifications(self._account_id, self._owner_user_id)
            except Exception:
                backend_logger.exception(
                    "resolve cookie invalid notification failed : account_id = %s",
                    self._account_id,
                )


def run_async_function(type,id,status_queue,account_id=None,owner_user_id=None):
    status_queue = _LoginStatusQueue(status_queue, account_id, owner_user_id)
    if type == '5':
        bilibili_cookie_gen(id, status_queue, account_id, owner_user_id)
        return

    if not all([xiaohongshu_cookie_gen, get_tencent_cookie, douyin_cookie_gen, get_ks_cookie]):
        status_queue.put("500")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        match type:
            case '1':
                loop.run_until_complete(xiaohongshu_cookie_gen(id, status_queue, account_id, owner_user_id))
            case '2':
                loop.run_until_complete(get_tencent_cookie(id,status_queue, account_id, owner_user_id))
            case '3':
                loop.run_until_complete(douyin_cookie_gen(id,status_queue, account_id, owner_user_id))
            case '4':
                loop.run_until_complete(get_ks_cookie(id,status_queue, account_id, owner_user_id))
            case _:
                status_queue.put("500")
    except Exception as e:
        print(f"登录流程异常 : error_type = {type(e).__name__}")
        status_queue.put("500")
    finally:
        loop.close()

def sse_stream(status_queue, queue_key=None):
    yield from build_sse_stream(status_queue, active_queues, queue_key)


_shutdown_marked = False
_previous_signal_handlers = {}


