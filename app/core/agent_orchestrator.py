"""Agent 对话编排:意图到工具的路由、执行与回答生成(LangGraph 优先,降级本地摘要)。"""


from __future__ import annotations

import json as _json
import time as _time
from typing import TypedDict


class _AgentState(TypedDict, total=False):
    session_id: str
    message: str
    context: dict
    history: list
    selected_tools: list
    tool_results: list
    answer: str


def _agent_llm_available():
    return bool(LLM_API_KEY and LLM_BASE_URL and AGENT_CHAT_MODEL)


def _call_agent_chat_llm(messages, max_tokens=None):
    if not _agent_llm_available():
        raise RuntimeError("LLM 未配置，Agent 已使用本地摘要回答。")
    payload = {
        "model": AGENT_CHAT_MODEL,
        "messages": messages,
        "temperature": AGENT_CHAT_TEMPERATURE,
        "max_tokens": int(max_tokens or AGENT_CHAT_MAX_TOKENS),
    }
    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
        data = _json.loads(response.read().decode("utf-8"))
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _select_agent_tools(message):
    text = str(message or "").lower()
    tools = []
    if any(word in text for word in ["流程", "步骤", "怎么运转", "完整"]):
        tools.extend([("explain_vidferry_pipeline", {}), ("get_workflow_overview", {})])
    if any(word in text for word in ["待处理", "初始", "还没处理"]):
        tools.append(("list_videos_by_status", {"status": "initial"}))
    if "已下载" in text or "下载了" in text:
        tools.append(("list_videos_by_status", {"status": "downloaded"}))
    if any(word in text for word in ["已处理", "处理后", "未发布"]):
        tools.append(("list_videos_by_status", {"status": "processed"}))
    if "已发布" in text or "发布了" in text:
        tools.extend([("list_videos_by_status", {"status": "published"}), ("list_publish_tasks", {})])
    if "失败" in text or "异常" in text or "报错" in text:
        tools.append(("list_failed_jobs", {}))
    if "账号" in text:
        tools.append(("get_account_status", {}))
    if "平台" in text or "哪" in text and "发" in text:
        tools.append(("get_video_detail", {"query": message}))
    if any(word in text for word in ["文案", "怎么改", "拦截", "质检"]):
        tools.append(("get_video_detail", {"query": message}))
    if not tools:
        tools.append(("get_workflow_overview", {}))

    deduped = []
    seen = set()
    for name, args in tools:
        key = (name, _json.dumps(args, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, args))
    return deduped[:AGENT_MAX_TOOL_CALLS]


def _run_agent_tool(name, args):
    if name == "get_workflow_overview":
        return get_workflow_overview()
    if name == "list_videos_by_status":
        return list_videos_by_status(args.get("status"), args.get("limit"))
    if name == "get_video_detail":
        return get_video_detail(args.get("query") or "")
    if name == "get_publish_platforms":
        return get_publish_platforms(args.get("videoId") or "")
    if name == "list_publish_tasks":
        return agent_list_publish_tasks(args.get("limit"))
    if name == "list_failed_jobs":
        return list_failed_jobs(args.get("limit"))
    if name == "get_account_status":
        return get_account_status()
    if name == "explain_vidferry_pipeline":
        return explain_vidferry_pipeline()
    raise ValueError(f"Agent 工具不在白名单中: {name}")


