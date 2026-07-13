"""通用的 Web、健康检查与静态资源 API 路由。"""

from app.config import (
    AGENT_BLOCK_LEVEL,
    AGENT_CHAT_MAX_TOKENS,
    AGENT_CHAT_MODEL,
    AGENT_CHAT_TEMPERATURE,
    AGENT_ENABLED,
    AGENT_FRAME_MAX_COUNT,
    AGENT_FRAME_SCALE_WIDTH,
    AGENT_GUARD_MAX_TOKENS,
    AGENT_GUARD_TEMPERATURE,
    AGENT_MAX_TOOL_CALLS,
    AGENT_MAX_TOOL_ROWS,
    AGENT_REACT_MAX_STEPS,
    AGENT_REQUIRE_PREPUBLISH_CHECK,
    AGENT_REQUIRE_VISION_CHECK,
    AGENT_VISION_FAIL_CLOSED,
    AGENT_VISION_MODEL,
    get_llm_config_status,
)


def _agent_status_payload():
    return {
        "enabled": AGENT_ENABLED,
        "chatModel": AGENT_CHAT_MODEL,
        "visionModelConfigured": bool(AGENT_VISION_MODEL),
        "requirePrepublishCheck": AGENT_REQUIRE_PREPUBLISH_CHECK,
        "blockLevel": AGENT_BLOCK_LEVEL,
        "maxToolRows": AGENT_MAX_TOOL_ROWS,
        "maxToolCalls": AGENT_MAX_TOOL_CALLS,
        "reactMaxSteps": AGENT_REACT_MAX_STEPS,
        "chatTemperature": AGENT_CHAT_TEMPERATURE,
        "chatMaxTokens": AGENT_CHAT_MAX_TOKENS,
        "guardTemperature": AGENT_GUARD_TEMPERATURE,
        "guardMaxTokens": AGENT_GUARD_MAX_TOKENS,
        "requireVisionCheck": AGENT_REQUIRE_VISION_CHECK,
        "visionFailClosed": AGENT_VISION_FAIL_CLOSED,
        "frameMaxCount": AGENT_FRAME_MAX_COUNT,
        "frameScaleWidth": AGENT_FRAME_SCALE_WIDTH,
    }


@app.route("/runtime/config-status", methods=["GET"])
def runtime_config_status():
    return jsonify({
        "code": 200,
        "data": {
            "llm": get_llm_config_status(),
            "agent": _agent_status_payload(),
        },
    })
