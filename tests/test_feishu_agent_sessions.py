from contextlib import nullcontext

from app.feishu_robot import FeishuRobot


class _SessionManager:
    def __init__(self):
        self.active = "phone-session"
        self.sessions = [{"id": "phone-session", "title": "默认会话", "messageCount": 2}]

    def agent_actor(self, owner_user_id):
        assert owner_user_id == 7
        return nullcontext()

    def get_or_create_external_agent_session(self, source, source_key):
        assert source == "feishu"
        assert source_key
        return self.active

    def create_external_agent_session(self, source, source_key, title):
        assert source == "feishu"
        self.active = "new-phone-session"
        self.sessions.insert(0, {"id": self.active, "title": title or "手机端会话", "messageCount": 0})
        return self.active

    def list_external_agent_sessions(self, source, source_key):
        assert source == "feishu"
        return self.sessions

    def switch_external_agent_session(self, source, source_key, position):
        self.active = self.sessions[int(position) - 1]["id"]
        return self.sessions[int(position) - 1]

    def compact_agent_session(self, session_id, force):
        return {"sessionId": session_id, "force": force}


def test_phone_text_uses_agent_with_source_and_owner():
    replies = []
    calls = []

    def run_agent(message, **kwargs):
        calls.append((message, kwargs))
        return {"answer": "完成", "toolResults": []}

    robot = FeishuRobot(
        {"ou_test"},
        run_agent,
        lambda message_id, text: replies.append((message_id, text)),
        lambda message_id, card: replies.append((message_id, card)),
        session_manager=_SessionManager(),
        owner_user_id=7,
        submit=lambda task: task(),
    )

    robot._process("message-1", "ou_test", "查询视频", "request-1")

    assert calls[0][0] == "查询视频"
    assert calls[0][1]["context"]["source"] == "feishu"
    assert calls[0][1]["owner_user_id"] == 7


def test_phone_commands_do_not_call_agent():
    replies = []
    manager = _SessionManager()
    robot = FeishuRobot(
        {"ou_test"},
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Agent should not run for commands")),
        lambda message_id, text: replies.append(text),
        lambda *_args: None,
        session_manager=manager,
        owner_user_id=7,
        submit=lambda task: task(),
    )

    robot._process("message-1", "ou_test", "/new 新主题", "request-1")
    robot._process("message-2", "ou_test", "/sessions", "request-2")
    robot._process("message-3", "ou_test", "/use 1", "request-3")
    robot._process("message-4", "ou_test", "/compact", "request-4")

    assert any("新会话" in reply for reply in replies)
    assert any("手机端会话" in reply for reply in replies)
    assert any("已切换" in reply for reply in replies)
    assert any("已汇总" in reply for reply in replies)
