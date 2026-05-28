class NoSpeechDetectedError(RuntimeError):
    pass


@app.before_request
def ensure_database_tables():
    init_youtube_workflow_table()

def _parse_upload_date(value):
    if not value:
        return ""
    text = str(value)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _format_iso_date(value):
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else value


def _format_count(value):
    if value is None or value == "":
        return ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,}"


def _format_subscribers_w(value):
    if value is None or value == "":
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith("w"):
        return text

    normalized = text.lower()
    normalized = normalized.replace(",", "").replace("subscribers", "").replace("subscriber", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return text

    number = float(match.group(1))
    number_unit_pattern = rf"{re.escape(match.group(1))}\s*([kmw])\b"
    unit_match = re.search(number_unit_pattern, normalized)
    unit = unit_match.group(1) if unit_match else ""

    if "万" in normalized or unit == "w":
        count = number * 10000
    elif "million" in normalized or unit == "m":
        count = number * 1000000
    elif "thousand" in normalized or unit == "k":
        count = number * 1000
    else:
        count = number

    wan = count / 10000
    precision = 2 if 0 < wan < 0.1 else 1
    formatted = f"{wan:.{precision}f}".rstrip("0").rstrip(".")
    return f"{formatted}w"


def _db_path():
    return Path(BASE_DIR / "db" / "database.db")


def _json_response(code=200, msg="success", data=None, status=200):
    return jsonify({"code": code, "msg": msg, "data": data}), status


def _clean_unique_list(values):
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


_publish_account_locks = {}
_publish_account_locks_guard = threading.Lock()


def _safe_text(value, default=""):
    return str(value if value is not None else default).strip()


def _normalize_publish_tags(tags):
    if isinstance(tags, (list, tuple, set)):
        raw_values = tags
    else:
        raw_values = re.split(r"[，,\s]+", str(tags or ""))
    cleaned = []
    seen = set()
    for value in raw_values:
        text = str(value or "").strip().lstrip("#")
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _get_publish_account_lock(platform_type, account_file):
    key = f"{int(platform_type or 0)}:{_safe_text(account_file)}"
    with _publish_account_locks_guard:
        lock = _publish_account_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _publish_account_locks[key] = lock
        return lock


class WorkflowConflictError(ValueError):
    def __init__(self, message, error_code, error_type="WORKFLOW_CONFLICT", data=None):
        super().__init__(message)
        self.error_code = error_code
        self.error_type = error_type
        self.data = data or {}


def _error_response(status, message, error_code, error_type="", data=None):
    payload = {
        "errorCode": error_code,
        "errorType": error_type or error_code,
        **(data or {}),
    }
    return _json_response(status, message, payload, status)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _parse_json_object(raw_value):
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {"raw": str(raw_value)}


def _clean_topic_list(value):
    if not isinstance(value, list):
        return []
    topics = []
    for item in value:
        topic = str(item or "").strip().lstrip("#")
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def _build_default_publish_draft(analysis_result):
    result = analysis_result if isinstance(analysis_result, dict) else {}
    title_options = [
        str(title or "").strip()
        for title in (result.get("title_options") if isinstance(result.get("title_options"), list) else [])
        if str(title or "").strip()
    ]
    selected_title = random.choice(title_options) if title_options else ""
    return {
        "title": selected_title,
        "description": str(result.get("publish_copy") or "").strip(),
        "tags": _clean_topic_list(result.get("tags")),
        "source": "llm_default",
        "updatedAt": _now_iso(),
    }


def _parse_publish_draft(raw_value, analysis_result=None):
    draft = _parse_json_object(raw_value)
    if not draft:
        return {}
    return {
        "title": str(draft.get("title") or "").strip(),
        "description": str(draft.get("description") or "").strip(),
        "tags": _clean_topic_list(draft.get("tags")),
        "source": str(draft.get("source") or "").strip(),
        "updatedAt": str(draft.get("updatedAt") or "").strip(),
    }


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
    return ",".join("?" for _ in values)


