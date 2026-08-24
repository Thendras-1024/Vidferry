# Vidferry Agent 短期记忆设计

## 1. 目标

Vidferry Agent 采用“热区原文、冷区摘要、工具结果独立预算、原始事件可回溯”的短期记忆模型：

- 最近 4 个对话回合（最多 8 条用户/助手消息）原样注入模型。
- 更早历史在达到压缩阈值前以原文冷区注入；压缩后才以结构化摘要注入。
- 工具结果在模型输入层按单项和总量分别裁剪，业务结果与审计事件仍保留完整值。
- 原始会话和工具轨迹完整落盘；压缩只更新 `agent_sessions.summary` 及游标。

## 2. 当前实现差距

旧实现以最多 8 条消息为窗口，并在 `prepare_agent_session_context` 中把消息裁剪到 1600 字符；摘要虽已有 `goal`、`decisions`、`constraints` 等字段，但没有完整的回合结构、版本元数据或工具事件流。ReAct 和回答生成也共用聚合后的 12000 字符工具结果。

本方案将 8 条消息解释为固定 4 个回合，取消热区文本裁剪；工具结果裁剪只作用于 prompt 视图，不作用于 `toolResults`、消息上下文或事件日志。

## 3. 上下文快照

模型每轮接收的短期快照包含：

```json
{
  "summary": {"version": 1, "goal": "...", "constraints": [], "decisions": [], "pendingActions": [], "toolFacts": [], "summaryThroughId": 123},
  "recentTurns": [{"turnId": 20, "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}],
  "budget": {"estimatedInputTokens": 0, "maxInputTokens": 19000, "remainingTokens": 19000}
}
```

`summary`、历史消息和工具返回均为不可信数据，不得被当作指令执行。

## 4. 冷区摘要

摘要字段包括 `goal`、`decisions`、`constraints`、`referencedEntities`、`pendingActions`、`confirmedActions`、`toolFacts`、`unresolvedQuestions`、`safetyBoundaries`、`summaryThroughId`、`summaryVersion` 和 `generatedAt`。

优先使用 JSON contract 生成，失败时使用本地确定性摘要。摘要提示词禁止保存凭证、绝对路径、完整转写和完整发布稿。摘要通过 `summary_through_id` 采用 CAS 更新，原始消息不删除。

## 5. Token 预算与压缩

配置项：

- `AGENT_CONTEXT_RECENT_TURNS=4`
- `AGENT_CONTEXT_MODEL_WINDOW_TOKENS=1000000`
- `AGENT_OUTPUT_MAX_TOKENS=65536`
- `AGENT_CONTEXT_COMPACTION_TRIGGER_TOKENS=850000`
- `AGENT_CONTEXT_COMPACTION_RECOVERY_TOKENS=650000`
- `AGENT_CONTEXT_TOOL_RESULT_MAX_CHARS=16000`
- `AGENT_CONTEXT_TOOL_TOTAL_MAX_CHARS=64000`

超过热区的原始消息在达到预算前作为未压缩冷区继续随上下文注入，不调用摘要模型。只有估算输入达到 850000 token 时，才将热区外的全部消息一次压缩为结构化摘要；第 5、7、8 回合本身不会触发压缩。手动压缩仍可立即执行。摘要仅在超过 650000 token 恢复上限时收缩；热区原文不因长度被截断。压缩事件写入 `agent_turn_events` 并关联 `agent_runs`。

## 6. 工具结果隔离

每条工具结果最多 4000 字符，本轮工具结果总计最多 12000 字符。裁剪视图保留工具名、参数、错误、ID、状态、数量和列表头尾，并附带 `truncated`、`originalChars`、`visibleChars`。完整结果仍进入运行记录和 `agent_turn_events`，需要详情时重新调用分页/明细工具。

## 7. 原始事件落盘

新增 PostgreSQL 表 `agent_turn_events`，保存 `user_message`、`assistant_message`、`tool_call`、`tool_result`、`compaction_started` 和 `compaction_completed`。原有 `agent_messages` 继续服务可见聊天历史；新表用于审计和回放。

