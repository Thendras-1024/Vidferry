import app.feishu_robot as feishu_robot
import app as app_module


def test_enabled_robot_without_owner_id_does_not_start_thread(monkeypatch):
    monkeypatch.setattr(feishu_robot, "env_settings", lambda: ("app", "secret", {"ou_1"}, 0))
    monkeypatch.setattr(feishu_robot, "_set_robot_status", lambda *args: None)
    monkeypatch.setattr(feishu_robot, "_embedded_robot_thread", None)

    assert feishu_robot.start_embedded_feishu_robot(True, lambda *_args: None) is False
    assert feishu_robot._embedded_robot_thread is None


def test_embedded_robot_accepts_explicit_owner_id(monkeypatch):
    calls = []

    class _Thread:
        def __init__(self, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

        def is_alive(self):
            return False

    monkeypatch.setattr(feishu_robot, "env_settings", lambda: ("app", "secret", {"ou_1"}, 0))
    monkeypatch.setattr(feishu_robot, "Thread", _Thread)
    monkeypatch.setattr(feishu_robot, "run_feishu_robot", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(feishu_robot, "_embedded_robot_thread", None)

    assert feishu_robot.start_embedded_feishu_robot(
        True,
        lambda *_args: None,
        session_manager=object(),
        owner_user_id=7,
    ) is True
    assert calls[-1][1]["owner_user_id"] == 7


def test_initialize_runtime_passes_feishu_owner_id(monkeypatch):
    calls = []

    class _Backend:
        BASE_DIR = "E:/Vidferry"
        run_agent_chat = staticmethod(lambda *_args, **_kwargs: None)
        sanitize_agent_output = staticmethod(str)

        def __getattr__(self, name):
            return lambda: None

    monkeypatch.setattr(app_module, "FEISHU_ROBOT_ENABLED", True)
    monkeypatch.setattr(app_module, "FEISHU_AGENT_OWNER_USER_ID", 1)
    monkeypatch.setattr(app_module, "_backend", lambda: _Backend())
    monkeypatch.setattr(
        app_module,
        "start_embedded_feishu_robot",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    app_module.initialize_runtime()

    assert calls[-1][0][0] is True
    assert calls[-1][1]["owner_user_id"] == 1
