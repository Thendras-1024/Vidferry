"""HTTP 请求辅助函数。"""

from flask import jsonify


def _json_response(code=200, msg="success", data=None, status=200):
    return jsonify({"code": code, "msg": msg, "data": data}), status


def _error_response(status, message, error_code, error_type="", data=None):
    payload = {
        "errorCode": error_code,
        "errorType": error_type or error_code,
        **(data or {}),
    }
    return _json_response(status, message, payload, status)


def _parse_positive_int(value, default, minimum=1, maximum=500):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(minimum, min(number, maximum))


def _split_request_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")
    return [str(item or "").strip() for item in raw_values if str(item or "").strip()]


def _sql_placeholders(values):
    return ",".join("%s" for _ in values)