def _agent_fallback_answer(message, tool_results):
    lines = ["我查到这些信息："]
    for item in tool_results:
        name = item.get("tool")
        result = item.get("result") or {}
        if name == "get_workflow_overview":
            counts = result.get("counts") or {}
            lines.append(
                f"当前概览：待处理 {counts.get('initial', 0)}，已下载未处理 {counts.get('downloaded', 0)}，"
                f"已处理未发布 {counts.get('processed', 0)}，已发布 {counts.get('published', 0)}，失败 {counts.get('failed', 0)}。"
            )
        elif name == "list_videos_by_status":
            videos = result.get("items") or []
            title_list = "；".join((video.get("title") or video.get("id") or "未命名") for video in videos[:5])
            lines.append(f"{result.get('label')}共 {result.get('total', len(videos))} 条。{title_list or '当前没有匹配视频。'}")
        elif name == "get_video_detail":
            if not result.get("found"):
                lines.append(result.get("message") or "没找到对应视频。")
            else:
                platforms = result.get("platforms", {}).get("items") or []
                platform_text = "、".join(item.get("platform") or "" for item in platforms) or "暂无成功发布记录"
                lines.append(f"视频「{result.get('title')}」当前已发布平台：{platform_text}。")
        elif name == "list_failed_jobs":
            jobs = result.get("items") or []
            lines.append(f"最近失败/异常任务 {len(jobs)} 条。" + ("；".join(job.get("message") or job.get("id") for job in jobs[:3]) if jobs else ""))
        elif name == "get_account_status":
            accounts = result.get("items") or []
            bad = [item for item in accounts if item.get("status") != "valid"]
            lines.append(f"账号共 {len(accounts)} 个，异常 {len(bad)} 个。")
    lines.append("我目前只读查询和建议，不会直接执行发布、删除或登录。")
    return "\n".join(lines)


def _node_select_tools(state):
    state["selected_tools"] = _select_agent_tools(state.get("message") or "")
    return state


def _node_run_tools(state):
    results = []
    for name, args in state.get("selected_tools") or []:
        try:
            results.append({"tool": name, "args": args, "result": _run_agent_tool(name, args)})
        except Exception as exc:
            results.append({"tool": name, "args": args, "error": str(exc)})
    state["tool_results"] = results
    return state


def _node_answer(state):
    message = state.get("message") or ""
    tool_results = state.get("tool_results") or []
    if _agent_llm_available():
        try:
            state["answer"] = _call_agent_chat_llm([
                {
                    "role": "system",
                    "content": (
                        "你是 Vidferry 项目的只读运营 Agent。只能根据工具结果回答，"
                        "不能承诺执行发布、删除、登录、修改数据库，也不能输出 Cookie/API Key/本机绝对路径。"
                        "回答要中文、简洁、可操作。"
                    ),
                },
                {"role": "user", "content": f"用户问题：{message}\n页面上下文：{_json.dumps(state.get('context') or {}, ensure_ascii=False)}"},
                {"role": "user", "content": f"只读工具结果：{_json.dumps(tool_results, ensure_ascii=False)}"},
            ])
            return state
        except Exception as exc:
            state["llmError"] = str(exc)
    state["answer"] = _agent_fallback_answer(message, tool_results)
    return state


def _build_agent_graph():
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return None

    graph = StateGraph(_AgentState)
    graph.add_node("select_tools", _node_select_tools)
    graph.add_node("run_tools", _node_run_tools)
    graph.add_node("answer", _node_answer)
    graph.set_entry_point("select_tools")
    graph.add_edge("select_tools", "run_tools")
    graph.add_edge("run_tools", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


_AGENT_GRAPH = None


def run_agent_chat(message, session_id="", context=None):
    if not AGENT_ENABLED:
        raise RuntimeError("Agent 未启用。")
    started_at = _time.time()
    context = context or {}
    session_id = ensure_agent_session(session_id, context=context)
    save_agent_message(session_id, "user", message, context)

    global _AGENT_GRAPH
    if _AGENT_GRAPH is None:
        _AGENT_GRAPH = _build_agent_graph()
    if _AGENT_GRAPH is not None:
        state = _AGENT_GRAPH.invoke({"session_id": session_id, "message": message, "context": context})
    else:
        state = _node_answer(_node_run_tools(_node_select_tools({"session_id": session_id, "message": message, "context": context})))

    answer = state.get("answer") or "我暂时没有查到结果。"
    save_agent_message(session_id, "assistant", answer, {"toolResults": state.get("tool_results") or []})
    run_id = save_agent_run(
        "chat",
        session_id=session_id,
        input_summary={"message": message, "context": context},
        output={"answer": answer, "toolResults": state.get("tool_results") or []},
        model=AGENT_CHAT_MODEL,
        started_at=started_at,
    )
    return {
        "sessionId": session_id,
        "runId": run_id,
        "answer": answer,
        "toolResults": state.get("tool_results") or [],
    }
