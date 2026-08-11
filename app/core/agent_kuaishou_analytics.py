"""快手分析工具的 Agent 参数、执行与结果卡片适配。"""

from __future__ import annotations


KUAISHOU_ANALYTICS_TOOL_NAMES = {
    "get_published_video_metrics",
    "list_account_video_metrics",
    "get_published_video_comments",
}


def normalize_kuaishou_agent_args(name, args):
    if name not in KUAISHOU_ANALYTICS_TOOL_NAMES:
        return args
    platform = args.get("platform")
    if isinstance(platform, (list, tuple, set, dict)) or str(platform or "").strip().lower() != "kuaishou":
        raise ValueError("快手分析工具的 platform 只能是单个字符串 kuaishou")
    if "limit" in args:
        maximum = 100 if name == "list_account_video_metrics" else 50
        default = 50 if name == "list_account_video_metrics" else 20
        args["limit"] = max(1, min(int(args.get("limit") or default), maximum))
    return args


def run_kuaishou_agent_tool(name, args):
    if name == "get_published_video_metrics":
        return True, get_published_video_metrics(
            args.get("platform"), args.get("publishRecordId"), args.get("accountId"), args.get("platformWorkId")
        )
    if name == "list_account_video_metrics":
        return True, list_account_video_metrics(
            args.get("platform"), args.get("accountId"), args.get("fromDate"), args.get("toDate"), args.get("limit")
        )
    if name == "get_published_video_comments":
        if args.get("userConfirmed") is not True:
            raise ValueError("评论采样必须由用户明确选择作品并确认")
        return True, get_published_video_comments(args.get("platform"), args.get("publishRecordId"), args.get("limit"))
    return False, None


def kuaishou_analytics_skill_loaded(observations):
    return any(
        item.get("tool") == "load_skill"
        and (item.get("result") or {}).get("name") == "kuaishou-analytics"
        for item in observations or []
    )


def kuaishou_agent_result_cards(name, result):
    cards, actions = [], []
    if name == "get_published_video_metrics":
        if result.get("needsClarification"):
            for candidate in (result.get("candidates") or [])[:8]:
                candidate_id = candidate.get("platformWorkId") or candidate.get("accountId")
                actions.append({
                    "type": "ask",
                    "label": candidate.get("title") or candidate.get("accountName") or str(candidate_id),
                    "message": (
                        f"我选择 accountId={candidate_id}，继续分析快手发布记录 publishRecordId={result.get('publishRecordId') or ''}。"
                        if candidate.get("accountId") else
                        f"我选择 platformWorkId={candidate_id}，继续分析快手发布记录 publishRecordId={result.get('publishRecordId') or ''}。"
                    ),
                })
        else:
            current = result.get("current") or {}
            metrics = current.get("metrics") or {}
            cards.append({
                "type": "kuaishou-metrics",
                "title": current.get("title") or "快手作品数据",
                "count": metrics.get("views"),
                "items": [
                    {"title": "播放", "detail": metrics.get("views"), "status": f"较上次 {result.get('delta', {}).get('views')}"},
                    {"title": "点赞", "detail": metrics.get("likes"), "status": f"评论 {metrics.get('comments')} / 分享 {metrics.get('shares')}"},
                ],
            })
            actions.append({
                "type": "ask", "label": "分析这条视频评论",
                "message": f"请采样并分析快手发布记录 {result.get('publishRecordId')} 的评论，我确认读取这条作品的评论。",
            })
    elif name == "list_account_video_metrics":
        videos = result.get("items") or []
        cards.append({
            "type": "kuaishou-ranking",
            "title": f"快手作品表现（样本 {result.get('sampleSize', 0)} 条）",
            "count": result.get("sampleSize", 0),
            "items": [
                {
                    "title": video.get("title") or "未命名作品",
                    "detail": f"播放 {video.get('metrics', {}).get('views')} / 互动率 {video.get('derived', {}).get('engagementRate')}",
                    "status": "已关联本地视频" if video.get("localVideoLinked") else "未关联本地原视频",
                }
                for video in videos[:5]
            ],
        })
        for video in videos[:5]:
            if video.get("publishRecordId"):
                actions.append({
                    "type": "ask", "label": f"分析评论：{(video.get('title') or '该作品')[:18]}",
                    "message": f"请采样并分析快手发布记录 {video.get('publishRecordId')} 的评论，我确认读取这条作品的评论。",
                })
    elif name == "get_published_video_comments":
        comments = result.get("items") or []
        cards.append({
            "type": "kuaishou-comments",
            "title": f"快手评论样本（{len(comments)} 条）",
            "count": len(comments),
            "items": [
                {"title": item.get("body") or "", "detail": f"点赞 {item.get('likeCount')}", "status": item.get("publishedAt") or ""}
                for item in comments[:5]
            ],
        })
    return cards, actions
