import datetime
import json

import pytest

from app.backend.runtime import create_backend_module


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
