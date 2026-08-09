<template>
          <section v-if="showPage" class="agent-page">
            <header class="agent-page-header">
              <div>
                <span class="agent-drawer-kicker">PROJECT AGENT</span>
                <h1>{{ currentAgentTitle }}</h1>
              </div>
              <div class="agent-page-status">
                <span class="status-pulse" :class="{ 'is-warning': agentConfigWarning }" />
                <span>{{ agentConfigWarning ? '配置待检查' : 'Agent 在线' }}</span>
                <el-tag size="small" effect="plain" :type="agentSessionSource === 'feishu' ? 'success' : 'info'">{{ agentSessionSourceLabel }}</el-tag>
              </div>
            </header>
            <div class="agent-panel">
              <div class="agent-context-card">
                <div class="agent-avatar"><el-icon><ChatDotRound /></el-icon></div>
                <div class="agent-context-copy">
                  <strong>Vidferry 项目管家</strong>
                  <span>视频采集、处理、素材与发布状态查询</span>
                </div>
              </div>
              <div v-if="agentSessionId" class="agent-context-status">
                <el-button text size="small" class="agent-context-toggle" @click="agentContextDetailsVisible = !agentContextDetailsVisible">
                  {{ agentContextUsageLabel }} · {{ agentCurrentSession?.messageCount || 0 }} 条消息
                </el-button>
                <el-tooltip content="压缩上下文" placement="bottom">
                  <el-button text circle size="small" aria-label="压缩上下文" :loading="agentCompaction.state === 'running'" @click="compactCurrentAgentSession">
                    <el-icon><RefreshRight /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
              <div v-if="agentContextDetailsVisible && agentContextStats" class="agent-context-details">
                <span>预估输入 {{ agentContextStats.estimatedInputTokens }} tokens</span>
                <span>最近实际 {{ agentContextStats.lastPromptTokens || '暂无' }} tokens</span>
                <span>摘要覆盖至 #{{ agentContextStats.summaryThroughId || 0 }}</span>
                <span>自动压缩：{{ agentContextStats.compactAfterMessages }} 条或 {{ agentContextStats.compactAfterChars }} 字符</span>
              </div>
              <div v-if="agentCompaction.state !== 'idle'" class="agent-compaction-activity" :class="`is-${agentCompaction.state}`" aria-live="polite">
                <el-icon v-if="agentCompaction.state === 'running'" class="is-loading"><Loading /></el-icon>
                <span>{{ agentCompaction.message }}</span>
                <small>{{ agentCompactionElapsedSeconds }} 秒</small>
              </div>
              <div v-if="!agentSessionReadonly && agentMessages.length === 0" class="agent-quick-panel">
                <div class="agent-section-title">从当前工作流开始</div>
                <div class="agent-quick-actions">
                  <el-button v-for="question in agentQuickQuestions" :key="question" size="small" plain @click="sendAgentMessage(question)">{{ question }}</el-button>
                </div>
              </div>
              <div ref="agentMessagesRef" class="agent-messages" @scroll.passive="handleAgentMessagesScroll">
                <div v-if="agentOlderMessagesLoading" class="agent-older-loading" aria-live="polite">
                  <el-icon class="is-loading"><Loading /></el-icon><span>正在加载更早消息</span>
                </div>
                <div v-for="message in agentMessages" :key="message.id" class="agent-message" :class="`is-${message.role}`">
                  <div class="agent-message-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
                  <div class="agent-message-content">
                    <div v-if="message.thinking" class="agent-thinking" aria-live="polite">
                      <el-icon class="agent-thinking-icon is-loading"><Loading /></el-icon><span>{{ message.statusMessage || '正在思考' }}</span>
                    </div>
                    <span v-if="message.content">{{ message.content }}</span>
                  </div>
                  <div v-for="card in message.cards || []" :key="`${message.id}-${card.type}-${card.title}`" class="agent-result-card">
                    <div class="agent-card-title"><span>{{ card.title }}</span><strong>{{ card.count }}</strong></div>
                    <div v-for="item in card.items || []" :key="`${item.title}-${item.detail || item.status}`" class="agent-card-item">
                      <strong>{{ item.title }}</strong><span>{{ item.detail || item.channel || item.status }}</span>
                    </div>
                  </div>
                  <section v-if="message.importProposal" class="agent-proposal">
                    <div class="agent-proposal-title">
                      <span>待确认线索</span><strong>{{ message.importProposal.items?.length || 0 }}</strong>
                    </div>
                    <el-checkbox-group v-if="message.importProposal.status === 'pending'" v-model="message.selectedCandidateIds" class="agent-proposal-list">
                      <el-checkbox v-for="item in message.importProposal.items || []" :key="item.id" :value="item.id" class="agent-proposal-item">
                        <span class="agent-proposal-copy"><strong>{{ item.title }}</strong><small>{{ [item.channel, item.duration].filter(Boolean).join(' · ') }}</small></span>
                      </el-checkbox>
                    </el-checkbox-group>
                    <el-checkbox-group v-else-if="message.importProposal.status === 'confirmed'" v-model="message.selectedCandidateIds" class="agent-proposal-list is-readonly">
                      <el-checkbox v-for="item in message.importProposal.items || []" :key="item.id" :value="item.id" disabled class="agent-proposal-item">
                        <span class="agent-proposal-copy"><strong>{{ item.title }}</strong><small>{{ [item.channel, item.duration].filter(Boolean).join(' · ') }}</small></span>
                      </el-checkbox>
                    </el-checkbox-group>
                    <el-checkbox-group v-if="message.importProposal.status === 'pending' && message.importProposal.requiresTargets" v-model="message.selectedImportAccountIds" class="agent-proposal-targets" @change="normalizeImportAccountSelection(message)">
                      <el-checkbox v-for="account in message.importProposal.availableAccounts || []" :key="account.id" :value="account.id">{{ account.platformName }} · {{ account.name }}</el-checkbox>
                    </el-checkbox-group>
                    <el-checkbox-group v-else-if="message.importProposal.status === 'confirmed' && message.importProposal.requiresTargets" v-model="message.selectedImportAccountIds" class="agent-proposal-targets is-readonly">
                      <el-checkbox v-for="account in message.importProposal.availableAccounts || []" :key="account.id" :value="account.id" disabled>{{ account.platformName }} · {{ account.name }}</el-checkbox>
                    </el-checkbox-group>
                    <el-date-picker v-if="message.importProposal.status === 'pending' && message.importProposal.requiresSchedule" v-model="message.importScheduledAt" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="选择定时发布时间" class="agent-proposal-schedule" />
                    <el-date-picker v-else-if="message.importProposal.status === 'confirmed' && message.importProposal.requiresSchedule" v-model="message.importScheduledAt" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" class="agent-proposal-schedule" disabled />
                    <p v-if="message.importProposal.status === 'pending' && message.importProposal.scheduleNotice" class="agent-proposal-result">{{ message.importProposal.scheduleNotice }}</p>
                    <div v-if="message.importProposal.status === 'pending'" class="agent-proposal-action">
                      <el-button type="primary" size="small" :loading="message.importing" :disabled="!canConfirmAgentImport(message)" @click="confirmAgentImport(message)">
                        确认{{ message.importProposal.actionLabel || '导入' }} {{ (message.selectedCandidateIds || []).length }} 个线索
                      </el-button>
                    </div>
                    <p v-else-if="message.importProposal.status === 'expired'" class="agent-proposal-result">该确认已失效，请重新让 Agent 检索。</p>
                    <p v-if="message.importResult" class="agent-proposal-result">{{ message.importResult }}</p>
                  </section>
                  <section v-if="message.executionProposal" class="agent-proposal">
                    <div class="agent-proposal-title"><span>待确认操作</span><strong>{{ message.executionProposal.actionLabel }}</strong></div>
                    <p class="agent-proposal-description">{{ message.executionProposal.video?.title || '当前视频' }}</p>
                    <el-checkbox-group v-if="message.executionProposal.status === 'pending' && message.executionProposal.requiresTargets" v-model="message.selectedExecutionAccountIds" class="agent-proposal-targets" @change="normalizeExecutionAccountSelection(message)">
                      <el-checkbox v-for="account in message.executionProposal.availableAccounts || []" :key="account.id" :value="account.id">{{ account.platformName }} · {{ account.name }}</el-checkbox>
                    </el-checkbox-group>
                    <el-checkbox-group v-else-if="message.executionProposal.status === 'confirmed' && message.executionProposal.requiresTargets" v-model="message.selectedExecutionAccountIds" class="agent-proposal-targets is-readonly">
                      <el-checkbox v-for="account in message.executionProposal.availableAccounts || []" :key="account.id" :value="account.id" disabled>{{ account.platformName }} · {{ account.name }}</el-checkbox>
                    </el-checkbox-group>
                    <el-date-picker v-if="message.executionProposal.status === 'pending' && message.executionProposal.requiresSchedule" v-model="message.executionScheduledAt" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="选择发布时间" class="agent-proposal-schedule" />
                    <el-date-picker v-else-if="message.executionProposal.status === 'confirmed' && message.executionProposal.requiresSchedule" v-model="message.executionScheduledAt" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" class="agent-proposal-schedule" disabled />
                    <div v-if="message.executionProposal.status === 'pending'" class="agent-proposal-action">
                      <el-button type="primary" size="small" :loading="message.executing" :disabled="!canConfirmAgentExecution(message)" @click="confirmAgentExecution(message)">
                        确认{{ message.executionProposal.actionLabel }}
                      </el-button>
                    </div>
                    <p v-else-if="message.executionProposal.status === 'expired'" class="agent-proposal-result">该确认已失效，请重新让 Agent 生成提案。</p>
                    <p v-if="message.executionResult" class="agent-proposal-result">{{ message.executionResult }}</p>
                  </section>
                  <section v-if="message.agentTasks?.length" class="agent-task-progress">
                    <div class="agent-proposal-title"><span>任务进度</span><strong>{{ message.agentTasks.length }}</strong></div>
                    <div v-for="task in message.agentTasks" :key="task.id" class="agent-task-progress-item">
                      <div><strong>{{ task.title || task.videoId || '视频任务' }}</strong><span>{{ agentWorkflowStageLabel(task) }} · {{ agentWorkflowStatusLabel(task) }}</span></div>
                      <el-progress :percentage="Math.max(0, Math.min(100, task.progress || 0))" :status="task.status === 'failed' || task.status === 'abnormal' ? 'exception' : task.status === 'success' ? 'success' : ''" :stroke-width="5" />
                      <p :class="{ 'is-error': task.errorReason || task.status === 'failed' || task.status === 'abnormal' }">{{ task.errorReason || task.message }}</p>
                    </div>
                  </section>
                  <div v-if="message.actions?.length" class="agent-actions">
                    <el-button v-for="action in message.actions" :key="`${message.id}-${action.label}`" size="small" plain @click="confirmAgentAction(action)">{{ action.label }}</el-button>
                  </div>
                  <div v-if="showAgentMessageTools(message)" class="agent-message-tools">
                    <el-tooltip content="复制" placement="bottom">
                      <el-button text circle aria-label="复制消息" @click="copyAgentMessage(message)"><el-icon><DocumentCopy /></el-icon></el-button>
                    </el-tooltip>
                    <el-tooltip v-if="message.role === 'user' && !agentLoading" content="重试" placement="bottom">
                      <el-button text circle aria-label="重试问题" @click="prepareAgentRetry(message)"><el-icon><RefreshRight /></el-icon></el-button>
                    </el-tooltip>
                  </div>
                </div>
                <div v-if="agentMessages.length === 0" class="agent-empty">
                  <el-icon><ChatDotRound /></el-icon><strong>开始一个新对话</strong><span>询问当前视频工作流、账号状态或发布进度。</span>
                </div>
              </div>
              <div class="agent-input">
                <div v-if="agentSessionReadonly" class="agent-readonly-note">此会话由飞书端继续对话；网页端仅可查看。</div>
                <div v-if="agentVideoContext" class="agent-video-context" :class="{ 'is-disabled': !agentIncludeVideoContext }">
                  <el-checkbox v-model="agentIncludeVideoContext">视频上下文</el-checkbox>
                  <span :title="agentVideoContext.title">{{ agentVideoContext.title || '未命名视频' }}</span>
                  <el-tag size="small" effect="plain">{{ agentVideoContext.publishedPlatforms?.length || 0 }} 个平台</el-tag>
                </div>
                <div class="agent-composer">
                  <el-input ref="agentInputRef" v-model="agentInput" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="agentSessionReadonly" :placeholder="agentSessionReadonly ? '飞书会话仅可查看' : '询问视频采集、处理、素材或发布状态'" @keydown="handleAgentInputKeydown" />
                  <el-button class="agent-send-button" type="primary" :loading="agentLoading" :disabled="agentSessionReadonly || !agentInput.trim()" circle aria-label="发送" @click="sendAgentMessage()">
                    <el-icon><Promotion /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </section>
    <el-drawer
      v-model="agentDrawerVisible"
      direction="rtl"
      size="min(1120px, 96vw)"
      class="agent-drawer"
      append-to-body
      @open="openAgentWorkbench"
    >
      <template #header>
        <div class="agent-drawer-header">
          <div>
            <span class="agent-drawer-kicker">PROJECT AGENT</span>
            <strong>Vidferry Agent</strong>
          </div>
          <el-tag size="small" effect="plain" :type="agentConfigWarning ? 'warning' : 'success'">
            只读
          </el-tag>
          <el-tooltip content="历史会话" placement="bottom">
            <el-button text circle title="历史会话" aria-label="历史会话" @click="openAgentHistory">
              <el-icon><Clock /></el-icon>
            </el-button>
          </el-tooltip>
          <el-button text circle title="新建对话" aria-label="新建对话" @click="newAgentConversation">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="agent-workbench">
        <aside class="agent-session-sidebar">
          <el-button class="agent-new-session" type="primary" plain @click="newAgentConversation">
            <el-icon><Plus /></el-icon>
            新对话
          </el-button>
          <el-input
            v-model="agentHistoryQuery"
            class="agent-session-search"
            clearable
            placeholder="搜索会话"
            @keyup.enter="loadAgentHistory"
            @clear="loadAgentHistory"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-radio-group v-model="agentHistorySource" class="agent-source-filter" size="small" @change="loadAgentHistory">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="web">本地</el-radio-button>
            <el-radio-button label="feishu">手机</el-radio-button>
          </el-radio-group>
          <el-date-picker
            v-model="agentHistoryRange"
            class="agent-session-date"
            type="daterange"
            size="small"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            unlink-panels
            @change="loadAgentHistory"
          />
          <div class="agent-session-sidebar-title">
            <span>会话</span>
            <el-button text circle title="刷新会话" aria-label="刷新会话" :loading="agentHistoryLoading" @click="loadAgentHistory">
              <el-icon><RefreshRight /></el-icon>
            </el-button>
          </div>
          <el-scrollbar class="agent-session-list">
            <div v-if="!agentHistoryLoading && agentHistory.length === 0" class="agent-session-empty">暂无匹配会话</div>
            <div
              v-for="session in agentHistory"
              :key="session.id"
              class="agent-session-item"
              :class="{ 'is-current': session.id === agentSessionId }"
              @click="selectAgentSession(session)"
            >
              <div class="agent-session-item-main">
                <div class="agent-session-title-row">
                  <strong>{{ session.title || session.preview || 'Vidferry Agent' }}</strong>
                  <el-tag size="small" effect="plain" :type="session.source === 'feishu' ? 'success' : 'info'">
                    {{ session.source === 'feishu' ? '手机端' : '本地' }}
                  </el-tag>
                </div>
                <span>{{ session.preview || '暂无用户消息' }}</span>
                <small>{{ formatAgentSessionTime(session.updatedAt) }} · {{ session.messageCount || 0 }} 条</small>
              </div>
              <el-button text circle type="danger" title="删除会话" aria-label="删除会话" @click.stop="removeAgentSession(session)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </el-scrollbar>
        </aside>
        <div class="agent-panel">
        <div class="agent-context-card">
          <div class="agent-avatar">
            <el-icon><ChatDotRound /></el-icon>
          </div>
          <div class="agent-context-copy">
            <strong>只读项目管家</strong>
            <span>{{ agentContextLabel }} · {{ agentConfigWarning ? '等待视觉模型' : '在线' }}</span>
          </div>
          <el-tag size="small" effect="plain" :type="agentSessionSource === 'feishu' ? 'success' : 'info'">
            {{ agentSessionSourceLabel }}
          </el-tag>
        </div>
        <div v-if="agentSessionId" class="agent-context-status">
          <el-button text size="small" class="agent-context-toggle" @click="agentContextDetailsVisible = !agentContextDetailsVisible">
            {{ agentContextUsageLabel }} · {{ agentCurrentSession?.messageCount || 0 }} 条消息
          </el-button>
          <el-tooltip content="压缩上下文" placement="bottom">
            <el-button text circle size="small" aria-label="压缩上下文" :loading="agentCompaction.state === 'running'" @click="compactCurrentAgentSession">
              <el-icon><RefreshRight /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
        <div v-if="agentContextDetailsVisible && agentContextStats" class="agent-context-details">
          <span>预估输入 {{ agentContextStats.estimatedInputTokens }} tokens</span>
          <span>最近实际 {{ agentContextStats.lastPromptTokens || '暂无' }} tokens</span>
          <span>摘要覆盖至 #{{ agentContextStats.summaryThroughId || 0 }}</span>
          <span>自动压缩：{{ agentContextStats.compactAfterMessages }} 条或 {{ agentContextStats.compactAfterChars }} 字符</span>
        </div>
        <div v-if="agentCompaction.state !== 'idle'" class="agent-compaction-activity" :class="`is-${agentCompaction.state}`" aria-live="polite">
          <el-icon v-if="agentCompaction.state === 'running'" class="is-loading"><Loading /></el-icon>
          <span>{{ agentCompaction.message }}</span>
          <small>{{ agentCompactionElapsedSeconds }} 秒</small>
        </div>
        <div v-if="!agentSessionReadonly" class="agent-quick-panel">
          <div class="agent-section-title">快捷问题</div>
          <div class="agent-quick-actions">
            <el-button
              v-for="question in agentQuickQuestions"
              :key="question"
              size="small"
              plain
              @click="sendAgentMessage(question)"
            >
              {{ question }}
            </el-button>
          </div>
        </div>
        <div ref="agentMessagesRef" class="agent-messages" @scroll.passive="handleAgentMessagesScroll">
          <div v-if="agentOlderMessagesLoading" class="agent-older-loading" aria-live="polite">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>正在加载更早消息</span>
          </div>
          <div
            v-for="message in agentMessages"
            :key="message.id"
            class="agent-message"
            :class="`is-${message.role}`"
          >
            <div class="agent-message-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
            <div class="agent-message-content">
              <div v-if="message.thinking" class="agent-thinking" aria-live="polite">
                <el-icon class="agent-thinking-icon is-loading"><Loading /></el-icon>
                <span>{{ message.statusMessage || '正在思考' }}</span>
              </div>
              <span v-if="message.content">{{ message.content }}</span>
            </div>
            <div v-for="card in message.cards || []" :key="`${message.id}-${card.type}-${card.title}`" class="agent-result-card">
              <div class="agent-card-title"><span>{{ card.title }}</span><strong>{{ card.count }}</strong></div>
              <div v-for="item in card.items || []" :key="`${item.title}-${item.detail || item.status}`" class="agent-card-item">
                <strong>{{ item.title }}</strong>
                <span>{{ item.detail || item.channel || item.status }}</span>
              </div>
            </div>
            <div v-if="message.actions?.length" class="agent-actions">
              <el-button v-for="action in message.actions" :key="`${message.id}-${action.label}`" size="small" plain @click="confirmAgentAction(action)">{{ action.label }}</el-button>
            </div>
            <div v-if="showAgentMessageTools(message)" class="agent-message-tools">
              <el-tooltip content="复制" placement="bottom">
                <el-button text circle aria-label="复制消息" @click="copyAgentMessage(message)">
                  <el-icon><DocumentCopy /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip v-if="message.role === 'user' && !agentLoading" content="重试" placement="bottom">
                <el-button text circle aria-label="重试问题" @click="prepareAgentRetry(message)">
                  <el-icon><RefreshRight /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </div>
          <div v-if="agentMessages.length === 0" class="agent-empty">
            <el-icon><ChatDotRound /></el-icon>
            <strong>还没有对话</strong>
            <span>从一个快捷问题开始。</span>
          </div>
        </div>
        <div class="agent-input">
          <div v-if="agentSessionReadonly" class="agent-readonly-note">
            此会话由手机端继续对话；在飞书中发送消息或使用 /sessions、/use、/new 管理会话。
          </div>
          <div
            v-if="agentVideoContext"
            class="agent-video-context"
            :class="{ 'is-disabled': !agentIncludeVideoContext }"
          >
            <el-checkbox v-model="agentIncludeVideoContext">视频上下文</el-checkbox>
            <span :title="agentVideoContext.title">{{ agentVideoContext.title || '未命名视频' }}</span>
            <el-tag size="small" effect="plain">{{ agentVideoContext.publishedPlatforms?.length || 0 }} 个平台</el-tag>
          </div>
          <el-input
            ref="agentInputRef"
            v-model="agentInput"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            :disabled="agentSessionReadonly"
            :placeholder="agentSessionReadonly ? '手机端会话仅可查看' : (agentVideoContext && agentIncludeVideoContext ? '询问这个视频的发布或处理信息' : '例如：已处理但还没发布的视频有哪些？')"
            @keydown="handleAgentInputKeydown"
          />
          <el-button type="primary" :loading="agentLoading" :disabled="agentSessionReadonly" @click="sendAgentMessage()">
            发送
          </el-button>
        </div>
      </div>
      </div>
    </el-drawer>
    <el-dialog
      v-model="agentHistoryVisible"
      title="历史会话"
      width="min(560px, calc(100vw - 32px))"
      append-to-body
    >
      <div class="agent-history-toolbar">
        <span>{{ agentHistoryLoading ? '正在读取' : `共 ${agentHistory.length} 个会话` }}</span>
        <div class="agent-history-filter">
          <el-date-picker
            v-model="agentHistoryRange"
            type="daterange"
            size="small"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            unlink-panels
            @change="loadAgentHistory"
          />
          <el-button text type="primary" :loading="agentHistoryLoading" @click="loadAgentHistory">刷新</el-button>
        </div>
      </div>
      <el-empty v-if="!agentHistoryLoading && agentHistory.length === 0" description="暂无历史会话" :image-size="72" />
      <el-scrollbar v-else max-height="420px">
        <div class="agent-history-list">
          <div
            v-for="session in agentHistory"
            :key="session.id"
            class="agent-history-item"
            :class="{ 'is-current': session.id === agentSessionId }"
            @click="selectAgentSession(session)"
          >
            <div class="agent-history-item-main">
              <strong>{{ session.title || session.preview || 'Vidferry Agent' }}</strong>
              <span>{{ session.preview || '暂无用户消息' }}</span>
            </div>
            <div class="agent-history-item-meta">
              <span>{{ formatAgentSessionTime(session.updatedAt) }}</span>
              <span>{{ session.messageCount || 0 }} 条消息</span>
            </div>
            <el-button
              text
              circle
              type="danger"
              title="删除会话"
              aria-label="删除会话"
              @click.stop="removeAgentSession(session)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
      </el-scrollbar>
    </el-dialog>