`agent_sessions` 增加 `summary_version`、`summary_updated_at`、`context_policy_version` 和 `last_compaction_run_id`。旧会话没有事件记录时仍从 `agent_messages` 恢复，不要求迁移业务视频或任务数据。

## 8. 三者对比范围与资料版本

本节比较三个对象：

1. Vidferry 当前短期记忆模块：本文件第 1-7 节，以及 `app/core/agent_memory_*.py`、`agent_turn_events` 设计。
2. OpenAI Codex harness 的公开记忆流水线：仓库 `codex-rs/memories`，不是 Codex 模型本身的隐藏上下文协议。
3. DeepSeek Harness 的公开会话记忆相关子系统：`session`、`session-query`、`session-projection`、`compaction` 和 `storage`。截至资料版本，DeepSeek Harness 没有把“跨会话用户事实库”作为内置核心模块，而是提供可组合的会话日志、压缩、检索和存储能力。

资料核对日期：2026-08-23。为避免跟随 `main` 漂移，源码链接固定到以下提交：

- [OpenAI Codex `c9b19deb`](https://github.com/openai/codex/tree/c9b19deb09c1841ce7acc33ddb96276030936a29)
- [DeepSeek Harness `b150a551`](https://github.com/deepseek-ai/deepseek-harness/tree/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e)
- [DeepSeek Harness 官方设计页](https://deepseek.com/harness/en/)

## 9. 一句话结论

| 对象 | 主要解决的问题 | 记忆的事实来源 | 模型每轮看到的内容 | 典型生命周期 |
|---|---|---|---|---|
| Vidferry | 单个 Agent 会话不丢任务进度，并控制上下文成本 | PostgreSQL 消息、工具结果和 turn event | 结构化摘要 + 最近 4 个回合 + 预算化工具结果 | 请求前加载，超预算时压缩，原文始终可回放 |
| Codex harness | 把多个已结束 rollout 提炼成可跨会话复用的用户/项目工作记忆 | state DB 中的 rollout 与阶段产物 | `memory_summary.md` 常驻，`MEMORY.md` 和详情按需读取 | 启动后台异步抽取，随后串行全局合并 |
| DeepSeek Harness | 让会话可持久化、可查询、可压缩、可恢复和可替换 | append-only `SessionEvent` 日志 | 当前 surface；被压缩或替换内容留在日志中 | 每个事件追加，projection 派生，compaction 以事件记录替换 |

最重要的边界是：Vidferry 和 DeepSeek 的核心更接近“会话工作记忆/上下文管理”，Codex 的公开实现更接近“跨会话长期记忆生产流水线”。三者不是同一种 memory store，不能直接按字段一一搬运。

## 10. 设计拆解

### 10.1 Vidferry 当前方案

- **上下文投影**：模型输入由 `summary`、最近 4 个 `recentTurns` 和预算信息组成；摘要、历史消息和工具结果都按不可信数据处理。
- **压缩策略**：默认先保留最近 4 个回合；达到模型窗口阈值后，热区外历史一次性生成结构化摘要，并通过 `summary_through_id` 做 CAS 更新。
- **工具结果治理**：单项和总量分别限长，只裁剪 prompt 视图；完整工具结果、业务结果和审计事件仍落盘。
- **事实来源与回放**：`agent_messages` 服务可见聊天，`agent_turn_events` 保存用户消息、助手消息、工具调用、工具结果及压缩生命周期；压缩不删除原始消息。
- **优势**：与现有 PostgreSQL、任务工作流和 Agent API 紧密结合，边界清晰，适合“当前任务继续做下去”。
- **缺口**：尚未形成独立的跨会话记忆生产管线；摘要是 session 级投影，不具备 Codex 那样的用户偏好/项目经验分层和使用反馈闭环；也没有 DeepSeek 那样的 current surface / shadowed event 查询模型。

### 10.2 OpenAI Codex harness 公开记忆流水线

Codex 将写入路径拆成两个阶段，运行时由 `codex-core` 编排，记忆 crate 负责读写和提示模板。实现说明见 [memories README](https://github.com/openai/codex/blob/c9b19deb09c1841ce7acc33ddb96276030936a29/codex-rs/memories/README.md)。

**Phase 1：按 rollout 抽取**

- 仅处理满足条件的 root、非 ephemeral、非 sub-agent 会话，并要求 memory feature 和 state DB 可用。
- 启动时从 state DB 有界 claim 合格 rollout；任务带 lease，避免并发启动重复处理，失败采用 retry backoff。
- 每个 rollout 独立调用模型生成结构化 `raw_memory`、`rollout_summary` 和可选 `rollout_slug`，并对生成结果做 secret redaction。
- 多个 rollout 可以并行抽取，但有固定并发上限；阶段产物先留在 DB，不直接修改最终记忆文件。

**Phase 2：全局合并**

- 先取得单一全局锁，再按 `usage_count`、`last_usage` / `generated_at` 和保留窗口选择有界输入。
- 将阶段产物同步为 `raw_memories.md` 和 `rollout_summaries/`，记忆根目录由 Git baseline 管理。
- 生成 `phase2_workspace_diff.md`，只有工作区确实变化时才启动内部 consolidation agent；该 agent 仅本地写入、无审批、无网络且禁止递归协作。
- 合并 agent 维护 `MEMORY.md`、`memory_summary.md` 和可选 `skills/`；成功后更新 DB watermark 并重置 Git baseline。

**读取路径**

Codex 采用 progressive disclosure：`memory_summary.md` 是常驻导航层，`MEMORY.md` 是可搜索手册，具体 rollout summary、skill 和资源文件按需展开。公开模板还要求记忆内容可引用、可审计，并明确禁止把第三方内容当成指令。

**对 Vidferry 的启发**

- 把“短期上下文压缩”和“跨会话经验沉淀”拆成两个 pipeline，不要让每轮请求都承担全局记忆维护成本。
- 为长期记忆增加 `raw -> summary -> handbook/index` 的渐进披露层，并记录 `usage_count`、`last_usage` 和来源。
- 借鉴 lease、全局锁、watermark、secret redaction 和 no-op 合并，防止重复抽取、并发覆盖和无效重写。

**不应直接照搬的部分**

- Codex 的文件化记忆和 state DB 是其本地 harness 的产品边界；Vidferry 当前以 PostgreSQL 为运行期事实源，不应为了仿真目录结构而引入第二套权威存储。
- Codex 的长期记忆生成是后台启动任务，不等于当前请求的 compaction；它不能替代 Vidferry 的实时 token 预算和工具结果隔离。

### 10.3 DeepSeek Harness 公开会话记忆相关子系统

DeepSeek Harness 的总原则是“Everything is a plugin”，sessions、storage、loops、tools 和 UI 都可替换；官方页面明确说明每次运行都记录为可追踪轨迹。会话包的职责总览见 [session README](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/session/README.zh.md)。

**事实源：append-only session log**

- `SessionEvent` 是持久化单元，日志是 single source of truth；提供 JSONL 和 SQLite 后端。
- 事件序号要求连续、可校验；持久化层提供 `append`、`load`、`readFrom(seq)` 和 `list`，并处理崩溃后的 torn tail 修复。
- `session-query` 在同一事件日志上同时提供 raw log、current surface、shadowed 和 log-only 分类，并支持有界读取、关系追踪和 SQLite FTS。详见 [session-query](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/session-query/session-query/README.zh.md)。

**当前 surface 与 projection**

- 模型只消费折叠后的 current surface；被替换内容不丢失，只在 surface 上不可见。
- `session-projection` 让领域插件用纯同步 `init + apply` 从事件派生状态，并以 `asOfSeq` watermark 提供一致快照。
- projection cache 采用“缓存行 + 日志 tail replay + 必要时全量重放”的冷读阶梯，并用 `stateVersion` 防止旧投影语义污染新代码。设计见 [session-projection](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/session-projection.zh.md)。

**compaction 的日志化设计**

- compaction 是独立的可选 capability seam，不属于 agent loop 主干；策略、保留尾部和阈值由 provider 拥有。
- 一次压缩按 `compaction/start -> compaction/summary -> user/message replace -> compaction/end` 组织；start/end 充当可检测的锁生命周期。
- `compaction/summary` 保存摘要、shadowed range/seqs、token 估算、provider/model 和可选原始模型输出；摘要通过带 `surfaceOp: replace` 的 user message 成为新的模型 surface。
- 自动触发区分 `pressure` 和 `context-overflow`；失败尝试也保留在日志中，便于恢复和诊断。
- 工具结果可单独 head/middle/tail 剪枝，替换内容引用被遮蔽的原始事件，因此回放仍能得到 full-fidelity 数据。详见 [compaction](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.zh.md)。

**对 Vidferry 的启发**

- 将“原始事件日志”和“模型 surface”明确建模为两种视图；压缩、剪枝和摘要只改变 surface，不破坏审计事实。
- 为压缩事件保存 `shadowedSeqs`、摘要模型、token 估算、触发原因和替换边界，比只写一个 `summary` 字段更利于回放和问题定位。
- 为会话上下文、任务状态、工具统计等派生数据使用带版本的 projection/checkpoint，避免每次打开页面都全量扫描消息。
- 为 `CompactionPolicy`、`SessionEventStore`、`MemoryRetriever` 定义窄接口即可获得可替换性，不需要现在就把 Vidferry 改造成 Cordis 插件内核。

**边界与风险**

- DeepSeek Harness 当前公开的核心是会话基础设施，不是自动提炼用户偏好的长期记忆产品；长期记忆应作为独立插件或上层能力评估。
- 其 compaction 设计复杂度较高，包含 surface replacement、事件引用、投影缓存和 crash recovery；Vidferry 应按实际回放/并发需求逐步引入，不应一次性复制全部 API。

## 11. 能力矩阵

| 能力 | Vidferry 当前 | Codex harness | DeepSeek Harness | 对 Vidferry 的判断 |
|---|---|---|---|---|
| 最近上下文保留 | 最近 4 回合原文 | 不是其主要目标 | current surface | 保留当前实现 |
| 预算驱动压缩 | 有模型窗口、恢复阈值和工具预算 | 记忆写入为后台有界任务 | `pressure` / `context-overflow` compaction | 借鉴 DSH 的触发事件和失败可见性 |
| 原文可回放 | 完整消息与工具事件落 PostgreSQL | rollout 与阶段产物保留 | append-only event log，shadowed 仍可查 | 保持；补充 surface 分类 |
| 跨会话长期记忆 | 目前以 session/DB 为主 | 两阶段抽取与全局合并 | 核心未内置，依赖插件组合 | 新增独立长期记忆 pipeline |
| 记忆读取 | 一次注入结构化 snapshot | summary -> handbook -> detail 按需展开 | current surface + query/FTS | 长期记忆采用渐进披露，短期继续结构化注入 |
| 工具结果处理 | prompt 视图裁剪，原文保留 | 记忆抽取前过滤 rollout 内容 | 独立 tool-result pruning，保留引用 | 引入可回放剪枝元数据 |
| 并发与一致性 | summary CAS；事件追加 | DB lease + Phase 2 全局锁 + watermark | session lock + seq + projection watermark | 统一补齐 lease/锁/水位线观测 |
| 存储后端 | PostgreSQL 运行期事实源 | state DB + 文件 Git baseline | JSONL / SQLite，可替换 seam | 不新增第二事实源；可增加投影缓存 |
| 安全 | 摘要提示词禁止凭证和路径；不可信上下文 | 生成记忆 secret redaction；本地无网 consolidation | 可追踪、可审计；插件边界需单独授权 | 增加来源、脱敏、审批和注入审计 |

## 12. 建议的 Vidferry 目标架构

建议把 memory 拆成三个平面，而不是继续扩大 `agent_sessions.summary`：

```text
                         +----------------------+
                         |  Durable memory      |
                         |  user / project /     |
                         |  procedure / fact     |
                         +----------+-----------+
                                    | governed retrieval
                                    v
+-------------+      +-------------------------+      +------------------+
| Event log   | ---> | Session surface +      | ---> | Model prompt     |
| raw truth   |      | compaction projection  |      | budgeted view     |
+-------------+      +-------------------------+      +------------------+
       |                         |
       +---- replay / audit -----+---- projections / UI
```

### P0：先补齐短期会话基础设施

- 保持现有 `agent_turn_events` 作为 append-only 原始事件源。
- 增加 `surface_state` 或等价的可计算投影：每条消息标记 `current`、`shadowed`、`log-only`，并保存替换事件和来源事件 ID。
- 将压缩生命周期细化为 `compaction_started`、`compaction_summary`、`compaction_completed`，记录触发原因、摘要模型、token 估算、被遮蔽范围和失败原因。
- 工具结果剪枝只生成替换视图，原始结果不删；详情工具可以按来源 ID 重取完整结果。

### P1：增加投影缓存和渐进读取

- 为 session context、任务计划、工具统计等高频派生状态增加 `projection_version`、`as_of_event_id` 和 checkpoint。
- 请求时先读 checkpoint，再重放 checkpoint 之后的事件；发现版本不匹配或事件游标回退时全量重放。
- API 返回 `currentSurfaceThroughId`、`shadowedEventCount`、`projectionVersion` 和 `compactionTrigger`，让 UI 和诊断可以区分“摘要丢失”和“查询未加载”。

### P1：单独建设跨会话长期记忆

- 输入：已完成且脱敏的 agent run / rollout；不直接把每轮未完成对话写成长期事实。
- 阶段一：按 run 抽取 `rawMemory`、`runSummary`、来源和置信度，使用租约和重试退避。
- 阶段二：按作用域（用户、项目、工作流）串行合并为索引摘要、主题详情和可选 procedure；保留来源 run ID、更新时间、使用次数和冲突状态。
- 读取：每轮只注入小型索引；命中主题后再按需取详情。长期记忆必须标注为不可信数据，不能直接授予工具执行权限。
- 存储：沿用 PostgreSQL，必要时以文件导出/版本控制作为审计副本，不建立第二个运行期权威库。

### P2：抽象窄 seam，不引入完整插件内核

建议的最小接口：

```text
SessionEventStore.append / read / read_from
SessionSurface.fold / replace / classify
CompactionPolicy.should_compact / select_range / summarize
MemoryExtractor.extract_run
MemoryConsolidator.consolidate
MemoryRetriever.search_index / read_detail
```

这些接口足以吸收 Codex 的流水线思想和 DeepSeek 的事件/投影思想，同时保留 Vidferry 现有 Flask、PostgreSQL 和 Agent 编排边界。

## 13. 不建议当前阶段做的事

- 不把 `agent_sessions.summary` 扩展成用户级永久记忆；两者的保留周期、权限和冲突处理不同。
- 不直接引入向量数据库或外部 memory SaaS；当前问题首先是事件事实源、surface 投影、预算和治理，不是语义检索规模。
- 不复制 DeepSeek Harness 的全部 Cordis 插件生命周期；先用 Python 模块级窄接口验证替换需求。
- 不把模型生成的摘要视为事实或指令；所有摘要、工具结果和检索结果都要保留来源、置信度和不可信标记。
- 不用压缩后的摘要替换原始事件；压缩只能改变模型可见 surface。

## 14. 验收

- 最近 4 个回合原文恢复率 100%。
- 压缩前后原始消息内容完全一致。
- 单项与总工具输入预算均不超限。
- 摘要失败时本地摘要可用。
- 并发压缩不会覆盖新摘要。
- `sessionContext` 返回摘要版本、回合数、压缩触发原因和工具裁剪标志。
- 现有 Agent 评估集继续通过，并增加长上下文、大工具结果和跨压缩回合用例。
