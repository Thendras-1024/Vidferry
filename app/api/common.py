"""Common web, health, and static resource API routes."""

from app.config import get_llm_config_status


@app.route("/runtime/config-status", methods=["GET"])
def runtime_config_status():
    return jsonify({
        "code": 200,
        "data": {
            "llm": get_llm_config_status(),
        },
    })
