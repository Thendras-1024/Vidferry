"""服务器推送事件(SSE)与二维码流式输出辅助函数。"""

import time


def build_sse_stream(status_queue, active_queues, queue_key=None):
    try:
        while True:
            if not status_queue.empty():
                msg = status_queue.get()
                yield f"data: {msg}\n\n"
                if msg in {"200", "500"}:
                    break
            else:
                time.sleep(0.1)
    finally:
        if queue_key:
            print(f"清理队列: {queue_key}")
            active_queues.pop(queue_key, None)
