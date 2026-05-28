PLATFORM_TYPE_TO_NAME = {
    1: "小红书",
    2: "视频号",
    3: "抖音",
    4: "快手",
    5: "B站",
}

PLATFORM_NAME_TO_TYPE = {name: value for value, name in PLATFORM_TYPE_TO_NAME.items()}


def platform_name(platform_type):
    try:
        return PLATFORM_TYPE_TO_NAME.get(int(platform_type), str(platform_type or ""))
    except (TypeError, ValueError):
        return str(platform_type or "")


def platform_type_from_name(name):
    return PLATFORM_NAME_TO_TYPE.get(str(name or "").strip(), 0)


def clean_unique_list(values):
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


def normalize_publish_targets(payload):
    raw_targets = payload.get("targets")
    if isinstance(raw_targets, list) and raw_targets:
        targets = []
        seen_platforms = set()
        for raw in raw_targets:
            if not isinstance(raw, dict):
                raise ValueError("发布目标格式错误")
            try:
                platform_type = int(raw.get("platformType") or raw.get("type") or 0)
            except (TypeError, ValueError):
                platform_type = 0
            if platform_type not in PLATFORM_TYPE_TO_NAME:
                raise ValueError("发布目标包含不支持的平台")
            if platform_type in seen_platforms:
                raise ValueError(f"{platform_name(platform_type)} 只能选择一个账号")
            account_file = str(raw.get("accountFile") or raw.get("account") or "").strip()
            if not account_file:
                raise ValueError(f"{platform_name(platform_type)} 未选择账号")
            seen_platforms.add(platform_type)
            targets.append({
                "platformType": platform_type,
                "platformName": platform_name(platform_type),
                "accountFile": account_file,
                "accountId": raw.get("accountId"),
                "accountName": raw.get("accountName") or "",
            })
        return targets

    try:
        platform_type = int(payload.get("type") or 0)
    except (TypeError, ValueError):
        platform_type = 0
    if platform_type not in PLATFORM_TYPE_TO_NAME:
        raise ValueError("平台类型不能为空")
    account_list = clean_unique_list(payload.get("accountList") or [])
    if len(account_list) != 1:
        raise ValueError("每个平台只能选择一个账号")
    return [{
        "platformType": platform_type,
        "platformName": platform_name(platform_type),
        "accountFile": account_list[0],
        "accountId": "",
        "accountName": "",
    }]
