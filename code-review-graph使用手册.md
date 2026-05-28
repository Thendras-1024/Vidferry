# code-review-graph 终极精简使用手册

## 最常用终端命令（必记）
code-review-graph install          # 自动配置所有 AI 工具（Codex/Cursor等）
code-review-graph install --platform codex  # 只给 Codex 配置
code-review-graph build            # 全量构建项目代码图谱
code-review-graph update           # 增量更新（只扫描改动文件，超快）
code-review-graph status           # 查看图谱统计（文件数/节点/关系）
code-review-graph watch            # 实时监听文件，自动更新图谱
code-review-graph visualize        # 生成网页可视化结构图
code-review-graph detect-changes --brief  # 查看本次改动影响范围 + 省了多少Token

## Codex / AI 编辑器内命令（斜杠 / 触发）
/code-review-graph:build-graph     构建/重建代码图谱
/code-review-graph:review-delta    审查【上次提交后】的所有代码改动
/code-review-graph:review-pr       完整PR审查（含影响范围分析）

## 你日常只用这 4 条就够了
code-review-graph build（第一次）
code-review-graph watch（开着自动更）
/code-review-graph:review-delta（写代码后审查）
code-review-graph status（看状态）