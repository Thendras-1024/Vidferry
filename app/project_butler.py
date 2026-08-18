"""Read-only project-butler queries for the Feishu robot."""

from __future__ import annotations

from app.db.base import _db_connect


_ATTENTION_WORDS = ("现在有什么要处理", "有什么要做", "待处理", "需要我", "需要处理")
_FAILURE_WORDS = ("为什么失败", "失败原因", "异常任务", "哪里出错", "报错")
_ACCOUNT_WORDS = ("账号是否正常", "账号状态", "账号异常")
_NEXT_WORDS = ("下一步", "接下来怎么做", "任务解释", "状态是什么意思")


def _agent_tool(name):
    """Agent tools are assembled into sau_backend at runtime."""
    import sau_backend
    return getattr(sau_backend, name)


def _init_database():
    _agent_tool("init_database_tables")()


def _account_status():
    return _agent_tool("get_account_status")()


def _workflow_overview():
    return _agent_tool("get_workflow_overview")()


def _failed_jobs():
    return _agent_tool("list_failed_jobs")()


def waiting_confirmation_jobs(limit=20):
    _init_database()
    with _db_connect(row_factory=True) as conn:
        rows = conn.execute(
            """
            SELECT id, video_id, title, status, step, message, updated_at, created_at
            FROM youtube_workflow_jobs
            WHERE status = 'waiting_confirmation'
            ORDER BY updated_at DESC, created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return {"total": len(rows), "items": [dict(row) for row in rows]}


def _abnormal_accounts():
    accounts = _account_status().get("items") or []
    return [item for item in accounts if item.get("status") != "valid"]


def butler_result(text):
    """Return deterministic help for common non-developer questions, else None."""
    message = str(text or "").strip()
    if not message:
        return None
    if any(word in message for word in _ATTENTION_WORDS):
        failures = _failed_jobs()
        waiting = waiting_confirmation_jobs()
        abnormal_accounts = _abnormal_accounts()
        accounts = {"total": len(abnormal_accounts), "items": abnormal_accounts}
        total = len(failures.get("items") or []) + waiting["total"] + accounts["total"]
        answer = "当前没有需要人工处理的事项。" if not total else f"当前有 {total} 项需要关注，我已按优先级整理如下。"
        return {"answer": answer, "toolResults": [
            {"tool": "list_failed_jobs", "result": failures},
            {"tool": "waiting_confirmation", "result": waiting},
            {"tool": "get_account_status", "result": accounts},
        ]}
    if any(word in message for word in _FAILURE_WORDS):
        return {"answer": "我已列出异常任务。优先查看失败阶段和原因；处理后可在 Web 控制台重新提交。", "toolResults": [
            {"tool": "list_failed_jobs", "result": _failed_jobs()},
        ]}
    if any(word in message for word in _ACCOUNT_WORDS):
        return {"answer": "以下是已配置发布账号的当前状态；异常账号需要在 Web 控制台重新登录或检查 Cookie。", "toolResults": [
            {"tool": "get_account_status", "result": _account_status()},
        ]}
    if any(word in message for word in _NEXT_WORDS):
        return {"answer": "任务会依次经过下载、处理、发布稿生成和发布前确认。需要执行操作时请进入 Web 控制台。", "toolResults": [
            {"tool": "get_workflow_overview", "result": _workflow_overview()},
        ]}
    return None


def card_action_result(action):
    prompts = {
        "failed": "为什么失败",
        "waiting": "现在有什么要处理",
        "overview": "下一步怎么做",
        "accounts": "账号是否正常",
    }
    return butler_result(prompts.get(str(action or ""), ""))
