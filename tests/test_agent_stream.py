import json
import unittest
from contextlib import contextmanager

import app.core.agent_orchestrator as agent_orchestrator


def _events(chunks):
    result = []
    for chunk in chunks:
        lines = [line for line in chunk.splitlines() if line]
        result.append((lines[0].split(": ", 1)[1], json.loads(lines[1].split(": ", 1)[1])))
    return result


class AgentStreamTests(unittest.TestCase):
    def setUp(self):
        self.originals = {name: getattr(agent_orchestrator, name, None) for name in (
            "AGENT_ENABLED", "ensure_agent_session", "save_agent_message", "save_agent_run",
            "sanitize_agent_output", "_node_policy_check", "_node_react_loop", "_agent_llm_available",
            "_call_agent_contract", "AGENT_CHAT_MODEL", "prepare_agent_session_context",
            "finalize_agent_turn", "agent_session_guard", "renew_agent_session_lease",
            "call_json_contract",
        )}
        agent_orchestrator.AGENT_ENABLED = True
        agent_orchestrator.AGENT_CHAT_MODEL = "test-model"
        agent_orchestrator.ensure_agent_session = lambda session_id, context: session_id or "session-test"
        agent_orchestrator.save_agent_message = lambda *args, **kwargs: 1
        agent_orchestrator.save_agent_run = lambda *args, **kwargs: "run-test"
        agent_orchestrator.sanitize_agent_output = lambda value: str(value or "")
        agent_orchestrator._agent_llm_available = lambda: False
        agent_orchestrator.finalize_agent_turn = None
        agent_orchestrator.agent_session_guard = None
        agent_orchestrator.renew_agent_session_lease = None
        agent_orchestrator._node_policy_check = lambda state: {**state, "safety_decision": {"allowed": True}}
        agent_orchestrator._node_react_loop = lambda state: {
            **state,
            "answer": "**待处理**视频已经找到。",
            "iterations": 1,
            "tool_results": [{
                "tool": "list_videos_by_status",
                "result": {"status": "initial", "label": "待处理", "total": 1, "items": [{"title": "示例视频", "channel": "示例频道"}]},
            }],
        }

    def tearDown(self):
        for name, value in self.originals.items():
            if value is None:
                if hasattr(agent_orchestrator, name):
                    delattr(agent_orchestrator, name)
            else:
                setattr(agent_orchestrator, name, value)

    def test_stream_emits_visible_stages_deltas_and_final_result(self):
        events = _events(list(agent_orchestrator.run_agent_chat_stream("待处理的视频有哪些？")))
        self.assertEqual([name for name, _ in events[:3]], ["status", "status", "status"])
        self.assertEqual(events[-1][0], "result")
        delta_text = "".join(data["content"] for name, data in events if name == "delta")
        result = events[-1][1]
        self.assertEqual(delta_text, result["answer"])
        self.assertNotIn("**", result["answer"])
        self.assertEqual(result["actions"], [{
            "type": "navigate",
            "label": "查看全部待处理视频",
            "path": "/youtube-research",
            "query": {"status": "initial"},
        }])

    def test_stream_uses_validated_reply_before_emitting_deltas(self):
        agent_orchestrator._agent_llm_available = lambda: True
        calls = []

        def call_contract(messages, contract_id, validator, max_tokens=None, session_id=""):
            calls.append(contract_id)
            return {"answer": "这是经过契约校验后的中文回答。"}, {}, {"attemptCount": 1}

        agent_orchestrator._call_agent_contract = call_contract
        events = _events(list(agent_orchestrator.run_agent_chat_stream("待处理的视频有哪些？")))
        result = events[-1][1]

        self.assertEqual(calls, ["agent_reply"])
        self.assertEqual(result["answer"], "这是经过契约校验后的中文回答。")

    def test_stream_loads_short_term_session_context(self):
        observed = {}
        agent_orchestrator.prepare_agent_session_context = lambda session_id: {
            "summary": {"goal": "继续处理昨天的视频任务"},
            "recentMessages": [{"role": "user", "content": "先检查第一个视频"}],
            "messageCount": 8,
            "summaryThroughId": 6,
            "compacted": True,
        }

        def react_loop(state):
            observed.update(state["context"]["_sessionMemory"])
            return {
                **state,
                "answer": "我会结合刚才的会话继续查询。",
                "iterations": 0,
                "tool_results": [],
            }

        agent_orchestrator._node_react_loop = react_loop
        events = _events(list(agent_orchestrator.run_agent_chat_stream("继续")))
        result = events[-1][1]

        self.assertEqual(observed["summary"]["goal"], "继续处理昨天的视频任务")
        self.assertEqual(observed["recentMessages"][0]["content"], "先检查第一个视频")
        self.assertTrue(result["sessionContext"]["compacted"])

    def test_stream_persists_answer_before_first_delta(self):
        persisted = []

        def save_message(session_id, role, content, context):
            persisted.append(("message", role, content))
            return len(persisted)

        def save_run(*args, **kwargs):
            persisted.append(("run", kwargs.get("session_id"), kwargs.get("output", {}).get("answer")))
            return "run-persisted"

        agent_orchestrator.save_agent_message = save_message
        agent_orchestrator.save_agent_run = save_run
        events = []
        for chunk in agent_orchestrator.run_agent_chat_stream("请查询"):
            event = _events([chunk])[0]
            events.append(event)
            if event[0] == "delta":
                self.assertEqual([item[:2] for item in persisted], [
                    ("message", "user"),
                    ("message", "assistant"),
                    ("run", "session-test"),
                ])

        self.assertIn("delta", [name for name, _ in events])

    def test_stream_reports_memory_failure(self):
        def fail_memory(_session_id):
            raise RuntimeError("memory database unavailable")

        agent_orchestrator.prepare_agent_session_context = fail_memory
        events = _events(list(agent_orchestrator.run_agent_chat_stream("继续")))
        phases = [data.get("phase") for name, data in events if name == "status"]

        self.assertIn("memory_warning", phases)
        self.assertFalse(events[-1][1]["sessionContext"]["available"])

    def test_stream_emits_initial_status_before_loading_memory(self):
        memory_loaded = []

        def load_memory(_session_id):
            memory_loaded.append(True)
            return {"summary": {}, "recentMessages": [], "messageCount": 0, "compacted": False}

        agent_orchestrator.prepare_agent_session_context = load_memory
        stream = agent_orchestrator.run_agent_chat_stream("继续")
        first_event = _events([next(stream)])[0]

        self.assertEqual(first_event, ("status", {"phase": "understanding", "message": "正在理解你的问题"}))
        self.assertEqual(memory_loaded, [])
        list(stream)
        self.assertEqual(memory_loaded, [True])

    def test_stream_does_not_emit_answer_when_atomic_persistence_fails(self):
        def fail_finalize(*args, **kwargs):
            raise RuntimeError("database unavailable")

        agent_orchestrator.finalize_agent_turn = fail_finalize
        events = _events(list(agent_orchestrator.run_agent_chat_stream("请查询")))

        self.assertEqual(events[-1], ("error", {"message": "Agent 回答保存失败，请重试。"}))
        self.assertNotIn("delta", [name for name, _ in events])
        self.assertNotIn("result", [name for name, _ in events])

    def test_stream_reports_session_lease_timeout(self):
        @contextmanager
        def blocked_guard(_session_id):
            raise TimeoutError("Agent 会话正被另一个请求占用，请稍后重试。")
            yield

        agent_orchestrator.agent_session_guard = blocked_guard
        events = _events(list(agent_orchestrator.run_agent_chat_stream("继续")))

        self.assertEqual(events, [("error", {"message": "Agent 会话正被另一个请求占用，请稍后重试。"})])

    def test_stream_reports_unexpected_failure_as_sse_error(self):
        agent_orchestrator._node_policy_check = lambda _state: (_ for _ in ()).throw(RuntimeError("database unavailable"))

        events = _events(list(agent_orchestrator.run_agent_chat_stream("继续")))

        self.assertEqual(events[-1], ("error", {"message": "Agent 对话发生异常，请重试。"}))

    def test_stream_renews_session_lease_before_reply_generation(self):
        renewed_sessions = []
        agent_orchestrator._agent_llm_available = lambda: True
        agent_orchestrator.renew_agent_session_lease = lambda session_id: renewed_sessions.append(session_id) or True
        agent_orchestrator.call_json_contract = lambda **_kwargs: ({"answer": "整理后的回答。"}, {}, {})

        list(agent_orchestrator.run_agent_chat_stream("继续"))

        self.assertEqual(renewed_sessions, ["session-test"])


if __name__ == "__main__":
    unittest.main()
