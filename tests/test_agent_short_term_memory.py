import json
from pathlib import Path

import pytest

from app.backend.runtime import create_backend_module


def test_agent_tool_context_has_per_item_and_total_limits():
    backend = create_backend_module("test_agent_short_term_memory_tools")
    backend._CONTEXT_TOOL_RESULT_MAX_CHARS = 120
    backend._CONTEXT_TOOL_TOTAL_MAX_CHARS = 220
    context = backend._agent_tool_context([
        {"tool": "list_videos", "args": {}, "result": {"items": [{"id": str(i), "title": "x" * 100} for i in range(10)]}},
        {"tool": "list_tasks", "args": {}, "result": {"items": [{"id": str(i), "title": "y" * 100} for i in range(10)]}},
    ])
    assert context["truncated"] is True
    assert context["chars"] <= 220
    assert all(item.get("truncated") for item in context["items"])
    assert all(item["visibleChars"] <= 120 for item in context["items"])
    assert all(len(json.dumps(item, ensure_ascii=False)) <= 120 for item in context["items"])


def test_recent_turns_preserve_original_message_text():
    backend = create_backend_module("test_agent_short_term_memory_turns")
    text = "原始消息" + ("x" * 3000)
    turns = backend._agent_recent_turns([
        {"id": 1, "role": "user", "content": "old"},
        {"id": 2, "role": "assistant", "content": "old answer"},
        *[
            {"id": 3 + index, "role": role, "content": text if index == 0 else role}
            for index, role in enumerate(["user", "assistant"] * 4)
        ],
    ])
    assert len(turns) == 4
    assert turns[0]["messages"][0]["content"] == text
    assert turns[-1]["messages"][-1]["content"] == "assistant"


def test_compaction_moves_cold_turns_to_summary_before_prompting():
    backend = create_backend_module("test_agent_short_term_memory_trigger")
    cold_messages = [{"id": index, "role": "user", "content": "历史"} for index in range(1, 5)]
    assert backend._agent_compaction_trigger(False, cold_messages, 1, 934_464) == "hot_window"
    assert backend._agent_compaction_trigger(True, cold_messages, 1, 1000) == "manual"


def test_context_snapshot_contract_exposes_budget_fields():
    backend = create_backend_module("test_agent_short_term_memory_contract")
    assert backend._CONTEXT_RECENT_TURNS == 4
    assert backend._CONTEXT_POLICY_VERSION == "agent-context-v2"
    assert backend._CONTEXT_MODEL_WINDOW_TOKENS == 1_000_000
    assert backend._CONTEXT_INPUT_MAX_TOKENS == 934_464
    assert backend._CONTEXT_OUTPUT_MAX_TOKENS == 65_536
    assert backend._CONTEXT_COMPACTION_TRIGGER_TOKENS == 850_000
    assert backend._CONTEXT_COMPACTION_RECOVERY_TOKENS == 650_000
    assert backend._CONTEXT_TOOL_RESULT_MAX_CHARS == 16_000
    assert backend.AGENT_CONTEXT_RECENT_TURNS == 4
    assert backend.AGENT_OUTPUT_MAX_TOKENS == 65_536
    assert backend.AGENT_CONTEXT_TOOL_TOTAL_MAX_CHARS == 64_000


def test_summary_only_shrinks_above_recovery_budget():
    backend = create_backend_module("test_agent_short_term_memory_recovery")
    summary = backend._normalize_session_summary({
        "goal": "保留目标", "constraints": ["保留约束"], "pendingActions": ["保留待办"],
        "decisions": ["已完成决定"], "toolFacts": ["x" * 1_000],
    })
    assert backend._shrink_summary_to_budget(summary, 0, 650_000) == summary
    shrunk = backend._shrink_summary_to_budget(summary, 0, 150)
    assert shrunk["goal"] == "保留目标"
    assert shrunk["constraints"] == ["保留约束"]
    assert shrunk["toolFacts"] == []


