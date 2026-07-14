import gc
import tempfile
import threading
import time
import unittest
from pathlib import Path

import sau_backend as backend


class AgentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.originals = {
            "_db_path": backend._db_path,
            "LLM_API_KEY": backend.LLM_API_KEY,
            "LLM_BASE_URL": backend.LLM_BASE_URL,
        }
        database_path = Path(self.temp_dir.name) / "agent-memory.db"
        backend._db_path = lambda: database_path
        backend.LLM_API_KEY = ""
        backend.LLM_BASE_URL = ""
        backend.init_database_tables()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(backend, name, value)
        gc.collect()
        self.temp_dir.cleanup()

    def test_history_can_be_listed_reopened_and_deleted(self):
        session_id = backend.ensure_agent_session(context={"pageTitle": "视频采集处理"})
        backend.save_agent_message(session_id, "user", "帮我查看昨天的视频任务", {"pageTitle": "视频采集处理"})
        backend.save_agent_message(session_id, "assistant", "昨天有两个视频任务。", {})

        history = backend.list_agent_sessions(page=1, page_size=20)
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["id"], session_id)
        self.assertEqual(history["items"][0]["messageCount"], 2)
        self.assertIn("帮我查看昨天", history["items"][0]["title"])

        messages = backend.list_agent_messages(session_id, 100)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "帮我查看昨天的视频任务")

        client = backend.app.test_client()
        response = client.get("/agents/sessions?page=1&pageSize=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["items"][0]["id"], session_id)

        response = client.get(f"/agents/sessions/{session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["messageCount"], 2)

        response = client.get(f"/agents/sessions/{session_id}/messages?limit=100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["data"]["items"]), 2)

        response = client.delete(f"/agents/sessions/{session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(backend.get_agent_session(session_id))
        self.assertEqual(backend.list_agent_messages(session_id, 100), [])
        self.assertEqual(backend.list_agent_sessions()["total"], 0)
        self.assertEqual(client.get(f"/agents/sessions/{session_id}").status_code, 404)
        self.assertEqual(client.get("/agents/sessions").get_json()["data"]["total"], 0)
        with self.assertRaises(ValueError):
            backend.save_agent_message(session_id, "assistant", "删除后不应写入", {})
        with self.assertRaises(ValueError):
            backend.save_agent_run("chat", session_id=session_id)
        with backend._db_connect(row_factory=True) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS total FROM agent_messages WHERE session_id = ?", (session_id,)).fetchone()["total"],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS total FROM agent_runs WHERE session_id = ?", (session_id,)).fetchone()["total"],
                0,
            )
        self.assertNotEqual(backend.ensure_agent_session(session_id), session_id)

    def test_long_session_is_compacted_but_raw_messages_remain_reviewable(self):
        session_id = backend.ensure_agent_session(context={"pageTitle": "发布中心"})
        for index in range(7):
            backend.save_agent_message(session_id, "user", f"第 {index + 1} 轮目标：检查视频 {index + 1}", {})
            backend.save_agent_message(session_id, "assistant", f"第 {index + 1} 轮已完成检查。", {})

        context = backend.prepare_agent_session_context(session_id)

        self.assertTrue(context["compacted"])
        self.assertEqual(context["messageCount"], 14)
        self.assertEqual(len(context["recentMessages"]), backend.AGENT_CONTEXT_RECENT_MESSAGES)
        self.assertIn("第 3 轮目标", context["summary"]["goal"])
        self.assertGreater(context["summaryThroughId"], 0)
        self.assertTrue(all(item["id"] > context["summaryThroughId"] for item in context["recentMessages"]))
        self.assertEqual(len(backend.list_agent_messages(session_id, 100)), 14)

        prompt_messages = backend._build_react_messages(
            "继续处理刚才的任务",
            {"pageTitle": "发布中心", "_sessionMemory": context},
            [],
        )
        prompt_text = prompt_messages[1]["content"]
        self.assertIn("会话短期记忆", prompt_text)
        self.assertIn("第 7 轮目标", prompt_text)
        self.assertIn("最近消息", prompt_text)

    def test_history_messages_support_before_id_cursor_pages(self):
        session_id = backend.ensure_agent_session(context={})
        for index in range(30):
            backend.save_agent_message(session_id, "user", f"历史消息 {index + 1}", {})

        client = backend.app.test_client()
        page_contents = []
        before_id = None
        while True:
            query = "?limit=12" + (f"&beforeId={before_id}" if before_id else "")
            response = client.get(f"/agents/sessions/{session_id}/messages{query}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()["data"]
            contents = [item["content"] for item in data["items"]]
            page_contents = contents + page_contents
            if not data["hasMore"]:
                self.assertIsNone(data["nextBeforeId"])
                break
            self.assertEqual(len(contents), 12)
            before_id = data["nextBeforeId"]

        self.assertEqual(len(page_contents), 30)
        self.assertEqual(page_contents, [f"历史消息 {index + 1}" for index in range(30)])

    def test_summary_lists_are_stably_deduplicated(self):
        summary = backend._normalize_session_summary({
            "decisions": ["视频已下载", " 视频  已下载 ", "字幕已生成"],
            "pendingActions": ["发布到 B 站", "发布到 b 站"],
        })

        self.assertEqual(summary["decisions"], ["视频已下载", "字幕已生成"])
        self.assertEqual(summary["pendingActions"], ["发布到 B 站"])

    def test_agent_hot_path_does_not_rerun_schema_migrations(self):
        original = backend.init_database_tables
        backend.init_database_tables = lambda: self.fail("Agent 热路径不应执行建表或迁移")
        try:
            session_id = backend.ensure_agent_session(context={"pageTitle": "Agent"})
            backend.save_agent_message(session_id, "user", "检查热路径", {})
            backend.save_agent_run("chat", session_id=session_id)
            self.assertEqual(len(backend.list_agent_messages(session_id, 10)), 1)
        finally:
            backend.init_database_tables = original

    def test_compaction_compare_and_swap_preserves_newer_summary(self):
        session_id = backend.ensure_agent_session(context={})
        for index in range(7):
            backend.save_agent_message(session_id, "user", f"问题 {index}", {})
            backend.save_agent_message(session_id, "assistant", f"回答 {index}", {})

        original = backend._llm_session_summary
        summary_started = threading.Event()
        release_summary = threading.Event()
        result = {}

        def slow_summary(previous, messages):
            summary_started.set()
            self.assertTrue(release_summary.wait(3))
            return backend._summary_from_messages(previous, messages)

        def run_compaction():
            result.update(backend.compact_agent_session(session_id, force=True) or {})

        backend._llm_session_summary = slow_summary
        worker = threading.Thread(target=run_compaction)
        try:
            worker.start()
            self.assertTrue(summary_started.wait(3))
            with backend._db_connect(row_factory=True) as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO agent_messages (session_id, role, content, context, created_at) VALUES (?, 'user', ?, '{}', ?)",
                    (session_id, "来自另一进程的新消息", backend._agent_now_iso()),
                )
                newer_message_id = cursor.lastrowid
                cursor.execute(
                    """
                    UPDATE agent_sessions
                    SET summary = ?, summary_through_id = ?, message_count = message_count + 1
                    WHERE id = ?
                    """,
                    (backend._agent_json_dumps({"goal": "较新的摘要", "lastMessageId": newer_message_id}), newer_message_id, session_id),
                )
                conn.commit()
            release_summary.set()
            worker.join(3)
        finally:
            release_summary.set()
            worker.join(3)
            backend._llm_session_summary = original

        self.assertFalse(worker.is_alive())
        self.assertTrue(result["conflict"])
        session = backend.get_agent_session(session_id)
        self.assertEqual(session["summaryThroughId"], newer_message_id)
        self.assertEqual(session["summary"]["goal"], "较新的摘要")

    def test_assistant_message_and_run_are_committed_atomically(self):
        session_id = backend.ensure_agent_session(context={})
        backend.save_agent_message(session_id, "user", "原始问题", {})
        original = backend._insert_agent_run

        def fail_run(*args, **kwargs):
            raise RuntimeError("模拟运行记录写入失败")

        backend._insert_agent_run = fail_run
        try:
            with self.assertRaises(RuntimeError):
                backend.finalize_agent_turn(session_id, "不应留下的回答", {}, output={"answer": "不应留下的回答"})
        finally:
            backend._insert_agent_run = original

        messages = backend.list_agent_messages(session_id, 10)
        self.assertEqual([(item["role"], item["content"]) for item in messages], [("user", "原始问题")])
        with backend._db_connect(row_factory=True) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS total FROM agent_runs WHERE session_id = ?", (session_id,)).fetchone()["total"],
                0,
            )

    def test_same_session_chat_requests_are_serialized(self):
        session_id = backend.ensure_agent_session(context={})
        names = ("_AGENT_GRAPH", "_build_agent_graph", "_node_policy_check", "_node_react_loop")
        originals = {name: getattr(backend, name) for name in names}
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        call_count = 0
        call_count_lock = threading.Lock()
        errors = []

        def react_loop(state):
            nonlocal call_count
            with call_count_lock:
                call_count += 1
                current = call_count
            if current == 1:
                first_started.set()
                if not release_first.wait(3):
                    raise TimeoutError("首个请求未被释放")
            else:
                second_started.set()
            return {**state, "answer": f"回答 {current}", "tool_results": [], "iterations": 0}

        def invoke(message):
            try:
                backend.run_agent_chat(message, session_id=session_id)
            except Exception as exc:
                errors.append(exc)

        backend._AGENT_GRAPH = None
        backend._build_agent_graph = lambda: None
        backend._node_policy_check = lambda state: {**state, "safety_decision": {"allowed": True}}
        backend._node_react_loop = react_loop
        first = threading.Thread(target=invoke, args=("第一轮",))
        second = threading.Thread(target=invoke, args=("第二轮",))
        try:
            first.start()
            self.assertTrue(first_started.wait(3))
            second.start()
            time.sleep(0.15)
            self.assertFalse(second_started.is_set())
            release_first.set()
            first.join(3)
            second.join(3)
        finally:
            release_first.set()
            first.join(3)
            second.join(3)
            for name, value in originals.items():
                setattr(backend, name, value)

        self.assertEqual(errors, [])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        messages = backend.list_agent_messages(session_id, 20)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual([item["content"] for item in messages], ["第一轮", "回答 1", "第二轮", "回答 2"])

    def test_database_session_lease_blocks_another_owner(self):
        session_id = backend.ensure_agent_session(context={})
        original_wait = backend._AGENT_SESSION_LOCK_WAIT_SECONDS
        owner_id = backend._acquire_agent_session_lease(session_id)
        backend._AGENT_SESSION_LOCK_WAIT_SECONDS = 0
        try:
            with self.assertRaises(TimeoutError):
                backend._acquire_agent_session_lease(session_id)
        finally:
            backend._AGENT_SESSION_LOCK_WAIT_SECONDS = original_wait
            backend._release_agent_session_lease(session_id, owner_id)


if __name__ == "__main__":
    unittest.main()
