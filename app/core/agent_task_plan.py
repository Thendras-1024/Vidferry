"""Small, serializable task plans for the project Agent UI."""

from __future__ import annotations


_COPYWRITING_WORDS = ("文案", "标题", "话题", "标签", "发布稿")
_COPYWRITING_ACTIONS = ("改", "修改", "重写", "优化", "调整", "换", "不好")
_EXECUTION_WORDS = ("下载", "处理", "转写", "字幕", "剪辑", "发布", "分发", "预约", "定时")
_SEARCH_WORDS = ("搜索", "搜", "查询", "查找", "寻找", "推荐", "状态", "信息", "详情", "素材", "项目")


def _has_any(text, words):
    return any(word in text for word in words)


def _step(step_id, title, status="pending", detail="", card=""):
    return {
        "id": step_id,
        "title": title,
        "status": status,
        "detail": detail,
        "card": card,
    }


def infer_agent_task_kind(message, context=None):
    text = str(message or "").strip().lower()
    if _has_any(text, _COPYWRITING_WORDS) and _has_any(text, _COPYWRITING_ACTIONS):
        return "copywriting"
    if _has_any(text, _EXECUTION_WORDS) and (
        isinstance((context or {}).get("videoContext"), dict)
        or bool((context or {}).get("videoSelection"))
    ):
        return "video_execution"
    if _has_any(text, _SEARCH_WORDS):
        return "project_query"
    return "conversation"


def _copywriting_plan(context, proposal):
    proposal = proposal if isinstance(proposal, dict) else {}
    video_context = context.get("videoContext") if isinstance(context, dict) else {}
    video_context = video_context if isinstance(video_context, dict) else {}
    status = str(proposal.get("status") or "")
    total = len(proposal.get("selectedVideoIds") or [])
    current = int(proposal.get("currentIndex") or 0) + 1
    has_video = bool(proposal.get("selectedVideoId") or video_context.get("videoId"))
    if status == "selecting_video":
        steps = [
            _step("understand", "理解改写要求", "completed"),
            _step("select_video", "确认目标视频", "waiting_user", "请从视频卡片中选择", "video_selection"),
            _step("load_video", "读取视频信息与原分析", "pending"),
            _step("generate_drafts", "生成文案候选", "pending"),
            _step("save_draft", "保存为待发布稿", "pending"),
        ]
        return steps, "waiting_user", "video_selection"
    if status == "ready":
        steps = [
            _step("understand", "理解改写要求", "completed"),
            _step("select_video", "确认目标视频", "completed"),
            _step("load_video", "读取视频信息与原分析", "completed"),
            _step("generate_drafts", "生成文案候选", "completed"),
            _step("save_draft", "保存为待发布稿", "waiting_user", f"第 {current} / {max(total, current)} 条：请选择并确认一份文案", "copywriting_selection"),
        ]
        return steps, "waiting_user", "copywriting_selection"
    if status == "confirmed":
        return [
            _step("understand", "理解改写要求", "completed"),
            _step("select_video", "确认目标视频", "completed"),
            _step("load_video", "读取视频信息与原分析", "completed"),
            _step("generate_drafts", "生成文案候选", "completed"),
            _step("save_draft", "保存为待发布稿", "completed", proposal.get("resultMessage") or "已保存"),
        ], "completed", ""
    if status in {"unavailable", "expired"}:
        return [
            _step("understand", "理解改写要求", "completed"),
            _step("select_video", "确认目标视频", "failed", proposal.get("message") or "提案不可用"),
        ], "failed", ""
    return [
        _step("understand", "理解改写要求", "active"),
        _step("select_video", "确认目标视频", "completed" if has_video else "pending"),
        _step("load_video", "读取视频信息与原分析", "pending"),
        _step("generate_drafts", "生成文案候选", "pending"),
        _step("save_draft", "保存为待发布稿", "pending"),
    ], "running", ""


def _proposal_plan(proposal, title, selection_id, action_id):
    proposal = proposal if isinstance(proposal, dict) else {}
    status = str(proposal.get("status") or "")
    if status == "pending":
        return [
            _step("understand", "理解任务", "completed"),
            _step(selection_id, "核对目标与参数", "waiting_user", "请核对卡片后确认", "proposal_confirmation"),
            _step(action_id, title, "pending"),
        ], "waiting_user", "proposal_confirmation"
    if status == "confirmed":
        return [
            _step("understand", "理解任务", "completed"),
            _step(selection_id, "核对目标与参数", "completed"),
            _step(action_id, title, "completed", proposal.get("resultMessage") or "已提交"),
        ], "completed", ""
    if status in {"expired", "failed"}:
        return [
            _step("understand", "理解任务", "completed"),
            _step(selection_id, "核对目标与参数", "failed", proposal.get("resultMessage") or "提案不可用"),
        ], "failed", ""
    return [
        _step("understand", "理解任务", "active"),
        _step(selection_id, "核对目标与参数", "pending"),
        _step(action_id, title, "pending"),
    ], "running", ""


def build_agent_task_plan(
    message,
    context=None,
    *,
    copywriting_proposal=None,
    import_proposal=None,
    execution_proposal=None,
    tool_results=None,
    safety_decision=None,
):
    """Return a UI-safe plan; it never grants an operation permission."""
    context = context if isinstance(context, dict) else {}
    kind = infer_agent_task_kind(message, context)
    if safety_decision and not safety_decision.get("allowed", True):
        return {
            "version": "agent-task-plan-v1",
            "kind": kind,
            "title": "处理请求",
            "status": "blocked",
            "waitingFor": "",
            "steps": [_step("safety", "安全检查", "failed", safety_decision.get("reason") or "请求未获允许")],
        }
    if kind == "copywriting":
        steps, status, waiting_for = _copywriting_plan(context, copywriting_proposal)
        title = "改写待发布文案"
    elif import_proposal:
        steps, status, waiting_for = _proposal_plan(import_proposal, "导入并执行视频任务", "select_candidates", "run_import")
        title = "导入视频线索"
    elif execution_proposal:
        steps, status, waiting_for = _proposal_plan(execution_proposal, execution_proposal.get("actionLabel") or "执行视频任务", "confirm_execution", "run_execution")
        title = execution_proposal.get("actionLabel") or "执行视频任务"
    elif kind == "project_query":
        has_results = bool(tool_results)
        steps = [
            _step("understand", "理解查询目标", "completed" if has_results else "active"),
            _step("query", "读取项目数据", "completed" if has_results else "active", card="query_results"),
            _step("summarize", "整理结果", "completed" if has_results else "pending"),
        ]
        status, waiting_for, title = ("completed", "", "查询项目状态") if has_results else ("running", "", "查询项目状态")
    else:
        steps = [_step("understand", "理解请求", "active")]
        status, waiting_for, title = "running", "", "处理请求"
    return {
        "version": "agent-task-plan-v1",
        "kind": kind,
        "title": title,
        "status": status,
        "waitingFor": waiting_for,
        "steps": steps,
    }
