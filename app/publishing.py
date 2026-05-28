PLATFORM_TYPE_TO_NAME = {
    1: "小红书",
    2: "视频号",
    3: "抖音",
    4: "快手",
    5: "B站",
}

PLATFORM_NAME_TO_TYPE = {name: value for value, name in PLATFORM_TYPE_TO_NAME.items()}

BILIBILI_DEFAULT_TID = 21

BILIBILI_CATEGORIES = [
    {"tid": 21, "group": "生活", "name": "日常"},
    {"tid": 180, "group": "纪录片", "name": "社会·美食·旅行"},
    {"tid": 37, "group": "纪录片", "name": "人文·历史"},
    {"tid": 138, "group": "生活", "name": "搞笑"},
    {"tid": 161, "group": "生活", "name": "手工"},
    {"tid": 239, "group": "生活", "name": "家居房产"},
    {"tid": 201, "group": "知识", "name": "科学科普"},
    {"tid": 124, "group": "知识", "name": "社科·法律·心理"},
    {"tid": 228, "group": "知识", "name": "人文历史"},
    {"tid": 207, "group": "知识", "name": "财经商业"},
    {"tid": 209, "group": "知识", "name": "职业职场"},
    {"tid": 215, "group": "美食", "name": "美食记录"},
    {"tid": 76, "group": "美食", "name": "美食制作"},
    {"tid": 213, "group": "美食", "name": "美食测评"},
    {"tid": 85, "group": "影视", "name": "短片"},
    {"tid": 182, "group": "影视", "name": "影视杂谈"},
    {"tid": 183, "group": "影视", "name": "影视剪辑"},
    {"tid": 95, "group": "科技", "name": "数码"},
    {"tid": 230, "group": "科技", "name": "软件应用"},
    {"tid": 231, "group": "科技", "name": "计算机技术"},
]


def _with_bilibili_category_label(category):
    item = dict(category)
    item["label"] = f"{item['group']} / {item['name']}"
    return item


BILIBILI_CATEGORY_OPTIONS = [_with_bilibili_category_label(item) for item in BILIBILI_CATEGORIES]
BILIBILI_CATEGORY_BY_TID = {int(item["tid"]): item for item in BILIBILI_CATEGORY_OPTIONS}


def bilibili_categories():
    return [dict(item) for item in BILIBILI_CATEGORY_OPTIONS]


def normalize_bilibili_tid(value, default=BILIBILI_DEFAULT_TID):
    try:
        tid = int(value or default)
    except (TypeError, ValueError):
        return int(default)
    return tid if tid > 0 else int(default)


def bilibili_category_label(tid):
    tid = normalize_bilibili_tid(tid)
    item = BILIBILI_CATEGORY_BY_TID.get(tid)
    return item["label"] if item else f"未知分区（{tid}）"


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
                "bilibiliTid": normalize_bilibili_tid(raw.get("bilibiliTid") or payload.get("bilibiliTid")) if platform_type == 5 else "",
                "productLink": str(raw.get("productLink") or payload.get("productLink") or "").strip() if platform_type == 3 else "",
                "productTitle": str(raw.get("productTitle") or payload.get("productTitle") or "").strip() if platform_type == 3 else "",
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
        "bilibiliTid": normalize_bilibili_tid(payload.get("bilibiliTid")) if platform_type == 5 else "",
        "productLink": str(payload.get("productLink") or "").strip() if platform_type == 3 else "",
        "productTitle": str(payload.get("productTitle") or "").strip() if platform_type == 3 else "",
    }]
