# 指标口径

- `viewsPerDay = views / max(作品发布至今的天数, 1)`
- `likeRate = likes / views`
- `commentRate = comments / views`
- `engagementRate = (likes + comments + shares) / views`

当 `views` 为 `0` 或缺失时，比率返回 `null`。任何平台未提供的原始指标也返回 `null`，不得按 `0` 处理或推断。

批量结论必须同时给出 `sampleSize`。`truncated=true` 表示结果只覆盖查询上限内的作品，不代表账号在日期范围内只有这些作品。