</template>
<script setup>
import { reactive, toRefs } from 'vue'
import { ChatDotRound, Clock, Delete, DocumentCopy, Loading, Plus, Promotion, RefreshRight, Search } from '@element-plus/icons-vue'

const props = defineProps({
  workspace: { type: Object, required: true },
  showPage: { type: Boolean, default: false },
  agentConfigWarning: { type: String, default: '' },
  formatAgentSessionTime: { type: Function, required: true }
})

const {
  agentDrawerVisible, agentLoading, agentInput, agentSessionId, agentMessages, agentMessagesRef,
  agentOlderMessagesLoading, agentHasOlderMessages, agentMessagesBeforeId, agentSessionRestoreLoading,
  agentInputRef, agentRetryContext, agentVideoContext, agentIncludeVideoContext, agentHistoryVisible,
  agentHistoryLoading, agentHistory, agentHistoryRange, agentHistorySource, agentHistoryQuery,
  agentFiltersVisible, agentCurrentSession, agentContextStats, agentContextDetailsVisible, agentCompaction, agentContextUsageLabel, agentCompactionElapsedSeconds, agentSessionSource, agentSessionSourceLabel, agentSessionReadonly,
  agentQuickQuestions, workspaceTitle, currentAgentTitle, sortedAgentHistory, agentContextLabel, currentAgentContext,
  scrollAgentMessages, loadOlderAgentMessages, handleAgentMessagesScroll, newAgentConversation, startAgentConversation,
  sendAgentMessage, showAgentMessageTools, copyAgentMessage, loadAgentHistory, openAgentHistory, openAgentWorkbench,
  selectAgentSession, compactCurrentAgentSession, handleAgentSessionCommand, removeAgentSession, prepareAgentRetry, handleAgentInputKeydown,
  confirmAgentAction, handleAskAgentEvent,
  normalizeImportAccountSelection, canConfirmAgentImport, confirmAgentImport,
  normalizeExecutionAccountSelection, canConfirmAgentExecution, confirmAgentExecution,
  agentWorkflowStatusLabel, agentWorkflowStageLabel
} = toRefs(reactive(props.workspace))
</script>

<style scoped>
.agent-proposal {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.agent-proposal-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}

.agent-proposal-list,
.agent-proposal-targets {
  display: grid;
  gap: 6px;
  margin: 8px 0;
}

.agent-proposal-item {
  display: flex;
  min-width: 0;
}

.agent-proposal-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.agent-proposal-copy strong,
.agent-proposal-copy small,
.agent-proposal-description {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-proposal-copy small,
.agent-proposal-result {
  color: var(--el-text-color-secondary);
}

.agent-proposal-description,
.agent-proposal-result {
  margin: 0 0 8px;
  font-size: 12px;
}

.agent-proposal-schedule {
  width: 100%;
  margin: 0 0 8px;
}

.is-readonly {
  opacity: 0.7;
}

.agent-proposal-action {
  display: flex;
  width: 100%;
}

.agent-task-progress {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.agent-task-progress-item {
  display: grid;
  gap: 5px;
}

.agent-task-progress-item > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  font-size: 12px;
}

.agent-task-progress-item strong,
.agent-task-progress-item span,
.agent-task-progress-item p {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-task-progress-item span,
.agent-task-progress-item p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.agent-task-progress-item p.is-error {
  color: var(--el-color-danger);
}
</style>
