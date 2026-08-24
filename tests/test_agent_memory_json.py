import datetime
import io
import json

import pytest

from app.backend.runtime import create_backend_module
from app.core import llm_harness


def test_agent_context_serializes_nested_datetime_values():
    backend = create_backend_module("test_agent_memory_json_backend")

    payload = backend._agent_json_dumps({"card": {"updatedAt": datetime.datetime(2026, 8, 17, 9, 30)}})

    assert backend._agent_json_loads(payload) == {"card": {"updatedAt": "2026-08-17T09:30:00"}}


def test_agent_context_rejects_unknown_non_json_value():
    backend = create_backend_module("test_agent_memory_json_unknown_backend")

    with pytest.raises(TypeError, match="not JSON serializable"):
        backend._agent_json_dumps({"value": object()})


def test_agent_stream_serializes_datetime_tool_results():
    backend = create_backend_module("test_agent_memory_json_stream_backend")
    value = datetime.datetime(2026, 8, 17, 23, 11, 25)

    assert "2026-08-17T23:11:25" in backend._json_for_prompt({"updatedAt": value})

    event = backend._agent_sse_event("result", {"updatedAt": value})
    assert json.loads(event.split("data: ", 1)[1]) == {"updatedAt": "2026-08-17T23:11:25"}


def test_notification_time_serializes_naive_database_time_without_utc_shift():
    backend = create_backend_module("test_notification_time_serialization_backend")
    local_time = datetime.datetime(2026, 8, 18, 16, 32)

    item = backend._notification_item({"id": 1, "updated_at": local_time})

    assert item["updatedAt"] == "2026-08-18T16:32:00"
    assert backend.app.json.loads(backend.app.json.dumps(item))["updatedAt"] == "2026-08-18T16:32:00"


def test_agent_text_stream_yields_provider_sse_chunks(monkeypatch):
    captured = {}

    class Response(io.BytesIO):
        def close(self):
            super().close()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response(
            b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0\xe5\xa5\xbd"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"\xe4\xb8\x96\xe7\x95\x8c"}}]}\n\n'
            b'data: [DONE]\n\n'
        )

    monkeypatch.setattr(llm_harness, "llm_provider_profile", lambda *_args, **_kwargs: {"provider": "openai_compatible"})
    monkeypatch.setattr(llm_harness.urllib.request, "urlopen", fake_urlopen)

    chunks = list(llm_harness.stream_text_completion(
        messages=[{"role": "user", "content": "测试"}],
        model="agent-model",
        api_key="test-key",
        base_url="https://example.test/v1",
        timeout=12,
        temperature=0.2,
        max_tokens=100,
    ))

    assert chunks == ["你好", "世界"]
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert captured["timeout"] == 12


def test_agent_text_stream_reports_provider_usage(monkeypatch):
    class Response(io.BytesIO):
        def close(self):
            super().close()

    def fake_urlopen(_request, timeout):
        return Response(b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(llm_harness, "llm_provider_profile", lambda *_args, **_kwargs: {"provider": "openai_compatible"})
    monkeypatch.setattr(llm_harness.urllib.request, "urlopen", fake_urlopen)
    usage = []
    list(llm_harness.stream_text_completion(
        messages=[], model="agent-model", api_key="test-key", base_url="https://example.test/v1",
        timeout=12, temperature=0.2, max_tokens=100, usage_callback=usage.append,
    ))
    assert usage == [{"tokens": 15, "totalTokens": 15, "promptTokens": 12, "completionTokens": 3}]


def test_agent_reply_uses_dedicated_provider_stream(monkeypatch):
    backend = create_backend_module("test_agent_reply_provider_stream_backend")
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return iter(["第一段", "第二段"])

    monkeypatch.setattr(backend, "stream_text_completion", fake_stream)

    assert list(backend._stream_agent_reply("请总结", [], "session-1")) == ["第一段", "第二段"]
    assert captured["profile_channel"] == "agent"
    assert captured["model"] == backend.AGENT_LLM_MODEL
    assert callable(captured["usage_callback"])


def test_agent_reply_collects_stream_usage(monkeypatch):
    backend = create_backend_module("test_agent_reply_stream_usage_backend")

    def fake_stream(**kwargs):
        kwargs["usage_callback"]({"promptTokens": 8, "completionTokens": 2, "tokens": 10})
        return iter(["第一段"])

    monkeypatch.setattr(backend, "stream_text_completion", fake_stream)
    usage_token = backend._AGENT_REQUEST_USAGE.set([])
    try:
        assert list(backend._stream_agent_reply("请总结", [], "session-1")) == ["第一段"]
        assert backend._AGENT_REQUEST_USAGE.get() == [{"promptTokens": 8, "completionTokens": 2, "tokens": 10}]
    finally:
        backend._AGENT_REQUEST_USAGE.reset(usage_token)


def test_agent_usage_summary_keeps_all_token_dimensions():
    backend = create_backend_module("test_agent_usage_summary_backend")
    usages = [{"tokens": 10, "totalTokens": 10, "promptTokens": 8, "completionTokens": 2}]
    assert backend._agent_usage_summary(usages) == {
        "tokens": 10, "totalTokens": 10, "promptTokens": 8, "completionTokens": 2,
    }