def test_short_term_memory_migration_declares_append_only_events():
    migration = Path("app/db/migrations/postgresql/V033__agent_short_term_memory.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS agent_turn_events" in migration
    assert "summary_version" in migration
    assert "idx_agent_turn_events_session_turn" in migration


def test_model_memory_keeps_recent_turns_without_raw_context():
    backend = create_backend_module("test_agent_short_term_memory_projection")
    messages = []
    for turn in range(5):
        messages.extend([
            {"id": turn * 2 + 1, "role": "user", "content": f"user-{turn}", "context": {"page": "hidden-page-context"}},
            {
                "id": turn * 2 + 2,
                "role": "assistant",
                "content": f"assistant-{turn}",
                "context": {
                    "cards": [{"private": "never-send"}],
                    "toolResults": [{"tool": "lookup", "args": {"id": turn}, "result": "x" * 40_000}],
                },
            },
        ])

    memory = backend._agent_model_memory({"goal": "目标"}, backend._agent_recent_turns(messages))
    serialized = backend._agent_json_dumps(memory)

    assert len(memory["recentTurns"]) == 4
    assert "user-0" not in serialized
    assert "hidden-page-context" not in serialized
    assert "never-send" not in serialized
    tool_result = memory["recentTurns"][0]["messages"][1]["toolResults"][0]
    assert tool_result["args"] == {"id": 1}
    assert tool_result["truncated"] is True


def test_model_memory_keeps_large_tool_args_and_only_replaces_result():
    backend = create_backend_module("test_agent_short_term_memory_large_args")
    args = {"ids": ["keep"] * 20_000}
    memory = backend._agent_model_memory({}, [{"messages": [{
        "role": "assistant",
        "content": "查询完成",
        "context": {"toolResults": [{"tool": "lookup", "args": args, "result": "x" * 40_000}]},
    }]}])

    tool_result = memory["recentTurns"][0]["messages"][0]["toolResults"][0]
    assert tool_result["args"] == args
    assert tool_result["result"] != "x" * 40_000


def test_prompt_compacts_tool_results_before_rejecting_context():
    backend = create_backend_module("test_agent_short_term_memory_budget")
    backend._CONTEXT_INPUT_MAX_TOKENS = 12_000
    raw = "tool-output-" * 20_000
    model_memory = {
        "summary": {},
        "recentTurns": [{"messages": [{
            "role": "assistant", "content": "已查询",
            "toolResults": [{"tool": "lookup", "args": {"id": "keep"}, "result": raw}],
        }]}],
    }
    compact_memory = {
        "summary": {},
        "recentTurns": [{"messages": [{
            "role": "assistant", "content": "已查询",
            "toolResults": [{
                "tool": "lookup", "args": {"id": "keep"}, "truncated": True,
                "result": {"summary": "工具结果已为上下文预算压缩，请使用明细工具继续查询。"},
            }],
        }]}],
    }
    session_memory = {"modelMemory": model_memory, "compactModelMemory": compact_memory, "budget": {}}

    messages = backend._build_react_messages("继续处理", {"_sessionMemory": session_memory}, [])
    serialized = backend._agent_json_dumps(messages)

    assert raw not in serialized
    assert "keep" in serialized
    assert session_memory["budget"]["toolResultsCompacted"] is True


def test_prompt_rejects_non_tool_recent_message_over_budget():
    backend = create_backend_module("test_agent_short_term_memory_content_budget")
    backend._CONTEXT_INPUT_MAX_TOKENS = 12_000
    session_memory = {
        "modelMemory": {"summary": {}, "recentTurns": [{"messages": [{"role": "user", "content": "x" * 100_000}]}]},
        "compactModelMemory": {"summary": {}, "recentTurns": [{"messages": [{"role": "user", "content": "x" * 100_000}]}]},
        "budget": {},
    }

    with pytest.raises(backend.AgentContextBudgetError):
        backend._build_react_messages("继续处理", {"_sessionMemory": session_memory}, [])


def test_turn_event_audit_keeps_metadata_without_message_or_tool_body():
    backend = create_backend_module("test_agent_turn_event_metadata_backend")
    user_payload = backend._agent_turn_event_metadata(
        "user_message",
        {"messageId": 7, "content": "secret user content", "context": {"videoPath": "secret.mp4"}},
    )
    tool_payload = backend._agent_turn_event_metadata(
        "tool_call", {"args": {"cookie": "secret", "videoId": "video-1"}},
    )

    assert user_payload == {"messageId": 7, "contentChars": 19, "contextKeys": ["videoPath"]}
    assert tool_payload == {"argKeys": ["cookie", "videoId"]}
    assert "secret" not in str(user_payload)
    assert "secret" not in str(tool_payload)
