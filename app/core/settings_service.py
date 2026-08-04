"""工作流默认设置的读写与归一化(存储在 app_settings 键值表)。"""


from app.core.cover_service import DEFAULT_COVER_SIGNATURE, normalize_cover_signature


WORKFLOW_SETTINGS_KEY = "youtube_workflow_settings"


def _normalize_highlight_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 3
    return count if count in {1, 2, 3} else 3


def _default_workflow_settings():
    return {
        "processVersion": PROCESS_VERSION_TRANSLATION,
        "subtitleLanguage": DEFAULT_SUBTITLE_LANGUAGE,
        "burnProfile": DEFAULT_BURN_PROFILE,
        "subtitleSize": DEFAULT_SUBTITLE_SIZE,
        "translatorLabel": DEFAULT_TRANSLATOR_LABEL,
        "searchQuery": YOUTUBE_DEFAULT_QUERY,
        "watermarkEnabled": False,
        "watermarkText": "",
        "coverSignature": DEFAULT_COVER_SIGNATURE,
        "highlightCount": 3,
        "translationEnabled": True,
        "highlightIntroEnabled": True,
        "coverIntroEnabled": True,
        "commentBurnEnabled": False,
        "contentSafetyReviewEnabled": False,
    }


def _comment_burn_available():
    return not str(SUBTITLE_COMMAND_TEMPLATE or "").strip()


def _normalize_workflow_settings(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    settings = _default_workflow_settings()

    process_version = str(payload.get("processVersion") or "").strip()
    if process_version in PROCESS_VERSIONS:
        settings["processVersion"] = process_version

    subtitle_language = str(payload.get("subtitleLanguage") or "").strip()
    if subtitle_language in SUBTITLE_LANGUAGES:
        settings["subtitleLanguage"] = subtitle_language

    burn_profile = str(payload.get("burnProfile") or "").strip()
    if burn_profile in BURN_PROFILES:
        settings["burnProfile"] = burn_profile

    subtitle_size = str(payload.get("subtitleSize") or "").strip()
    if subtitle_size in SUBTITLE_SIZE_PRESETS:
        settings["subtitleSize"] = subtitle_size

    translator_label = str(payload.get("translatorLabel") or "").strip()
    if translator_label:
        settings["translatorLabel"] = translator_label[:20]

    search_query = str(payload.get("searchQuery") or "").strip()[:160]
    if search_query == YOUTUBE_LEGACY_DEFAULT_QUERY:
        search_query = YOUTUBE_DEFAULT_QUERY
    settings["searchQuery"] = search_query or YOUTUBE_DEFAULT_QUERY

    settings["watermarkEnabled"] = bool(payload.get("watermarkEnabled", False))
    watermark_text = str(payload.get("watermarkText") or "").strip()[:16]
    settings["watermarkText"] = watermark_text if len(watermark_text) >= 2 else ""

    settings["coverSignature"] = normalize_cover_signature(payload.get("coverSignature", payload.get("coverBrandName")))
    settings["highlightCount"] = _normalize_highlight_count(payload.get("highlightCount", settings["highlightCount"]))
    settings["translationEnabled"] = bool(payload.get("translationEnabled", True))
    settings["highlightIntroEnabled"] = bool(payload.get("highlightIntroEnabled", True))
    settings["coverIntroEnabled"] = bool(payload.get("coverIntroEnabled", True))
    settings["commentBurnEnabled"] = bool(payload.get("commentBurnEnabled", False)) and settings["processVersion"] == PROCESS_VERSION_EDITING and _comment_burn_available()
    settings["contentSafetyReviewEnabled"] = bool(payload.get("contentSafetyReviewEnabled", False))

    return settings


def get_workflow_settings():
    init_database_tables()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (WORKFLOW_SETTINGS_KEY,))
        row = cursor.fetchone()
    if not row:
        settings = _default_workflow_settings()
        return {**settings, "commentBurnAvailable": _comment_burn_available()}
    try:
        settings = _normalize_workflow_settings(json.loads(row[0]))
    except Exception:
        settings = _default_workflow_settings()
    return {**settings, "commentBurnAvailable": _comment_burn_available()}


def update_workflow_settings(payload):
    current_settings = get_workflow_settings()
    settings = _normalize_workflow_settings({**current_settings, **(payload if isinstance(payload, dict) else {})})
    init_database_tables()
    with _db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (WORKFLOW_SETTINGS_KEY, json.dumps(settings, ensure_ascii=False)),
        )
        conn.commit()
    return {**settings, "commentBurnAvailable": _comment_burn_available()}
