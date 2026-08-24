<template>
  <div class="youtube-research">
    <section class="workspace-hero">
      <div class="hero-copy">
        <span class="eyebrow">VIDFERRY PIPELINE</span>
        <h1>视频采集与处理</h1>
        <p>集中管理 YouTube 视频线索、处理进度和后续发布。</p>
      </div>
      <div class="metric-strip" aria-label="视频线索概览">
        <button
          v-for="stat in summaryStats"
          :key="stat.label"
          class="metric-card"
          :class="[stat.tone, { 'is-active': videoFilter.status === stat.filter }]"
          type="button"
          @click="setStatusFilter(stat.filter)"
        >
          <span class="metric-label">{{ stat.label }}</span>
          <strong>{{ stat.value }}</strong>
          <span class="metric-meta">{{ stat.meta }}</span>
        </button>
      </div>
    </section>

    <section class="pipeline-strip" aria-label="Vidferry 线索流水线">
      <div v-for="stage in pipelineStages" :key="stage.label" class="pipeline-stage">
        <div class="stage-icon">
          <el-icon><component :is="stage.icon" /></el-icon>
        </div>
        <div>
          <span class="stage-label">{{ stage.label }}</span>
          <strong>{{ stage.value }}</strong>
        </div>
      </div>
    </section>

    <el-card class="command-card" shadow="never">
      <div class="command-header">
        <div>
          <span class="panel-kicker">线索入口</span>
          <h2>导入与查询</h2>
        </div>
        <el-button :loading="jobsLoading" @click="loadJobs()">
          <el-icon><Refresh /></el-icon>
          <span>刷新任务</span>
        </el-button>
      </div>

      <el-form :model="form" label-position="top" class="command-grid">
        <div class="entry-panel import-panel">
          <div class="entry-heading">
            <el-icon><Link /></el-icon>
            <div>
              <h3>单条链接导入</h3>
              <span>适合已经明确要处理的视频</span>
            </div>
          </div>
          <div class="entry-control">
            <el-form-item label="YouTube 视频链接">
              <el-input
                v-model="manualForm.url"
                clearable
                placeholder="https://www.youtube.com/watch?v=..."
              />
            </el-form-item>
            <el-form-item label="目标分组" class="group-field">
              <VideoGroupSelect v-model="manualForm.groupId" />
            </el-form-item>
            <el-button type="success" :loading="importing" @click="importVideo">
              <el-icon><Link /></el-icon>
              <span>导入链接</span>
            </el-button>
          </div>
        </div>

        <div class="entry-panel search-panel">
          <div class="entry-heading">
            <el-icon><Search /></el-icon>
            <div>
              <h3>关键词批量查询</h3>
              <span>从 YouTube 搜索候选视频并入库</span>
            </div>
          </div>
          <div class="entry-control search-control">
            <el-form-item label="英文关键词" required class="keyword-field">
              <el-input
                v-model="form.query"
                clearable
                :disabled="searchLoading"
                placeholder="输入英文 YouTube 检索关键词"
                @change="persistSearchQuery"
              />
            </el-form-item>
            <el-form-item label="目标分组" class="group-field">
              <VideoGroupSelect v-model="form.groupId" :disabled="searchLoading" />
            </el-form-item>
            <el-form-item label="数量" required class="limit-field">
              <el-input-number v-model="form.limit" :min="1" :max="30" :disabled="searchLoading" controls-position="right" />
            </el-form-item>
            <el-button type="primary" :loading="searchLoading" @click="handleSearch">
              <el-icon><Search /></el-icon>
              <span>开始查询</span>
            </el-button>
          </div>
          <div class="keyword-presets" aria-label="关键词预设">
            <span class="keyword-presets-label">常用预设</span>
            <el-button
              v-for="preset in keywordPresets"
              :key="preset.query"
              size="small"
              :type="form.query === preset.query ? 'primary' : 'default'"
              plain
              :disabled="searchLoading"
              @click="applyKeywordPreset(preset.query)"
            >
              {{ preset.label }}
            </el-button>
          </div>
          <div v-if="searchProgress.visible" class="search-progress-panel">
            <div class="search-progress-text">
              <span>{{ searchProgress.message }}</span>
              <strong>{{ searchProgressSummary }}</strong>
            </div>
            <el-progress :percentage="searchProgressPercent" :stroke-width="8" :status="searchProgressStatus" />
          </div>
        </div>
      </el-form>

      <div class="workflow-config">
        <div class="config-title">
          <span class="panel-kicker">处理任务发布配置</span>
          <span>一键处理任务时选择发布平台和账号</span>
        </div>
        <div class="publish-config-controls">
          <div class="account-group-config">
            <el-select v-model="workflowForm.publishAccountGroupId" clearable filterable placeholder="选择发布账号组" @change="applyPublishAccountGroup">
              <el-option v-for="group in publishAccountGroups" :key="group.id" :label="group.complete ? group.name : `${group.name}（配置不完整）`" :value="group.id" :disabled="!group.complete" />
            </el-select>
            <el-button size="small" @click="router.push('/account-management')">管理账号组</el-button>
            <span v-if="workflowForm.publishAccountGroupId" class="config-group-hint">已按账号组填充；修改平台或账号后将使用自定义配置。</span>
          </div>
          <div class="publish-platform-row" aria-label="选择发布平台">
            <span class="publish-platform-label">发布平台</span>
            <div class="publish-platform-switches">
          <label class="config-item">
            <span>发抖音</span>
            <el-switch v-model="workflowForm.publishToDouyin" />
          </label>
          <label class="config-item">
            <span>发B站</span>
            <el-switch v-model="workflowForm.publishToBilibili" />
          </label>
          <label class="config-item">
            <span>发小红书</span>
            <el-switch v-model="workflowForm.publishToXiaohongshu" />
          </label>
          <label class="config-item">
            <span>发快手</span>
            <el-switch v-model="workflowForm.publishToKuaishou" />
          </label>
          <label class="config-item">
            <span>发视频号</span>
            <el-switch v-model="workflowForm.publishToTencent" />
          </label>
            </div>
          </div>
          <div class="publish-account-fields">
          <el-select
            v-if="workflowForm.publishToDouyin"
            v-model="workflowForm.account"
            class="compact-input"
            clearable
            filterable
            placeholder="选择抖音账号"
          >
            <el-option
              v-for="account in normalAccountsByPlatform('抖音')"
              :key="account.id"
              :label="account.name"
              :value="account.name"
            />
          </el-select>
          <el-select
            v-if="workflowForm.publishToBilibili"
            v-model="workflowForm.bilibiliAccount"
            class="compact-input"
            clearable
            filterable
            placeholder="选择B站账号"
          >
            <el-option
              v-for="account in normalAccountsByPlatform('B站')"
              :key="account.id"
              :label="account.name"
              :value="account.name"
            />
          </el-select>
          <el-select
            v-if="workflowForm.publishToBilibili"
            v-model="workflowForm.bilibiliTid"
            class="tid-input"
            filterable
            placeholder="B站分区"
          >
            <el-option
              v-for="category in bilibiliCategories"
              :key="category.tid"
              :label="`${category.label}（${category.tid}）`"
              :value="category.tid"
            />
            <el-option
              v-if="isUnknownBilibiliTid(workflowForm.bilibiliTid)"
              :label="`未知分区（${workflowForm.bilibiliTid}）`"
              :value="workflowForm.bilibiliTid"
            />
          </el-select>
          <el-select
            v-if="workflowForm.publishToXiaohongshu"
            v-model="workflowForm.xiaohongshuAccount"
            class="compact-input"
            clearable
            filterable
            placeholder="选择小红书账号"
          >
            <el-option
              v-for="account in normalAccountsByPlatform('小红书')"
              :key="account.id"
              :label="account.name"
              :value="account.name"
            />
          </el-select>
          <el-select
            v-if="workflowForm.publishToKuaishou"
            v-model="workflowForm.kuaishouAccount"
            class="compact-input"
            clearable
            filterable
            placeholder="选择快手账号"
          >
            <el-option
              v-for="account in normalAccountsByPlatform('快手')"
              :key="account.id"
              :label="account.name"
              :value="account.name"
            />
          </el-select>
          <el-select
            v-if="workflowForm.publishToTencent"
            v-model="workflowForm.tencentAccount"
            class="compact-input"
            clearable
            filterable
            placeholder="选择视频号账号"
          >
            <el-option
              v-for="account in normalAccountsByPlatform('视频号')"
              :key="account.id"
              :label="account.name"
              :value="account.name"
            />
          </el-select>
          </div>
        </div>
      </div>

      <div class="query-meta" v-if="lastResult">
        <span>来源：{{ lastResult.source }}</span>
        <span>查询时间：{{ lastResult.searchedAt }}</span>
        <span>入库/更新：{{ lastResult.total }}</span>
      </div>
    </el-card>

    <el-card ref="videoListSectionRef" class="result-card data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">{{ historyMode ? '历史线索' : '线索列表' }}</span>
            <h2>{{ historyMode ? '已清理本地文件的视频' : '候选视频' }}</h2>
          </div>
          <div class="list-tools">
            <el-button size="small" :icon="Clock" @click="toggleHistoryMode">
              {{ historyMode ? '返回线索列表' : '历史线索' }}
            </el-button>
            <el-button size="small" :icon="Refresh" :loading="retentionScanning" @click="scanLocalRetention">
              扫描本地留存
            </el-button>
            <el-input
              v-model="videoFilter.keyword"
              class="video-keyword-filter"
              size="small"
              clearable
              :prefix-icon="Search"
              placeholder="搜索原标题或发布标题"
              aria-label="搜索原标题或发布标题"
            />
            <VideoGroupSelect v-model="videoFilter.groupId" include-all class="group-filter" />
            <el-button size="small" :icon="Setting" title="管理线索分组" @click="groupManagerVisible = true" />
            <el-dropdown :disabled="historyMode || selectedVideos.length === 0" @command="moveSelectedVideos">
              <el-button size="small" type="primary" plain :disabled="historyMode || selectedVideos.length === 0">
                移动到分组 {{ selectedVideos.length || '' }}
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="group in videoGroupStore.groups" :key="group.id" :command="group.id">{{ group.name }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="historyMode || selectedVideos.length === 0"
              :loading="batchDeleting"
              @click="batchDeleteVideos"
            >
              批量删除 {{ selectedVideos.length || '' }}
            </el-button>
            <el-select v-model="videoFilter.status" class="status-select" size="small" aria-label="显示状态">
              <el-option label="全部状态" value="all" />
              <el-option label="初始线索" value="initial" />
              <el-option label="已下载" value="downloaded" />
              <el-option label="已处理" value="processed" />
              <el-option label="已发布" value="published" />
              <el-option label="运行中" value="running" />
              <el-option label="任务失败" value="failed" />
              <el-option label="任务异常" value="abnormal" />
              <el-option label="已跳过处理" value="translationSkipped" />
            </el-select>
            <el-select v-model="videoFilter.sort" class="sort-select" size="small" aria-label="排序方式">
              <el-option label="默认顺序" value="default" />
              <el-option label="导入时间最近" value="importedNewest" />
              <el-option label="导入时间最远" value="importedOldest" />
              <el-option label="发布时间最新" value="publishedNewest" />
              <el-option label="视频时长最短" value="durationShortest" />
              <el-option label="状态完成度" value="stageProgress" />
            </el-select>
            <span class="panel-count">第 {{ videoPagination.page }} 页 · {{ items.length }} / {{ videoTotal }} 条</span>
          </div>
        </div>
      </template>

      <el-alert
        v-if="historyMode"
        title="这些视频已发布且本地媒体文件已清理；数据库记录、处理记录和发布台账仍会保留。重新下载或处理后可再次发布。"
        type="info"
        :closable="false"
        show-icon
        class="history-leads-alert"
      />

      <el-table
        :data="items"
        v-loading="loading"
        empty-text="暂无匹配的视频记录"
        class="research-table"
        style="width: 100%"
        ref="videoTableRef"
        row-key="id"
        @selection-change="handleVideoSelectionChange"
      >
        <el-table-column type="selection" width="44" :reserve-selection="true" />
        <el-table-column label="视频" min-width="340">
          <template #default="{ row }">
            <div class="video-cell">
              <img v-if="videoThumbnail(row)" :src="videoThumbnail(row)" alt="" class="thumbnail">
              <div v-else class="thumbnail thumbnail-empty">
                <el-icon><VideoCamera /></el-icon>
              </div>
              <div class="video-info">
                <div class="title-line">
                  <button
                    v-if="stageErrorJob(row)"
                    type="button"
                    class="stage-badge stage-badge-button"
                    :class="currentStage(row).className"
                    @click="showJobErrorDetails(row)"
                  >
                    {{ currentStage(row).label }}
                  </button>
                  <span v-else class="stage-badge" :class="currentStage(row).className">{{ currentStage(row).label }}</span>
                  <el-tag
                    v-if="row.analysisResult?.contentRisk?.requiresPublishConfirmation"
                    size="small"
                    type="warning"
                    effect="light"
                  >
                    发布需确认
                  </el-tag>
                  <el-tag size="small" effect="plain" type="info">{{ row.groupName || '未分类' }}</el-tag>
                  <div class="video-title-stack">
                    <a :href="row.url" :title="row.title || '未获取到标题'" target="_blank" rel="noopener noreferrer" class="video-title">
                      {{ row.chineseTitle || row.title || '未获取到标题' }}
                    </a>
                    <span
                      v-if="row.chineseTitle && row.title && row.chineseTitle !== row.title"
                      class="video-original-title"
                      :title="row.title"
                    >
                      {{ row.title }}
                    </span>
                  </div>
                  <el-button
                    class="video-detail-trigger"
                    text
                    circle
                    aria-label="查看视频详情"
                    title="查看视频详情"
                    @click="showVideoDetails(row)"
                  >
                    <el-icon><InfoFilled /></el-icon>
                  </el-button>
                </div>
                <div class="video-meta">
                  <span>{{ row.channel || '未知博主' }}</span>
                  <span>{{ row.subscribers || '粉丝数未知' }}</span>
                  <span>{{ row.publishedAt || '发布时间未知' }}</span>
                  <span>{{ row.duration || '时长未知' }}</span>
                </div>
                <div class="workflow-track" aria-label="视频处理流程">
                  <span
                    v-for="step in rowWorkflowSteps(row)"
                    :key="step.key"
                    class="workflow-step"
                    :class="step.className"
                  >
                    <span class="step-dot"></span>
                    <span>{{ step.label }}</span>
                  </span>
                </div>
                <div v-if="processedVersionBadges(row).length" class="processed-version-row">
                  <span>已生成</span>
                  <el-tag
                    v-for="version in processedVersionBadges(row)"
                    :key="version.key"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    {{ version.label }}
                  </el-tag>
                </div>
                <div v-if="row.publishedPlatforms?.length" class="processed-version-row published-platform-row">
                  <span>已发布</span>
                  <el-tag
                    v-for="platform in row.publishedPlatforms"
                    :key="platform.recordId || platform.type"
                    size="small"
                    type="success"
                    effect="plain"
                      :closable="Boolean(platform.recordId) && !['confirmed', 'reused'].includes(platform.status)"
                    @close="deletePublishedPlatform(row, platform)"
                  >
                    {{ platform.name }}
                  </el-tag>
                </div>
                <div v-if="unresolvedPublishTargets(row).length" class="processed-version-row published-platform-row">
                  <span>{{ row.publishDelivery?.statusLabel || '发布状态' }}</span>
                  <el-tag
                    v-for="target in unresolvedPublishTargets(row)"
                    :key="target.recordId || target.type"
                    size="small"
                    :type="publishTargetTagType(target.status)"
                    effect="plain"
                  >
                    {{ target.name }} · {{ publishTargetStatusText(target.status) }}
                  </el-tag>
                </div>
                <div v-if="activeJobForVideo(row)" class="inline-job">
                  <el-progress :percentage="displayProgress(activeJobForVideo(row))" :stroke-width="6" />
                  <span class="inline-job-status" :title="workflowProgressText(activeJobForVideo(row))">{{ workflowProgressText(activeJobForVideo(row)) }}</span>
                  <el-popover placement="bottom-start" trigger="click" width="360">
                    <div class="processing-settings-popover">
                      <strong>本次处理设置</strong>
                      <dl>
                        <template v-for="item in processingSettingsRows(activeJobForVideo(row))" :key="item.label">
                          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
                        </template>
                      </dl>
                    </div>
                    <template #reference>
                      <el-button class="processing-settings-trigger" text circle aria-label="查看本次处理设置" title="查看本次处理设置">
                        <el-icon><InfoFilled /></el-icon>
                      </el-button>
                    </template>
                  </el-popover>
                </div>
                <div v-else-if="analysisHint(row)" class="analysis-hint" :class="analysisHint(row).className">
                  <span>{{ analysisHint(row).label }}</span>
                  <el-button
                    v-if="canPreviewProcessedVideo(row)"
                    size="small"
                    text
                    :loading="previewLoadingId === row.id"
                    title="预览处理后视频"
                    @click="previewProcessedVideo(row)"
                  >
                    <el-icon><VideoPlay /></el-icon>
                    <span>预览成品</span>
                  </el-button>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="发布文案" min-width="340">
          <template #default="{ row }">
            <div
              v-if="showInlinePublishDraft(row)"
              class="publish-draft-card"
              :class="{ 'is-editing': isPublishDraftEditing(row) }"
            >
              <template v-if="isPublishDraftEditing(row)">
                <div class="draft-editor-grid">
                  <div class="draft-editor-primary">
                    <div class="draft-row">
                      <div class="draft-field-label"><span>标题</span><small>用于平台发布</small></div>
                      <el-select :model-value="publishDraftForm(row).customTitleEnabled ? CUSTOM_TITLE_VALUE : publishDraftForm(row).selectedTitle" placeholder="选择发布标题" filterable @change="handleTitleOptionChange(row, $event)">
                        <el-option v-for="title in publishDraftForm(row).titleOptions" :key="title" :label="title" :value="title" />
                        <el-option :label="publishDraftForm(row).selectedTitle || '自定义标题'" :value="CUSTOM_TITLE_VALUE" />
                      </el-select>
                    </div>
                    <div class="draft-row">
                      <div class="draft-field-label"><span>封面标题</span><small>最多两行，用于封面片头</small></div>
                      <div class="cover-title-fields">
                        <el-select :model-value="publishDraftForm(row).customCoverTitleEnabled ? CUSTOM_COVER_TITLE_VALUE : publishDraftForm(row).coverTitle" placeholder="选择封面标题" @change="handleCoverTitleOptionChange(row, $event)">
                          <el-option v-for="title in publishDraftForm(row).coverTitleOptions" :key="title" :label="coverTitleOptionLabel(title)" :value="title" />
                          <el-option label="自定义封面标题" :value="CUSTOM_COVER_TITLE_VALUE" />
                        </el-select>
                        <el-input v-if="publishDraftForm(row).customCoverTitleEnabled" v-model="publishDraftForm(row).coverTitle" type="textarea" :rows="2" maxlength="25" show-word-limit placeholder="请输入两行短标题，用换行分隔" />
                      </div>
                    </div>
                    <div class="draft-row">
                      <div class="draft-field-label"><span>自动标签</span><small>选择候选或删除已选标签</small></div>
                      <el-select v-model="publishDraftForm(row).tags" multiple filterable default-first-option reserve-keyword placeholder="选择候选话题" @change="normalizeDraftTopics(publishDraftForm(row))">
                        <el-option v-for="tag in publishDraftForm(row).tagOptions" :key="tag" :label="tag" :value="tag" />
                      </el-select>
                    </div>
                    <div class="draft-row">
                      <div class="draft-field-label"><span>本视频自定义话题</span></div>
                      <div class="tag-cloud">
                        <el-tag v-for="tag in publishDraftForm(row).customTags" :key="tag" closable @close="removeDraftCustomTag(row, tag)">#{{ tag }}</el-tag>
                        <span v-if="publishDraftForm(row).customTags.length === 0" class="empty-topic">暂无自定义话题</span>
                      </div>
                      <div class="topic-add-row">
                        <el-input
                          v-model="publishDraftForm(row).newTag"
                          placeholder="输入自定义话题"
                          clearable
                          @keyup.enter.prevent="addDraftTag(row)"
                        />
                        <el-button type="primary" plain @click="addDraftTag(row)">
                          <el-icon><Plus /></el-icon>
                          <span>新增话题</span>
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <div class="draft-description-panel">
                    <div class="draft-field-label"><span>描述</span><small>发布时展示给观众的正文</small></div>
                    <el-input v-model="publishDraftForm(row).publishCopy" type="textarea" :rows="8" maxlength="500" show-word-limit />
                  </div>
                </div>
              </template>
              <template v-else>
                <div class="draft-readonly draft-readonly-compact">
                  <div class="draft-summary">
                    <span class="draft-label">发布文案</span>
                    <strong>{{ row.analysisDraft.selectedTitle || row.analysisDraft.coverTitle || '已生成' }}</strong>
                    <span v-if="row.analysisDraft.tags?.length || row.analysisDraft.customTags?.length" class="draft-summary-tags">{{ row.analysisDraft.tags.length + row.analysisDraft.customTags.length }} 个话题</span>
                  </div>
                  <span class="draft-summary-copy">{{ row.analysisDraft.publishCopy || '暂无发布文案' }}</span>
                </div>
              </template>
              <div class="draft-actions">
                <el-button v-if="isPublishDraftEditing(row)" size="small" type="primary" text :loading="savingAnalysisId === row.id" @click="saveInlineAnalysis(row)">保存修改</el-button>
                <el-button v-else size="small" type="primary" text @click="startPublishDraftEditing(row)">编辑文案</el-button>
                <el-button v-if="isPublishDraftEditing(row)" size="small" text @click="cancelPublishDraftEditing(row)">取消</el-button>
                <el-button size="small" text @click="showAnalysis(row)">查看详情</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300">
          <template #default="{ row }">
            <div class="action-row">
              <el-button
                v-if="row.downloadStatus !== 1"
                size="small"
                type="primary"
                :loading="downloadingId === row.id"
                @click="downloadVideo(row)"
              >
                <el-icon><Download /></el-icon>
                <span>下载</span>
              </el-button>
              <el-tooltip
                v-if="row.downloadStatus === 1"
                :content="processingActionStatusText(row)"
                placement="top"
                :disabled="!processingActionStatusText(row)"
              >
                <el-button
                  v-if="row.downloadStatus === 1"
                  size="small"
                  type="warning"
                  :disabled="row.downloadStatus !== 1"
                  :loading="translatingId === row.id"
                  @click="needsEditingIntroUpdate(row) || needsCoverReburn(row) ? updateEditingIntro(row) : processVideo(row)"
                >
                  <el-icon><VideoCamera /></el-icon>
                  <span>{{ needsEditingIntroUpdate(row) ? '更新片头高光' : (needsCoverReburn(row) ? '重新烧制封面' : (hasCurrentProcessVersion(row) ? '重新处理' : '处理')) }}</span>
                </el-button>
              </el-tooltip>
              <el-button
                size="small"
                type="success"
                plain
                :loading="creatingJobId === row.id"
                @click="createJob(row)"
              >
                <el-icon><VideoPlay /></el-icon>
                <span>一键发布</span>
              </el-button>
              <el-dropdown trigger="click">
                <el-button size="small" text class="more-button">
                  更多
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="askAgentAboutVideo(row)">
                      <el-icon><ChatDotRound /></el-icon>
                      <span>交给 Agent</span>
                    </el-dropdown-item>
                    <el-dropdown-item @click="copyUrl(row.url)">
                      <el-icon><DocumentCopy /></el-icon>
                      <span>复制链接</span>
                    </el-dropdown-item>
                    <el-dropdown-item @click="handleAnalysisAction(row)">
                      <el-icon><VideoPlay /></el-icon>
                      <span v-if="analyzingId === row.id">生成中</span>
                      <span v-else>{{ analysisActionText(row) }}</span>
                    </el-dropdown-item>
                    <el-dropdown-item v-if="row.processedVersions?.length" :disabled="analyzingId === row.id || Number(row.analysisStatus) === 2" @click="regenerateAnalysis(row)">
                      <el-icon><Refresh /></el-icon>
                      <span>重新生成文案</span>
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-if="Number(row.translateStatus) === 1 || Number(row.translateStatus) === 2"
                      @click="resetProcessing(row)"
                    >
                      <el-icon><Refresh /></el-icon>
                      <span>{{ resettingId === row.id ? '回退中' : '重新处理' }}</span>
                    </el-dropdown-item>
                    <el-dropdown-item @click="openMoveVideoDialog(row)">
                      <el-icon><Folder /></el-icon>
                      <span>移动到分组</span>
                    </el-dropdown-item>
                    <el-dropdown-item class="danger-item" @click="deleteVideo(row)">
                      <el-icon><Delete /></el-icon>
                      <span>{{ deletingId === row.id ? '删除中' : '删除线索' }}</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-pagination" v-if="videoTotal > videoPagination.pageSize">
        <el-pagination
          v-model:current-page="videoPagination.page"
          :page-size="videoPagination.pageSize"
          :total="videoTotal"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>

    <el-dialog
      v-model="settingsDialogVisible"
      title="设置"
      width="920px"
      class="process-settings-dialog"
    >
      <div class="settings-panel">
        <el-tabs v-model="settingsTab" class="process-settings-tabs">
          <el-tab-pane label="处理方案" name="processing">
            <div class="settings-section settings-grid">
              <div class="settings-field">
                <span class="settings-label">字幕语言</span>
                <el-select v-model="workflowForm.subtitleLanguage" class="process-version-select">
                  <el-option v-for="language in subtitleLanguages" :key="language.value" :label="language.label" :value="language.value" />
                </el-select>
              </div>
              <div class="settings-field">
                <span class="settings-label">处理版本</span>
                <el-select v-model="workflowForm.processVersion" class="process-version-select">
                  <el-option v-for="version in processVersions" :key="version.value" :label="version.label" :value="version.value" />
                </el-select>
              </div>
              <div class="version-note settings-span-full">
                <strong>{{ currentProcessVersion.label }}</strong>
                <span>{{ currentProcessVersion.description }}</span>
              </div>
              <div class="setting-status settings-span-full">
                当前字幕输出：{{ workflowForm.subtitleMode === 'auto' ? '自动判断' : (workflowForm.subtitleMode === 'original' ? '保留原字幕' : currentSubtitleLanguage.label) }}
              </div>
              <div v-if="workflowForm.processVersion === 'editing_v1'" class="settings-field">
                <span class="settings-label">高光片段条数</span>
                <el-select v-model="workflowForm.highlightCount" class="process-version-select">
                  <el-option :value="1" label="1 条" />
                  <el-option :value="2" label="2 条" />
                  <el-option :value="3" label="3 条" />
                </el-select>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="字幕与输出" name="output">
            <div class="settings-section settings-grid">
              <div class="settings-field">
                <span class="settings-label">烧录预设</span>
                <el-select v-model="workflowForm.burnProfile" class="process-version-select">
                  <el-option v-for="profile in burnProfiles" :key="profile.value" :label="profile.label" :value="profile.value" />
                </el-select>
              </div>
              <div class="settings-field">
                <span class="settings-label">字幕字号</span>
                <el-select v-model="workflowForm.subtitleSize" class="process-version-select">
                  <el-option v-for="size in subtitleSizes" :key="size.value" :label="size.label" :value="size.value" />
                </el-select>
              </div>
              <div class="settings-field settings-span-full">
                <span class="settings-label">翻译署名</span>
                <el-input v-model="workflowForm.translatorLabel" :disabled="workflowForm.subtitleMode === 'original'" maxlength="20" show-word-limit placeholder="例如：AI 中文字幕" />
              </div>
              <div class="version-note settings-span-full">
                <div class="version-note-title">
                  <strong>{{ currentBurnProfile.label }}</strong>
                  <el-popover placement="bottom-start" trigger="click" width="340">
                    <div class="profile-popover">
                      <p>{{ currentBurnProfile.description }}</p>
                      <dl>
                        <template v-for="param in currentBurnProfile.params" :key="param.name">
                          <dt>{{ param.name }}：{{ param.value }}</dt>
                          <dd>{{ param.description }}</dd>
                        </template>
                      </dl>
                    </div>
                    <template #reference>
                      <el-button class="param-info-button" text circle aria-label="查看编码预设参数">
                        <el-icon><InfoFilled /></el-icon>
                      </el-button>
                    </template>
                  </el-popover>
                </div>
                <span>{{ currentSubtitleSize.description }}</span>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="翻译与拼接" name="assembly">
            <div class="settings-section watermark-settings">
              <div class="watermark-switch-row">
                <div>
                  <span class="settings-label">字幕模式</span>
                  <span class="setting-hint">检测到非中文原字幕时默认遮挡后烧制；中文原字幕保留，无原字幕时直接烧制</span>
                </div>
                <el-radio-group v-model="workflowForm.subtitleMode"><el-radio-button value="auto" :disabled="!subtitleMaskAvailable">自动适配</el-radio-button><el-radio-button value="force_burn">强制烧制</el-radio-button><el-radio-button value="original">原字幕</el-radio-button></el-radio-group>
              </div>
              <div v-if="workflowForm.subtitleMode === 'force_burn'" class="watermark-switch-row">
                <div>
                  <span class="settings-label">遮挡原视频字幕</span>
                  <span class="setting-hint">{{ subtitleMaskAvailable ? '固定遮挡底部字幕区并用强模糊细颗粒马赛克覆盖，新字幕位于上层' : '已启用自定义字幕命令，字幕遮挡不可用' }}</span>
                </div>
                <el-switch v-model="workflowForm.subtitleMaskEnabled" :disabled="!subtitleMaskAvailable" />
              </div>
              <div class="watermark-switch-row">
                <div>
                  <span class="settings-label">广告风险审查</span>
                  <span class="setting-hint">ASR 后检测连续站外推广，命中后等待管理员裁剪确认</span>
                </div>
                <el-switch v-model="workflowForm.contentSafetyReviewEnabled" />
              </div>
              <div class="watermark-switch-row">
                <div>
                  <span class="settings-label">拼接高光片段</span>
                  <span class="setting-hint">仅处理版本二生效，在正片前加入高光片段</span>
                </div>
                <el-switch v-model="workflowForm.highlightIntroEnabled" />
              </div>
              <div class="watermark-switch-row">
                <div>
                  <span class="settings-label">拼接封面图片</span>
                  <span class="setting-hint">仅处理版本二生效，在正片前加入封面片头</span>
                </div>
                <el-switch v-model="workflowForm.coverIntroEnabled" />
              </div>
              <div v-if="workflowForm.processVersion === 'editing_v1'" class="watermark-switch-row">
                <div>
                  <span class="settings-label">烧制评论</span>
                  <span class="setting-hint">{{ commentBurnAvailable ? '获取热门评论并筛选翻译，从正片第 25 秒开始显示' : '已启用自定义字幕命令，评论烧制不可用' }}</span>
                </div>
                <el-switch v-model="workflowForm.commentBurnEnabled" :disabled="!commentBurnAvailable" />
              </div>
              <div v-if="workflowForm.processVersion === 'editing_v1' && workflowForm.commentBurnEnabled" class="watermark-switch-row">
                <div>
                  <span class="settings-label">评论烧制数量</span>
                  <span class="setting-hint">最多烧制的评论数，实际数量受合格评论和视频时长限制</span>
                </div>
                <el-select v-model="workflowForm.commentBurnCount" class="process-version-select" aria-label="评论烧制数量">
                  <el-option v-for="count in [20, 25, 30, 35, 40, 45, 50]" :key="count" :value="count" :label="`${count} 条`" />
                </el-select>
              </div>
              <div v-if="workflowForm.processVersion === 'editing_v1' && workflowForm.commentBurnEnabled" class="watermark-switch-row">
                <div>
                  <span class="settings-label">评论翻译</span>
                  <span class="setting-hint">非中文评论先初译，再按所选模式修订</span>
                </div>
                <el-radio-group v-model="workflowForm.commentTranslationMode" size="small" aria-label="评论翻译模式">
                  <el-radio-button label="google_llm">Google 初译 + LLM 修订</el-radio-button>
                  <el-radio-button label="google">Google 初译</el-radio-button>
                </el-radio-group>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="封面片头" name="cover">
            <div class="settings-section settings-grid cover-settings">
              <div class="settings-field">
                <span class="settings-label">封面署名</span>
                <el-input v-model="workflowForm.coverSignature" maxlength="24" show-word-limit placeholder="Vidferry" />
              </div>
              <div class="cover-signature-preview settings-span-full">
                <span>{{ workflowForm.coverSignature || 'Vidferry' }}</span>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="水印标识" name="watermark">
            <div class="settings-section watermark-settings">
              <div class="watermark-switch-row">
                <div>
                  <span class="settings-label">启用水印</span>
                  <span class="setting-hint">整段视频右上角持续显示</span>
                </div>
                <el-switch v-model="workflowForm.watermarkEnabled" @change="flushWorkflowSettings" />
              </div>
              <div class="settings-field">
                <span class="settings-label">水印内容</span>
                <el-input
                  v-model="workflowForm.watermarkText"
                  :disabled="!workflowForm.watermarkEnabled"
                  minlength="2"
                  maxlength="16"
                  show-word-limit
                  placeholder="留空时使用 Vidferry；填写 2-16 个字符"
                  @change="normalizeWatermarkText"
                />
              </div>
              <div class="watermark-preview" :class="{ 'is-muted': !workflowForm.watermarkEnabled }">
                <span>{{ workflowForm.watermarkText || 'Vidferry' }}</span>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button type="primary" @click="settingsDialogVisible = false">完成</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="analysisDialogVisible"
      title="发布文案与内容分析"
      width="min(920px, calc(100vw - 32px))"
      class="analysis-dialog"
    >
      <div v-loading="analysisLoading" class="analysis-panel">
        <template v-if="analysisStatus === 3">
          <el-alert
            title="内容分析失败"
            :description="analysisErrorText"
            type="warning"
            :closable="false"
            show-icon
          />
        </template>
        <template v-else-if="analysisResult">
          <div class="analysis-section">
            <span class="panel-kicker">内容视角</span>
            <h3>视频总结</h3>
            <p>{{ analysisResult.summary || '暂无总结' }}</p>
            <p v-if="analysisResult.china_view_angle" class="analysis-muted">{{ analysisResult.china_view_angle }}</p>
          </div>

          <div class="analysis-section">
            <div class="analysis-title-row">
              <div>
                <span class="panel-kicker">发布辅助</span>
                <h3>标题与文案</h3>
              </div>
              <el-button size="small" @click="copyText(analysisResult.publish_copy || '')">复制文案</el-button>
            </div>
            <div class="title-options">
              <el-tag
                v-for="title in analysisResult.title_options || []"
                :key="title"
                effect="plain"
              >
                {{ title }}
              </el-tag>
            </div>
            <div v-if="(analysisResult.cover_title_options || []).length" class="cover-analysis-preview">
              <span class="draft-label">封面标题</span>
              <p v-for="title in analysisResult.cover_title_options" :key="title" class="cover-draft-value">{{ title }}</p>
            </div>
            <p class="publish-copy">{{ analysisResult.publish_copy || '暂无文案' }}</p>
            <div class="tag-list">
              <el-tag v-for="tag in analysisResult.tags || []" :key="tag" type="success" effect="light">#{{ tag }}</el-tag>
              <el-button size="small" text type="primary" @click="copyText((analysisResult.tags || []).map(tag => `#${tag}`).join(' '))">复制标签</el-button>
            </div>
          </div>

          <div class="analysis-section">
            <span class="panel-kicker">高光片段</span>
            <h3>主题高光与核心看点</h3>
            <div class="highlight-list">
              <div
                v-for="segment in highlightCandidates"
                :key="segment.candidateId || `${segment.start}-${segment.end}-${segment.suggested_caption}`"
                class="highlight-item"
                :class="{ 'is-selected': highlightSelection(segment).selected }"
              >
                <div class="highlight-time">{{ formatSegmentRange(segment) }}</div>
                <div class="highlight-body">
                  <div class="highlight-heading">
                    <strong>{{ segment.suggested_caption || '建议字幕条待补充' }}</strong>
                    <div v-if="highlightSelection(segment).selected" class="highlight-markers">
                      <el-tag size="small" type="success" effect="light">已选拼接</el-tag>
                      <el-tag v-if="highlightSelection(segment).adjusted" size="small" type="warning" effect="light">已修订</el-tag>
                    </div>
                  </div>
                  <p>{{ segment.reason || '暂无理由' }}</p>
                  <div class="highlight-markers">
                    <el-tag v-if="highlightShortlist(segment).selected" size="small" type="primary" effect="light">文本初选 #{{ highlightShortlist(segment).rank }}</el-tag>
                    <el-tag v-if="highlightSelection(segment).score !== null" size="small" type="warning" effect="light">视觉 {{ highlightSelection(segment).score }}</el-tag>
                  </div>
                  <span v-if="highlightShortlist(segment).reason" class="highlight-shortlist-reason">文本初选：{{ highlightShortlist(segment).reason }}</span>
                  <span v-if="highlightSelection(segment).adjusted" class="highlight-adjustment">
                    视觉审核已调整为 {{ formatSegmentRange(highlightSelection(segment).segment) }}
                  </span>
                  <span>{{ segment.type || 'highlight' }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-if="(analysisResult.risk_notes || []).length || analysisResult.contentRisk?.requiresPublishConfirmation" class="analysis-section">
            <span class="panel-kicker">人工确认</span>
            <div class="risk-list">
              <el-tag v-if="analysisResult.contentRisk?.requiresPublishConfirmation" type="warning" effect="dark">发布前需人工确认</el-tag>
              <el-tag v-for="note in analysisResult.risk_notes" :key="note" type="warning" effect="light">{{ note }}</el-tag>
            </div>
          </div>
        </template>
        <el-empty v-else description="暂无发布文案与内容分析" />
      </div>
      <template #footer>
        <el-button v-if="currentAnalysisRow && [1, 3].includes(analysisStatus)" type="primary" @click="regenerateAnalysis(currentAnalysisRow)">重新生成</el-button>
        <el-button @click="analysisDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="videoDetailDialogVisible"
      :title="currentDetailRow?.chineseTitle || currentDetailRow?.title || '视频详情'"
      width="min(780px, calc(100vw - 32px))"
      class="video-detail-dialog"
    >
      <div v-if="currentDetailRow" class="video-detail-panel">
        <section class="video-detail-section">
          <span class="panel-kicker">线索信息</span>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="当前阶段">
              <el-tag size="small" :type="detailStageTagType(currentDetailRow)">{{ currentStage(currentDetailRow).label }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="分组">{{ currentDetailRow.groupName || '未分类' }}</el-descriptions-item>
            <el-descriptions-item label="频道">{{ currentDetailRow.channel || '未知博主' }}</el-descriptions-item>
            <el-descriptions-item label="粉丝数">{{ currentDetailRow.subscribers || '粉丝数未知' }}</el-descriptions-item>
            <el-descriptions-item label="发布时间">{{ currentDetailRow.publishedAt || '发布时间未知' }}</el-descriptions-item>
            <el-descriptions-item label="视频时长">{{ currentDetailRow.duration || '时长未知' }}</el-descriptions-item>
            <el-descriptions-item label="来源链接" :span="2">
              <a :href="currentDetailRow.url" target="_blank" rel="noopener noreferrer" class="video-detail-link">打开 YouTube 视频</a>
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <section v-if="hasDownloadedVideo(currentDetailRow)" class="video-detail-section">
          <span class="panel-kicker">下载状态</span>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="原视频">已下载</el-descriptions-item>
            <el-descriptions-item label="原视频分辨率">{{ mediaResolutionText(detailMedia.downloaded) }}</el-descriptions-item>
            <el-descriptions-item label="处理状态">{{ isTranslationSkipped(currentDetailRow) ? '已跳过处理' : (hasProcessedVideo(currentDetailRow) ? '已处理' : '待处理') }}</el-descriptions-item>
          </el-descriptions>
        </section>

        <section v-if="activeJobForVideo(currentDetailRow)" class="video-detail-section">
          <span class="panel-kicker">执行任务</span>
          <div class="detail-job-progress">
            <el-progress :percentage="displayProgress(activeJobForVideo(currentDetailRow))" :stroke-width="8" />
            <span>{{ workflowProgressText(activeJobForVideo(currentDetailRow)) }}</span>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="任务状态">{{ jobStatusText(activeJobForVideo(currentDetailRow).status, activeJobForVideo(currentDetailRow).step) }}</el-descriptions-item>
            <el-descriptions-item label="当前步骤">{{ jobStepText(activeJobForVideo(currentDetailRow).step) }}</el-descriptions-item>
          </el-descriptions>
          <div class="detail-settings-list">
            <span v-for="setting in processingSettingsRows(activeJobForVideo(currentDetailRow))" :key="setting.label">
              {{ setting.label }}：{{ setting.value }}
            </span>
          </div>
        </section>

        <section v-if="currentDetailRow.processedVersions?.length" class="video-detail-section">
          <span class="panel-kicker">处理后成品</span>
          <div class="processed-version-details">
            <div v-for="version in currentDetailRow.processedVersions" :key="version.materialId || version.processVersion" class="processed-version-detail">
              <strong>{{ processVersionLabel(version.processVersion) }}</strong>
              <span>{{ version.duration || '时长未知' }}</span>
              <span>{{ fileSizeText(version.filesize) }}</span>
              <span>处理后视频分辨率 {{ mediaResolutionText(detailMedia.processed[version.processVersion]) }}</span>
              <span>{{ version.createdAt || '生成时间未知' }}</span>
              <el-tag v-if="version.coverReburnRequired" size="small" type="warning" effect="plain">封面待重烧</el-tag>
            </div>
          </div>
        </section>

        <section v-if="showInlinePublishDraft(currentDetailRow)" class="video-detail-section">
          <span class="panel-kicker">发布文案</span>
          <div class="detail-publish-draft">
            <strong>{{ currentDetailRow.analysisDraft.selectedTitle || currentDetailRow.analysisDraft.coverTitle || '已生成发布文案' }}</strong>
            <p>{{ currentDetailRow.analysisDraft.publishCopy || '暂无发布文案' }}</p>
            <span>{{ currentDetailRow.analysisDraft.tags.length + currentDetailRow.analysisDraft.customTags.length }} 个话题</span>
          </div>
        </section>

        <section v-if="currentDetailRow.publishDelivery?.targets?.length" class="video-detail-section">
          <span class="panel-kicker">发布状态</span>
          <div class="detail-target-list">
            <div v-for="target in currentDetailRow.publishDelivery.targets" :key="target.recordId || target.type" class="detail-target-item">
              <el-tag :type="publishTargetTagType(target.status)" effect="plain">
                {{ target.name }} · {{ publishTargetStatusText(target.status) }}
              </el-tag>
              <span v-if="target.publishedAt">发布于 {{ formatDetailTime(target.publishedAt) }}</span>
              <span v-else>暂无发布时间</span>
            </div>
          </div>
        </section>

        <section v-if="detailWorkflowLoading || detailSubtitleDecision" class="video-detail-section">
          <span class="panel-kicker">字幕自动适配</span>
          <div v-if="detailWorkflowLoading" class="detail-subtitle-loading">正在读取最近一次处理判断</div>
          <template v-else-if="detailSubtitleDecision">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="原视频字幕">{{ detailSubtitleDecision.classificationLabel }}</el-descriptions-item>
              <el-descriptions-item label="默认处理策略">{{ detailSubtitleDecision.actionLabel }}</el-descriptions-item>
              <el-descriptions-item label="判断时间">{{ formatDetailTime(detailSubtitleDecision.jobAt) }}</el-descriptions-item>
              <el-descriptions-item label="判断状态">{{ detailSubtitleDecision.statusLabel }}</el-descriptions-item>
            </el-descriptions>
            <div class="detail-subtitle-reason">{{ detailSubtitleDecision.reason }}</div>
          </template>
        </section>

        <section v-if="stageErrorJob(currentDetailRow)" class="video-detail-section">
          <span class="panel-kicker">异常信息</span>
          <div class="detail-row">
            <span>任务消息</span>
            <p>{{ stageErrorJob(currentDetailRow).errorReason || stageErrorJob(currentDetailRow).message || '暂无详细错误信息' }}</p>
          </div>
        </section>
      </div>
      <template #footer>
        <el-button @click="videoDetailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="processedPreviewDialogVisible"
      :title="currentDetailRow?.chineseTitle || currentPreviewMaterial?.displayTitle || currentDetailRow?.title || '处理后视频预览'"
      width="min(920px, calc(100vw - 32px))"
      :top="'8vh'"
      @close="stopProcessedPreview"
      @closed="resetProcessedPreview"
    >
      <div v-if="currentPreviewMaterial" class="processed-preview-container">
        <video ref="processedPreviewVideoRef" :src="processedPreviewUrl(currentPreviewMaterial)" controls class="processed-preview-video">
          您的浏览器不支持视频播放
        </video>
      </div>
    </el-dialog>

    <el-dialog
      v-model="jobErrorDialogVisible"
      title="任务失败详情"
      width="560px"
      destroy-on-close
    >
      <div v-if="currentErrorJob" class="job-error-detail">
        <div class="detail-row">
          <span>任务状态</span>
          <strong>{{ jobStatusText(currentErrorJob.status, currentErrorJob.step) }}</strong>
        </div>
        <div class="detail-row">
          <span>当前阶段</span>
          <strong>{{ jobStepText(currentErrorJob.step) }}</strong>
        </div>
        <div class="detail-row" v-if="currentErrorJob.errorReason">
          <span>错误原因</span>
          <p>{{ currentErrorJob.errorReason }}</p>
        </div>
        <div class="detail-row" v-if="currentErrorJob.errorCode">
          <span>错误码</span>
          <code>{{ currentErrorJob.errorCode }}</code>
        </div>
        <div class="detail-row" v-if="currentErrorJob.errorType">
          <span>错误类型</span>
          <code>{{ currentErrorJob.errorType }}</code>
        </div>
        <div class="detail-row" v-if="currentErrorJob.errorDetail">
          <span>详细信息</span>
          <p>{{ currentErrorJob.errorDetail }}</p>
        </div>
        <div class="detail-row" v-if="currentErrorJob.message">
          <span>任务消息</span>
          <p>{{ currentErrorJob.message }}</p>
        </div>
        <el-empty
          v-if="!jobErrorMessageAvailable(currentErrorJob)"
          description="暂无详细错误信息，请查看任务列表消息"
        />
      </div>
      <template #footer>
        <el-button @click="jobErrorDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="moveVideoDialogVisible" title="移动到分组" width="400px" destroy-on-close>
      <el-select v-model="moveTargetGroupId" placeholder="选择目标分组" style="width: 100%">
        <el-option
          v-for="group in videoGroupStore.groups"
          :key="group.id"
          :label="group.name"
          :value="group.id"
          :disabled="Number(movingVideo?.groupId) === Number(group.id)"
        />
      </el-select>
      <template #footer>
        <el-button @click="moveVideoDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="movingVideoGroup" @click="confirmMoveVideo">移动</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="resetDialogVisible" title="重新处理视频" width="min(520px, calc(100vw - 32px))">
      <div class="reset-processing-dialog">
        <p>删除「{{ resetTarget?.title || resetTarget?.url }}」的{{ processVersionLabel(workflowForm.processVersion) }}成品，下载原视频和其他处理版本会保留。</p>
        <el-checkbox v-model="refreshTranscriptOnReset">强制重新转写</el-checkbox>
        <span>默认复用现有转写缓存；只有识别内容有误时才需要重新转写。</span>
      </div>
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="resettingId === resetTarget?.id" @click="confirmResetProcessing">删除成品并准备重做</el-button>
      </template>
    </el-dialog>
    <el-dialog
      v-model="customTitleDialogVisible"
      :title="customTitleDialogTitle"
      width="min(520px, calc(100vw - 32px))"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="自定义发布标题" required>
          <el-input
            v-model="customTitleDraft"
            maxlength="120"
            show-word-limit
            autofocus
            placeholder="请输入要发布的标题"
            @keyup.enter="confirmCustomTitle"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cancelCustomTitle">取消</el-button>
        <el-button type="primary" @click="confirmCustomTitle">使用此标题</el-button>
      </template>
    </el-dialog>
    <VideoGroupManageDialog v-model="groupManagerVisible" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Clock, Delete, DocumentCopy, Download, Folder, InfoFilled, Link, Plus, Refresh, Search, Setting, VideoCamera, VideoPlay } from '@element-plus/icons-vue'
import { youtubeApi } from '@/api/youtube'
import { accountApi } from '@/api/account'
import { materialApi } from '@/api/material'
import { useAppStore } from '@/stores/app'
import { useAccountStore } from '@/stores/account'
import { useNotificationStore } from '@/stores/notification'
import { useVideoGroupStore } from '@/stores/videoGroup'
import { useUserStore } from '@/stores'
import VideoGroupSelect from '@/components/VideoGroupSelect.vue'
import VideoGroupManageDialog from '@/components/VideoGroupManageDialog.vue'
import { cleanTopicList, normalizeDraftTopics } from '@/utils/publishDraft'
import { backendTimeMs, formatBeijingTime } from '@/utils/time'
import { userWorkspaceStorageKey } from '@/utils/userWorkspaceStorage'

const loading = ref(false)
const searchLoading = ref(false)
const jobsLoading = ref(false)
const importing = ref(false)
const downloadingId = ref('')
const translatingId = ref('')
const creatingJobId = ref('')
const analyzingId = ref('')
const savingAnalysisId = ref('')
const deletingId = ref('')
const batchDeleting = ref(false)
const retentionScanning = ref(false)
const resettingId = ref('')
const resetDialogVisible = ref(false)
const resetTarget = ref(null)
const refreshTranscriptOnReset = ref(false)
const settingsDialogVisible = ref(false)
const settingsTab = ref('processing')
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const analysisDialogVisible = ref(false)
const analysisLoading = ref(false)
const analysisResult = ref(null)
const analysisStatus = ref(0)
const currentAnalysisRow = ref(null)
const videoDetailDialogVisible = ref(false)
const currentDetailRow = ref(null)
const processedPreviewDialogVisible = ref(false)
const currentPreviewMaterial = ref(null)
const processedPreviewVideoRef = ref(null)
const previewLoadingId = ref('')
const detailMedia = reactive({ downloaded: null, processed: {} })
const detailWorkflowJob = ref(null)
const detailWorkflowLoading = ref(false)
const jobErrorDialogVisible = ref(false)
const currentErrorJob = ref(null)
const videoTableRef = ref(null)
const videoListSectionRef = ref(null)
const items = ref([])
const jobs = ref([])
const videoTotal = ref(0)
const videoSummary = ref({})
const lastResult = ref(null)
const nowTick = ref(Date.now())
const editingPublishDraftIds = ref(new Set())
const editingPublishDraftForms = reactive({})
const CUSTOM_TITLE_VALUE = '__vidferry_custom_title__'
const CUSTOM_COVER_TITLE_VALUE = '__vidferry_custom_cover_title__'
const customTitleDialogVisible = ref(false)
const customTitleDialogKind = ref('title')
const customTitleDialogRow = ref(null)
const customTitleDraft = ref('')
const customTitlePrevious = ref('')
const customTitlePreviousEnabled = ref(false)
const customTitleDialogTitle = computed(() => (
  customTitleDialogKind.value === 'cover' ? '自定义封面标题' : '自定义发布标题'
))
const selectedVideos = ref([])
const groupManagerVisible = ref(false)
const moveVideoDialogVisible = ref(false)
const movingVideo = ref(null)
const moveTargetGroupId = ref('')
const movingVideoGroup = ref(false)
const searchProgress = reactive({
  visible: false,
  jobId: '',
  found: 0,
  requested: 0,
  created: 0,
  duplicate: 0,
  skipped: 0,
  failed: 0,
  status: '',
  message: ''
})
const notificationStore = useNotificationStore()
const appStore = useAppStore()
const accountStore = useAccountStore()
const videoGroupStore = useVideoGroupStore()
let jobsTimer = null
let searchJobTimer = null
let clockTimer = null
let jobsRequesting = false
let searchJobRequesting = false
let searchJobPollFailures = 0
let workflowSettingsLoaded = false
let loadingWorkflowSettings = false
let workflowSettingsSaveTimer = null
const JOBS_POLL_ACTIVE_MS = 1500
const JOBS_POLL_IDLE_MS = 8000
const SEARCH_JOB_POLL_MS = 1200

const openSettingsFromLayout = () => {
  settingsDialogVisible.value = true
}

const consumeOpenSettingsQuery = async () => {
  if (route.query.openSettings !== '1') return
  await nextTick()
  settingsDialogVisible.value = true
  router.replace({ path: route.path, query: { ...route.query, openSettings: undefined } })
}

const form = reactive({
  query: '',
  groupId: '',
  limit: 8
})

const keywordPresets = [
  { label: '中国旅行见闻', query: 'foreigner China travel vlog first time in China' },
  { label: '中国科技创新', query: 'China technology innovation' },
  { label: '自然风光纪录片', query: 'beautiful nature documentary 4K' },
  { label: '传统美食制作', query: 'traditional Chinese food cooking' },
  { label: '日常手作教程', query: 'satisfying DIY crafts tutorial' },
  { label: '动物科普趣闻', query: 'cute animals educational documentary' }
]

const showWorkflowJobErrorDetails = (job) => {
  if (!job || !['failed', 'abnormal'].includes(job.status)) return
  currentErrorJob.value = job
  jobErrorDialogVisible.value = true
}

const consumeFocusJobQuery = async () => {
  const jobId = String(route.query.focusJob || '')
  if (!jobId) return
  const action = String(route.query.focusAction || '')
  try {
    const res = await youtubeApi.getWorkflowJob(jobId)
    const job = res.data
    if (!job?.id) throw new Error('任务不存在')
    const index = jobs.value.findIndex(item => String(item.id) === jobId)
    if (index >= 0) jobs.value[index] = job
    else jobs.value.unshift(job)
    if (action === 'error') showWorkflowJobErrorDetails(job)
    if (action === 'confirm') promptPendingPublishConfirmations([job])
  } catch (error) {
    ElMessage.warning('对应任务已不存在或无法读取，请刷新任务列表。')
  } finally {
    await router.replace({ path: route.path, query: { ...route.query, focusJob: undefined, focusAction: undefined } })
  }
}

const persistSearchQuery = () => {
  if (form.query.trim()) flushWorkflowSettings()
}

const applyKeywordPreset = (query) => {
  form.query = query
  persistSearchQuery()
}

const manualForm = reactive({
  url: '',
  groupId: ''
})

const workflowForm = reactive({
  publishAccountGroupId: null,
  publishToDouyin: false,
  account: 'creator',
  publishToBilibili: false,
  bilibiliAccount: 'creator',
  bilibiliTid: 21,
  publishToXiaohongshu: false,
  xiaohongshuAccount: '',
  publishToKuaishou: false,
  kuaishouAccount: '',
  publishToTencent: false,
  tencentAccount: '',
  processVersion: 'translation_v1',
  subtitleLanguage: 'zh-CN',
  burnProfile: 'stable',
  subtitleSize: 'large',
  translatorLabel: 'Vidferry',
  coverSignature: 'Vidferry',
  watermarkEnabled: false,
  watermarkText: '',
  highlightCount: 3,
  subtitleMode: 'auto',
  translationEnabled: true,
  highlightIntroEnabled: true,
  coverIntroEnabled: true,
  commentBurnEnabled: false,
  subtitleMaskEnabled: false,
  commentBurnCount: 30,
  commentTranslationMode: 'google_llm',
  contentSafetyReviewEnabled: false
})
const commentBurnAvailable = ref(true)
const subtitleMaskAvailable = ref(true)

const WORKFLOW_SETTINGS_STORAGE_KEY = computed(() => userWorkspaceStorageKey(userStore.userInfo?.id, 'youtube.workflowSettings'))

const fallbackBilibiliCategories = [
  { tid: 21, group: '生活', name: '日常', label: '生活 / 日常' },
  { tid: 180, group: '纪录片', name: '社会·美食·旅行', label: '纪录片 / 社会·美食·旅行' },
  { tid: 37, group: '纪录片', name: '人文·历史', label: '纪录片 / 人文·历史' },
  { tid: 201, group: '知识', name: '科学科普', label: '知识 / 科学科普' },
  { tid: 124, group: '知识', name: '社科·法律·心理', label: '知识 / 社科·法律·心理' },
  { tid: 215, group: '美食', name: '美食记录', label: '美食 / 美食记录' },
  { tid: 95, group: '科技', name: '数码', label: '科技 / 数码' }
]

const bilibiliCategories = ref(fallbackBilibiliCategories)
const defaultBilibiliTid = ref(21)

const isUnknownBilibiliTid = (tid) => {
  const value = Number(tid || 0)
  return value > 0 && !bilibiliCategories.value.some(category => Number(category.tid) === value)
}

const loadBilibiliCategories = async () => {
  try {
    const response = await youtubeApi.getBilibiliCategories()
    const items = response.data?.items || response.items || []
    if (Array.isArray(items) && items.length > 0) {
      bilibiliCategories.value = items.map(item => ({
        ...item,
        tid: Number(item.tid),
        label: item.label || `${item.group || 'B站'} / ${item.name || item.tid}`
      }))
      defaultBilibiliTid.value = Number(response.data?.defaultTid || response.defaultTid || 21)
      if (!workflowForm.bilibiliTid) {
        workflowForm.bilibiliTid = defaultBilibiliTid.value
      }
    }
  } catch (error) {
    console.warn('读取 B站分区失败，使用内置常用分区', error)
  }
}

const normalAccountsByPlatform = (platformName) => {
  return accountStore.accounts.filter(account => account.platform === platformName && account.status === '正常')
}

const isNormalAccountName = (platformName, accountName) => {
  const name = String(accountName || '').trim()
  if (!name) return false
  return normalAccountsByPlatform(platformName).some(account => account.name === name)
}

const workflowPublishPlatforms = [
  { key: 'douyin', label: '抖音', platform: '抖音', enabledKey: 'publishToDouyin', accountKey: 'account' },
  { key: 'bilibili', label: 'B站', platform: 'B站', enabledKey: 'publishToBilibili', accountKey: 'bilibiliAccount' },
  { key: 'xiaohongshu', label: '小红书', platform: '小红书', enabledKey: 'publishToXiaohongshu', accountKey: 'xiaohongshuAccount' },
  { key: 'kuaishou', label: '快手', platform: '快手', enabledKey: 'publishToKuaishou', accountKey: 'kuaishouAccount' },
  { key: 'tencent', label: '视频号', platform: '视频号', enabledKey: 'publishToTencent', accountKey: 'tencentAccount' }
]

const publishAccountGroups = ref([])
let applyingAccountGroup = false

const loadPublishAccountGroups = async () => {
  try {
    const response = await accountApi.getPublishAccountGroups()
    publishAccountGroups.value = response.data || []
  } catch (error) {
    publishAccountGroups.value = []
    console.warn('加载发布账号组失败', error)
  }
}

const applyPublishAccountGroup = (groupId) => {
  if (!groupId) return
  const group = publishAccountGroups.value.find(item => Number(item.id) === Number(groupId))
  if (!group?.complete) {
    workflowForm.publishAccountGroupId = null
    ElMessage.warning('该账号组配置不完整，不能用于创建任务')
    return
  }
  const fields = {
    1: ['publishToXiaohongshu', 'xiaohongshuAccount'], 2: ['publishToTencent', 'tencentAccount'],
    3: ['publishToDouyin', 'account'], 4: ['publishToKuaishou', 'kuaishouAccount'], 5: ['publishToBilibili', 'bilibiliAccount']
  }
  const accounts = new Map(group.accounts.map(account => [Number(account.platformType), account.name]))
  applyingAccountGroup = true
  Object.entries(fields).forEach(([platformType, [enabledKey, accountKey]]) => {
    workflowForm[enabledKey] = accounts.has(Number(platformType))
    workflowForm[accountKey] = accounts.get(Number(platformType)) || ''
  })
  nextTick(() => { applyingAccountGroup = false })
}

const syncWorkflowAccountSelections = () => {
  workflowPublishPlatforms.forEach(item => {
    if (workflowForm[item.accountKey] && !isNormalAccountName(item.platform, workflowForm[item.accountKey])) {
      workflowForm[item.accountKey] = ''
    }
  })
}

watch(
  () => [workflowForm.publishToDouyin, workflowForm.account, workflowForm.publishToBilibili, workflowForm.bilibiliAccount, workflowForm.publishToXiaohongshu, workflowForm.xiaohongshuAccount, workflowForm.publishToKuaishou, workflowForm.kuaishouAccount, workflowForm.publishToTencent, workflowForm.tencentAccount],
  () => {
    if (!applyingAccountGroup) workflowForm.publishAccountGroupId = null
  }
)

const loadAccounts = async () => {
  try {
    const response = await accountApi.getAccounts()
    accountStore.setAccounts(response.data || [])
    syncWorkflowAccountSelections()
  } catch (error) {
    console.warn('读取账号列表失败', error)
  }
}

const subtitleLanguages = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en', label: '英文' },
  { value: 'ja', label: '日文' },
  { value: 'ko', label: '韩文' },
  { value: 'es', label: '西班牙语' },
  { value: 'fr', label: '法语' },
  { value: 'de', label: '德语' },
  { value: 'ru', label: '俄语' }
]

const processVersions = [
  {
    value: 'translation_v1',
    label: '处理版本一：翻译',
    description: '保留当前链路：生成目标语言字幕，并添加左上角原作者信息。'
  },
  {
    value: 'editing_v1',
    label: '处理版本二：剪辑',
    description: '保留字幕处理链路，并按设置条数将主题高光与核心看点拼接到视频开头。'
  }
]

const escapeHtml = (value) => {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const burnProfiles = [
  {
    value: 'stable',
    label: '标准 1080p（推荐）',
    description: '适合大多数视频处理任务，在 1080p 输出、画质和文件体积之间取得平衡。',
    params: [
      { name: 'preset', value: 'fast', description: 'H.264 标准编码档，在画质与处理时间之间保持平衡。' },
      { name: 'crf', value: '23', description: '通用画质档，文件体积和码率更可控，适合平台二次处理。' },
      { name: 'fps', value: '最高 30', description: '输出固定帧率并限制到 30fps，降低竖屏和高帧率素材的播放压力。' },
      { name: '分辨率', value: '最高 1080p', description: '横屏最高 1920x1080，竖屏最高 1080x1920，超过时自动等比缩放。' },
      { name: '码率峰值', value: '5000k', description: '限制瞬时峰值码率，减少播放器因高码率突增造成的卡顿。' },
      { name: 'genpts', value: '开启', description: '重建视频时间戳，修复部分源视频时间轴不连续的问题。' },
      { name: 'audio', value: 'AAC', description: '统一转为 AAC，避免 Opus 音频在部分播放器中无法播放。' }
    ]
  },
  {
    value: 'fast',
    label: '快速 1080p',
    description: '适合短视频或临时预览，烧录更快，画质和码率控制比标准 1080p 略弱。',
    params: [
      { name: 'preset', value: 'veryfast', description: '更快的 H.264 编码档位，处理时间更短。' },
      { name: 'crf', value: '24', description: '画质略低于标准 1080p，文件更小，速度更快。' },
      { name: 'fps', value: '最高 30', description: '仍保留固定帧率和 30fps 限制，避免明显时间戳卡顿。' },
      { name: '分辨率', value: '最高 1080p', description: '同样限制输出尺寸，保证基础播放兼容性。' },
      { name: '码率峰值', value: '4500k', description: '使用更低峰值码率，减少临时预览文件体积。' },
      { name: 'genpts', value: '开启', description: '仍保留时间戳重建，保证基础稳定性。' },
      { name: 'audio', value: 'AAC', description: '仍统一输出 AAC，保证平台和本地播放器兼容性。' }
    ]
  },
  {
    value: '2k',
    label: '2K 高画质（需 2K 原片）',
    description: '仅适合原视频本身达到 2K 的场景；保留更多画面细节，处理时间和文件体积会增加。',
    params: [
      { name: 'preset', value: 'fast', description: '维持 H.264 快速编码，在画质与处理时间间取得平衡。' },
      { name: 'crf', value: '21', description: '比 1080p 档位保留更多画面细节，文件体积相应增加。' },
      { name: 'fps', value: '最高 30', description: '仍限制为 30fps，避免高帧率增加播放器压力。' },
      { name: '分辨率', value: '最高 1440p', description: '仅支持横屏不低于 2560x1440 或竖屏不低于 1440x2560 的下载视频；不符合时不会创建任务。' },
      { name: '码率峰值', value: '12000k', description: '为 2K 保留更高峰值码率，同时控制移动端播放压力。' },
      { name: 'H.264', value: 'High 5.0', description: '使用 2K 所需的 H.264 级别，兼容较新的播放器和主流平台。' },
      { name: 'audio', value: 'AAC', description: '统一输出 AAC，保证平台和本地播放器兼容性。' }
    ]
  }
]

const subtitleSizes = [
  {
    value: 'standard',
    label: '标准',
    description: '适合横屏长视频留白较少的情况；仅控制中英字幕的基准字号。'
  },
  {
    value: 'large',
    label: '大号（抖音推荐）',
    description: '比标准字号更醒目，适合大多数手机端播放场景；其他烧制元素不受此设置影响。'
  },
  {
    value: 'douyin',
    label: '超大号',
    description: '适合手机竖屏和国内平台预览；仅控制中英字幕的基准字号，所有烧制元素会随输出画布等比缩放。'
  }
]

const currentProcessVersion = computed(() => {
  return processVersions.find(version => version.value === workflowForm.processVersion) || processVersions[0]
})

const currentSubtitleLanguage = computed(() => {
  return subtitleLanguages.find(language => language.value === workflowForm.subtitleLanguage) || subtitleLanguages[0]
})

const currentBurnProfile = computed(() => {
  return burnProfiles.find(profile => profile.value === workflowForm.burnProfile) || burnProfiles[0]
})

const currentSubtitleSize = computed(() => {
  return subtitleSizes.find(size => size.value === workflowForm.subtitleSize) || subtitleSizes[2]
})

const normalizeStoredWorkflowSettings = (rawSettings = {}) => {
  const settings = rawSettings && typeof rawSettings === 'object' ? rawSettings : {}
  const next = {}
  if (processVersions.some(version => version.value === settings.processVersion)) {
    next.processVersion = settings.processVersion
  }
  if (subtitleLanguages.some(language => language.value === settings.subtitleLanguage)) {
    next.subtitleLanguage = settings.subtitleLanguage
  }
  if (burnProfiles.some(profile => profile.value === settings.burnProfile)) {
    next.burnProfile = settings.burnProfile
  }
  if (subtitleSizes.some(size => size.value === settings.subtitleSize)) {
    next.subtitleSize = settings.subtitleSize
  }
  if (typeof settings.translatorLabel === 'string' && settings.translatorLabel.trim()) {
    next.translatorLabel = settings.translatorLabel.trim().slice(0, 20)
  }
  if (typeof settings.coverSignature === 'string' || typeof settings.coverBrandName === 'string') {
    next.coverSignature = String(settings.coverSignature ?? settings.coverBrandName).trim().slice(0, 24) || 'Vidferry'
  }
  if (typeof settings.searchQuery === 'string' && settings.searchQuery.trim()) {
    next.searchQuery = settings.searchQuery.trim().slice(0, 160)
  }
  if (typeof settings.watermarkEnabled === 'boolean') {
    next.watermarkEnabled = settings.watermarkEnabled
  }
  if (typeof settings.watermarkText === 'string') {
    const watermarkText = settings.watermarkText.trim().slice(0, 16)
    next.watermarkText = watermarkText.length >= 2 ? watermarkText : ''
  }
  const highlightCount = Number(settings.highlightCount)
  if ([1, 2, 3].includes(highlightCount)) {
    next.highlightCount = highlightCount
  }
  const commentBurnCount = Number(settings.commentBurnCount)
  if ([20, 25, 30, 35, 40, 45, 50].includes(commentBurnCount)) {
    next.commentBurnCount = commentBurnCount
  }
  if (['auto', 'force_burn', 'original'].includes(settings.subtitleMode)) {
    next.subtitleMode = settings.subtitleMode
  }
  for (const key of ['translationEnabled', 'highlightIntroEnabled', 'coverIntroEnabled', 'commentBurnEnabled', 'subtitleMaskEnabled']) {
    if (typeof settings[key] === 'boolean') next[key] = settings[key]
  }
  if (['google_llm', 'google'].includes(settings.commentTranslationMode)) {
    next.commentTranslationMode = settings.commentTranslationMode
  }
  return next
}

const readLocalWorkflowSettings = () => {
  try {
    const raw = WORKFLOW_SETTINGS_STORAGE_KEY.value ? localStorage.getItem(WORKFLOW_SETTINGS_STORAGE_KEY.value) : ''
    if (!raw) return {}
    return normalizeStoredWorkflowSettings(JSON.parse(raw))
  } catch (error) {
    console.warn('读取处理设置失败', error)
    return {}
  }
}

const persistLocalWorkflowSettings = (settings) => {
  try {
    if (WORKFLOW_SETTINGS_STORAGE_KEY.value) localStorage.setItem(WORKFLOW_SETTINGS_STORAGE_KEY.value, JSON.stringify(settings))
  } catch (error) {
    console.warn('保存本地处理设置失败', error)
  }
}

const currentWorkflowSettingsPayload = () => ({
  processVersion: workflowForm.processVersion,
  subtitleLanguage: workflowForm.subtitleLanguage,
  burnProfile: workflowForm.burnProfile,
  subtitleSize: workflowForm.subtitleSize,
  translatorLabel: workflowForm.translatorLabel,
  coverSignature: workflowForm.coverSignature,
  searchQuery: form.query,
  watermarkEnabled: workflowForm.watermarkEnabled,
  watermarkText: workflowForm.watermarkText,
  highlightCount: workflowForm.highlightCount,
  subtitleMode: workflowForm.subtitleMode,
  translationEnabled: workflowForm.translationEnabled,
  highlightIntroEnabled: workflowForm.highlightIntroEnabled,
  coverIntroEnabled: workflowForm.coverIntroEnabled,
  commentBurnEnabled: workflowForm.commentBurnEnabled,
  subtitleMaskEnabled: workflowForm.subtitleMaskEnabled,
  commentBurnCount: workflowForm.commentBurnCount,
  commentTranslationMode: workflowForm.commentTranslationMode,
  contentSafetyReviewEnabled: workflowForm.contentSafetyReviewEnabled
})

const applyStoredWorkflowSettings = (settings) => {
  commentBurnAvailable.value = settings?.commentBurnAvailable !== false
  subtitleMaskAvailable.value = settings?.subtitleMaskAvailable !== false
  const { searchQuery, ...workflowSettings } = normalizeStoredWorkflowSettings(settings)
  Object.assign(workflowForm, workflowSettings)
  if (!commentBurnAvailable.value || workflowForm.processVersion !== 'editing_v1') workflowForm.commentBurnEnabled = false
  if (!subtitleMaskAvailable.value) workflowForm.subtitleMaskEnabled = false
  if (!subtitleMaskAvailable.value && workflowForm.subtitleMode === 'auto') workflowForm.subtitleMode = 'force_burn'
  if (searchQuery) {
    form.query = searchQuery
  }
}

const normalizeWatermarkText = () => {
  const watermarkText = workflowForm.watermarkText.trim().slice(0, 16)
  workflowForm.watermarkText = watermarkText.length >= 2 ? watermarkText : ''
  if (watermarkText.length === 1) {
    ElMessage.warning('水印内容至少需要 2 个字符')
  }
  flushWorkflowSettings()
}

const consumeAgentStatusQuery = async () => {
  const status = String(route.query.status || '')
  if (!['initial', 'downloaded', 'processed', 'published', 'running', 'failed', 'abnormal'].includes(status)) return
  videoFilter.status = status
  await nextTick()
  videoListSectionRef.value?.$el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const loadWorkflowSettings = async () => {
  const localSettings = readLocalWorkflowSettings()
  if (Object.keys(localSettings).length) {
    applyStoredWorkflowSettings(localSettings)
  }
  try {
    const response = await youtubeApi.getWorkflowSettings()
    applyStoredWorkflowSettings(response.data || response)
    persistLocalWorkflowSettings(currentWorkflowSettingsPayload())
  } catch (error) {
    console.warn('读取后端处理设置失败，使用本地缓存', error)
  }
}

const saveWorkflowSettings = () => {
  const settings = currentWorkflowSettingsPayload()
  persistLocalWorkflowSettings(settings)
  if (!workflowSettingsLoaded || loadingWorkflowSettings) return
  if (workflowSettingsSaveTimer) {
    window.clearTimeout(workflowSettingsSaveTimer)
  }
  workflowSettingsSaveTimer = window.setTimeout(async () => {
    try {
      const response = await youtubeApi.updateWorkflowSettings(settings)
      const savedSettings = normalizeStoredWorkflowSettings(response.data || response)
      persistLocalWorkflowSettings(savedSettings)
    } catch (error) {
      console.warn('保存后端处理设置失败，已保留本地缓存', error)
    }
  }, 250)
}

const flushWorkflowSettings = async () => {
  if (workflowSettingsSaveTimer) {
    window.clearTimeout(workflowSettingsSaveTimer)
    workflowSettingsSaveTimer = null
  }
  if (!workflowSettingsLoaded || loadingWorkflowSettings) return
  try {
    await youtubeApi.updateWorkflowSettings(currentWorkflowSettingsPayload())
  } catch (error) {
    console.warn('同步后端处理设置失败，已保留本地缓存', error)
  }
}

const processVersionLabel = (value) => {
  return processVersions.find(version => version.value === value)?.label?.split('：')[0] || value || '未知版本'
}

const processingSettingsRows = (settings = {}) => {
  const enabled = value => value ? '开启' : '关闭'
  const burnProfile = burnProfiles.find(item => item.value === settings.burnProfile)?.label || settings.burnProfile || '-'
  const subtitleSize = subtitleSizes.find(item => item.value === settings.subtitleSize)?.label || settings.subtitleSize || '-'
  const commentMode = settings.commentTranslationMode === 'google' ? 'Google 翻译' : 'Google 翻译 + LLM 修订'
  const analysis = settings.sourceSubtitleAnalysis || {}
  const subtitleMode = { auto: '自动适配', force_burn: '强制烧制', original: '原字幕', legacy: '历史模式' }[settings.subtitleMode] || '历史模式'
  const finalAction = { original: '原字幕', burn: '烧制', mask_and_burn: '遮挡后烧制' }[analysis.decision?.effectiveAction] || (settings.subtitleMaskEnabled ? '遮挡后烧制' : (settings.translationEnabled ? '烧制' : '原字幕'))
  return [
    { label: '处理版本', value: processVersionLabel(settings.processVersion) },
    { label: '烧录预设', value: burnProfile },
    { label: '字幕字号', value: subtitleSize },
    { label: '字幕翻译', value: enabled(settings.translationEnabled) },
    { label: '字幕模式', value: subtitleMode },
    { label: '最终处理', value: finalAction },
    { label: '判断原因', value: analysis.reason || '-' },
    { label: '翻译署名', value: settings.translatorLabel || '-' },
    { label: '水印', value: settings.watermarkEnabled ? settings.watermarkText || '已开启' : '关闭' },
    { label: '高光片头', value: settings.highlightIntroEnabled ? `${settings.highlightCount || 0} 条` : '关闭' },
    { label: '封面片头', value: settings.coverIntroEnabled ? settings.coverTitle || '开启' : '关闭' },
    { label: '评论烧制', value: settings.commentBurnEnabled ? `${settings.commentBurnCount || 0} 条，${commentMode}` : '关闭' },
    { label: '字幕遮挡', value: enabled(settings.subtitleMaskEnabled) },
    { label: '内容安全审查', value: enabled(settings.contentSafetyReviewEnabled) }
  ]
}

watch(() => workflowForm.processVersion, (nextVersion, previousVersion) => {
  if (nextVersion !== 'editing_v1') workflowForm.commentBurnEnabled = false
  if (!previousVersion || nextVersion === previousVersion) return
  if (!workflowSettingsLoaded || loadingWorkflowSettings) return
  const label = processVersionLabel(nextVersion)
  ElMessage({
    type: 'info',
    message: `已切换到${label}，不影响当前已经提交的任务。`,
    showClose: true,
    duration: 3600,
    offset: 72
  })
})

watch(() => workflowForm.subtitleMode, value => {
  workflowForm.translationEnabled = value !== 'original'
  if (value !== 'force_burn') workflowForm.subtitleMaskEnabled = false
})

watch(
  () => ({
    processVersion: workflowForm.processVersion,
    subtitleLanguage: workflowForm.subtitleLanguage,
    burnProfile: workflowForm.burnProfile,
    subtitleSize: workflowForm.subtitleSize,
    translatorLabel: workflowForm.translatorLabel,
    coverSignature: workflowForm.coverSignature,
    watermarkEnabled: workflowForm.watermarkEnabled,
    watermarkText: workflowForm.watermarkText,
    highlightCount: workflowForm.highlightCount,
    subtitleMode: workflowForm.subtitleMode,
    translationEnabled: workflowForm.translationEnabled,
    highlightIntroEnabled: workflowForm.highlightIntroEnabled,
    coverIntroEnabled: workflowForm.coverIntroEnabled,
    commentBurnEnabled: workflowForm.commentBurnEnabled,
    subtitleMaskEnabled: workflowForm.subtitleMaskEnabled,
    commentBurnCount: workflowForm.commentBurnCount,
    commentTranslationMode: workflowForm.commentTranslationMode
  }),
  saveWorkflowSettings,
  { deep: true }
)

watch(() => form.query, saveWorkflowSettings)
watch(
  () => videoGroupStore.groups.map(group => group.id),
  (groupIds) => {
    const hasGroup = value => groupIds.some(id => Number(id) === Number(value))
    if (form.groupId && !hasGroup(form.groupId)) form.groupId = videoGroupStore.defaultGroupId || ''
    if (manualForm.groupId && !hasGroup(manualForm.groupId)) manualForm.groupId = videoGroupStore.defaultGroupId || ''
    if (videoFilter.groupId && !hasGroup(videoFilter.groupId)) videoFilter.groupId = ''
  }
)

const hasCurrentProcessVersion = (item) => {
  return Array.isArray(item.processedVersions) && item.processedVersions.some(version => version.processVersion === workflowForm.processVersion)
}

const processedVersionBadges = (item) => {
  if (!Array.isArray(item.processedVersions)) return []
  return item.processedVersions.map(version => ({
    key: `${version.processVersion}-${version.subtitleLanguage || ''}-${version.materialId || ''}`,
    label: `${processVersionLabel(version.processVersion)}${version.subtitleLanguageLabel ? ` / ${version.subtitleLanguageLabel}` : ''}`
  }))
}

const videoFilter = reactive({
  status: 'all',
  sort: 'default',
  groupId: '',
  keyword: ''
})

const historyMode = computed(() => route.query.view === 'history')

const toggleHistoryMode = () => {
  router.replace({
    path: route.path,
    query: { ...route.query, view: historyMode.value ? undefined : 'history' }
  })
}

const videoPagination = reactive({
  page: 1,
  pageSize: 20
})

const isDownloaded = (item) => Number(item.downloadStatus) === 1
const isTranslated = (item) => Number(item.translateStatus) === 1
const isTranslationSkipped = (item) => Number(item.translateStatus) === 2
const isPublished = (item) => item.publishStatus === 1
const formatDetailTime = value => formatBeijingTime(value, {
  year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
}) || '时间未知'
const unresolvedPublishTargets = (item) => (item.publishDelivery?.targets || []).filter(target => !['confirmed', 'reused'].includes(target.status))
const publishTargetStatusText = status => ({
  queued: '待发布', running: '发布中', confirmed: '已发布', reused: '已发布', failed: '失败', uncertain: '待核验', cancelled: '已取消'
}[status] || status || '未知')
const publishTargetTagType = status => ({
  confirmed: 'success', reused: 'success', queued: 'info', running: 'warning', failed: 'danger', uncertain: 'warning', cancelled: 'info'
}[status] || 'info')
const isRunningJob = (job) => ['queued', 'running', 'waiting_confirmation', 'waiting_publish'].includes(job.status)

const latestJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id)
const activeJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id && isRunningJob(job))
const activeAnalysisJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id && isRunningJob(job) && job.step === 'analysis')
const failedJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id && isFailedJobRelevantToCurrentStage(item, job))
const stageErrorJob = (item) => failedJobForVideo(item)

const detailSubtitleDecision = computed(() => {
  const job = detailWorkflowJob.value
  if (!job || String(job.subtitleMode || '').toLowerCase() !== 'auto') return null
  const analysis = job.sourceSubtitleAnalysis && typeof job.sourceSubtitleAnalysis === 'object'
    ? job.sourceSubtitleAnalysis
    : {}
  const classification = ['zh', 'none', 'non_zh'].includes(analysis.classification) ? analysis.classification : 'unknown'
  const details = {
    zh: { classificationLabel: '自带中文字幕', actionLabel: '不需要烧制字幕' },
    none: { classificationLabel: '无字幕', actionLabel: '烧制字幕' },
    non_zh: { classificationLabel: '有字幕但不带中文字幕', actionLabel: '烧制字幕 + 启用遮罩' },
    unknown: { classificationLabel: '无法判断', actionLabel: '烧制字幕 + 启用遮罩' }
  }[classification]
  return {
    ...details,
    jobAt: job.updatedAt || job.createdAt,
    statusLabel: analysis.status === 'success' ? '判断完成' : '无法完成判断，使用默认策略',
    reason: analysis.reason || '没有可用的原视频字幕判断结果，已采用烧制字幕并启用遮罩。'
  }
})

const isFailedJobRelevantToCurrentStage = (item, job) => {
  if (!job || !['failed', 'partial', 'needs_verification', 'abnormal'].includes(job.status)) return false
  const step = String(job.step || '').toLowerCase()
  if (!isDownloaded(item)) return ['queued', 'download', 'failed'].includes(step)
  if (!isTranslated(item) && !isTranslationSkipped(item)) {
    return ['queued', 'subtitle', 'analysis', 'editing', 'failed'].includes(step)
  }
  if (['publish', 'publish_confirmation'].includes(step)) return true
  return false
}

const jobErrorMessageAvailable = (job = {}) => {
  return Boolean(job.errorReason || job.errorCode || job.errorType || job.errorDetail || job.message)
}

const jobStepText = (step) => {
  const map = {
    queued: '排队中',
    download: '下载',
    subtitle: '处理',
    analysis: '分析',
    content_safety_detect: '风险检测',
    content_safety_confirm: '处理确认',
    content_trim: '风险裁剪',
    publish: '发布',
    publish_confirmation: '发布确认',
    done: '收尾'
  }
  return map[step] || step || '-'
}

const showJobErrorDetails = (item) => {
  showWorkflowJobErrorDetails(stageErrorJob(item))
}

const hasDownloadedVideo = (item) => {
  return Number(item.downloadStatus) === 1 || Boolean(item.downloadedFilePath)
}

const hasProcessedVideo = (item) => {
  return [1, 2].includes(Number(item.translateStatus)) || Boolean(item.processedFilePath)
}

const EDITING_INTRO_PENDING_STATUSES = ['stale', 'submit_failed', 'render_failed', 'concat_failed']

const needsEditingIntroUpdate = (item) => workflowForm.processVersion === 'editing_v1'
  && hasCurrentProcessVersion(item)
  && EDITING_INTRO_PENDING_STATUSES.includes(item.editingIntroStatus)

const needsCoverReburn = (item) => workflowForm.processVersion === 'editing_v1'
  && Boolean(item.processedVersions?.some(version => version.processVersion === 'editing_v1' && version.coverReburnRequired))

// 片头状态文案：仅对"待补/失败"状态返回文案，其余返回空串（不展示徽标）。
const editingIntroStatusText = (status) => {
  switch (status) {
    case 'stale':
      return '片头待更新'
    case 'submit_failed':
    case 'render_failed':
      return '片头待补'
    case 'concat_failed':
      return '拼接失败,可重试'
    default:
      return ''
  }
}

const processingActionStatusText = (item) => {
  const messages = []
  if (needsCoverReburn(item)) {
    messages.push('当前封面标题与已处理视频不一致，点击重新烧制封面')
  }
  const introStatus = editingIntroStatusText(item.editingIntroStatus)
  if (introStatus === '片头待更新') {
    messages.push('当前高光或封面内容与已处理视频不一致，点击更新片头高光')
  } else if (introStatus) {
    messages.push(`${introStatus}，点击更新片头高光重试`)
  }
  return messages.join('；')
}

const deleteBlockReason = (item) => {
  if (activeJobForVideo(item)) return '该视频存在运行中任务，请等待任务结束后再删除线索。'
  if (isPublished(item)) return ''
  if (hasProcessedVideo(item)) return '该视频已存在处理后视频，请先到视频素材页删除对应文件，再删除线索。'
  if (hasDownloadedVideo(item)) return '该视频已存在下载视频，请先到视频素材页删除对应文件，再删除线索。'
  return ''
}

const videoDisplayName = (item = {}) => {
  return item.title || item.url || item.id || '未命名线索'
}

const showDeleteBlockedDetails = async (blockedRows, title = '线索不能删除') => {
  const detailHtml = blockedRows
    .map(({ row, reason }, index) => {
      const name = escapeHtml(videoDisplayName(row))
      const message = escapeHtml(reason || '请先删除对应视频或等待任务结束。')
      return `<li><strong>${index + 1}. ${name}</strong><span>${message}</span></li>`
    })
    .join('')

  return ElMessageBox.alert(
    `<div class="delete-block-details"><p>以下 ${blockedRows.length} 条线索不能删除：</p><ol>${detailHtml}</ol></div>`,
    title,
    {
      confirmButtonText: '知道了',
      dangerouslyUseHTMLString: true,
      type: 'warning'
    }
  ).catch(() => {})
}

const analysisHint = (item) => {
  if (activeAnalysisJobForVideo(item) || Number(item.analysisStatus) === 2) {
    return { label: '发布文案生成中', className: 'is-running' }
  }
  if (Number(item.analysisStatus) === 3) {
    return { label: '发布文案生成失败，可重试', className: 'is-failed' }
  }
  if (item.hasAnalysis || Number(item.analysisStatus) === 1) {
    return { label: '已生成发布文案', className: 'is-ready' }
  }
  return null
}

const detailStageTagType = (item) => ({
  'is-running': 'warning',
  'is-warning': 'warning',
  'is-ready': 'success',
  'is-complete': 'success',
  'is-failed': 'danger'
}[currentStage(item).className] || 'info')

const fileSizeText = (value) => {
  const size = Number(value || 0)
  return size > 0 ? `${size.toFixed(2)} MB` : '文件大小未知'
}

const showVideoDetails = (row) => {
  currentDetailRow.value = row
  detailMedia.downloaded = null
  detailMedia.processed = {}
  detailWorkflowJob.value = null
  videoDetailDialogVisible.value = true
  loadDetailMedia(row)
  loadDetailWorkflow(row)
}

const canPreviewProcessedVideo = (row) => {
  return Number(row.analysisStatus) === 1 && Array.isArray(row.processedVersions) && row.processedVersions.length > 0
}

const processedPreviewUrl = (material) => {
  return material?.asset_id ? materialApi.getMaterialPreviewUrl(material.asset_id) : ''
}

const mediaResolutionText = (media) => {
  if (media === null) return '读取中'
  if (!media?.width || !media?.height) return '未知'
  return `${media.width} × ${media.height}`
}

const readMediaResolution = (material) => new Promise(resolve => {
  const source = processedPreviewUrl(material)
  if (!source) {
    resolve({ width: 0, height: 0 })
    return
  }
  const video = document.createElement('video')
  const finish = () => {
    video.removeAttribute('src')
    video.load()
  }
  const timeout = window.setTimeout(() => {
    finish()
    resolve({ width: 0, height: 0 })
  }, 8000)
  video.preload = 'metadata'
  video.onloadedmetadata = () => {
    window.clearTimeout(timeout)
    const resolution = { width: video.videoWidth, height: video.videoHeight }
    finish()
    resolve(resolution)
  }
  video.onerror = () => {
    window.clearTimeout(timeout)
    finish()
    resolve({ width: 0, height: 0 })
  }
  video.src = source
})

const loadDetailMedia = async (row) => {
  try {
    const [downloadedResponse, processedResponse] = await Promise.all([
      materialApi.getAllMaterials({ sourceType: 'youtube_download', videoIds: row.id, page: 1, pageSize: 1 }),
      materialApi.getAllMaterials({ sourceType: 'youtube_processed', videoIds: row.id, page: 1, pageSize: 100 })
    ])
    const downloaded = downloadedResponse.data?.items?.[0]
    const processed = processedResponse.data?.items || []
    const [downloadedResolution, ...processedResolutions] = await Promise.all([
      downloaded ? readMediaResolution(downloaded) : Promise.resolve({ width: 0, height: 0 }),
      ...processed.map(readMediaResolution)
    ])
    if (currentDetailRow.value?.id !== row.id) return
    detailMedia.downloaded = downloadedResolution
    detailMedia.processed = Object.fromEntries(processed.map((material, index) => [
      material.processVersion,
      processedResolutions[index] || { width: 0, height: 0 }
    ]))
  } catch (error) {
    if (currentDetailRow.value?.id !== row.id) return
    detailMedia.downloaded = { width: 0, height: 0 }
    detailMedia.processed = {}
    console.warn('读取视频分辨率失败:', error)
  }
}

const DETAIL_SUBTITLE_EXCLUDED_OPERATIONS = new Set([
  'download', 'download_only', 'download-only', 'cover_reburn', 'intro_refresh', 'editing_intro'
])

const loadDetailWorkflow = async (row) => {
  detailWorkflowLoading.value = true
  try {
    const response = await youtubeApi.listWorkflowJobs({
      videoIds: row.id,
      page: 1,
      pageSize: 100,
      status: 'all'
    })
    const jobs = (response?.data?.items || [])
      .filter(job => !DETAIL_SUBTITLE_EXCLUDED_OPERATIONS.has(String(job.operation || '').toLowerCase()))
      .sort((left, right) => {
        const rightTime = backendTimeMs(right.updatedAt || right.createdAt)
        const leftTime = backendTimeMs(left.updatedAt || left.createdAt)
        return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime)
      })
    if (currentDetailRow.value?.id === row.id) detailWorkflowJob.value = jobs[0] || null
  } catch (error) {
    if (currentDetailRow.value?.id === row.id) detailWorkflowJob.value = null
    console.warn('读取视频处理任务失败:', error)
  } finally {
    if (currentDetailRow.value?.id === row.id) detailWorkflowLoading.value = false
  }
}

const stopProcessedPreview = () => {
  const video = processedPreviewVideoRef.value
  if (!video) return
  video.pause()
  video.currentTime = 0
  video.removeAttribute('src')
  video.load()
}

const resetProcessedPreview = () => {
  stopProcessedPreview()
  currentPreviewMaterial.value = null
}

const previewProcessedVideo = async (row) => {
  if (!canPreviewProcessedVideo(row)) return
  previewLoadingId.value = row.id
  try {
    const response = await materialApi.getAllMaterials({
      sourceType: 'youtube_processed',
      videoIds: row.id,
      page: 1,
      pageSize: 100
    })
    const materials = response.data?.items || []
    const selected = materials.find(item => item.processVersion === workflowForm.processVersion) || materials[0]
    if (!selected?.asset_id) {
      ElMessage.warning('处理后视频已清理或暂不可预览')
      return
    }
    currentDetailRow.value = row
    currentPreviewMaterial.value = selected
    processedPreviewDialogVisible.value = true
  } catch (error) {
    console.error('获取处理后视频预览失败:', error)
    ElMessage.error('获取处理后视频预览失败')
  } finally {
    previewLoadingId.value = ''
  }
}

const analysisActionText = (item) => {
  if (activeAnalysisJobForVideo(item) || Number(item.analysisStatus) === 2) return '文案生成中'
  if (item.hasAnalysis || Number(item.analysisStatus) === 1) return '查看发布文案'
  if (Number(item.analysisStatus) === 3) return '重新生成文案'
  return '生成发布文案'
}

const buildAnalysisDraft = (draft = {}, result = {}) => {
  const llmTitleOptions = Array.isArray(result.title_options) ? result.title_options.filter(Boolean) : []
  const draftTitleOptions = Array.isArray(draft.title_options) ? draft.title_options.filter(Boolean) : []
  const selectedTitle = draft.title || draft.selectedTitle || draftTitleOptions[0] || llmTitleOptions[0] || ''
  const titleOptions = Array.from(new Set([selectedTitle, ...draftTitleOptions, ...llmTitleOptions].filter(Boolean)))
  const coverTitleOptions = Array.isArray(result.cover_title_options) ? result.cover_title_options.filter(Boolean) : []
  const coverTitle = draft.coverTitle || draft.cover_title || coverTitleOptions[0] || ''
  const customTitleEnabled = Boolean(selectedTitle && !llmTitleOptions.includes(selectedTitle) && !draftTitleOptions.includes(selectedTitle))
  const customCoverTitleEnabled = Boolean(coverTitle && !coverTitleOptions.includes(coverTitle))
  const draftTags = cleanTopicList(draft.tags)
  const resultTags = cleanTopicList(result.tags)
  const selectedTags = draftTags.length ? draftTags : resultTags
  const customTags = cleanTopicList(draft.customTags).filter(tag => !selectedTags.includes(tag))
  const tagOptions = Array.from(new Set([...selectedTags, ...resultTags]))
  return {
    titleOptions,
    selectedTitle,
    customTitleEnabled,
    coverTitleOptions: Array.from(new Set([coverTitle, ...coverTitleOptions].filter(Boolean))),
    coverTitle,
    customCoverTitleEnabled,
    coverContext: draft.coverContext || draft.cover_context || result.cover_context || '',
    publishCopy: draft.description || draft.publish_copy || result.publish_copy || '',
    tags: selectedTags,
    customTags,
    tagOptions,
    newTag: '',
    summary: result.summary || '',
    chinaViewAngle: result.china_view_angle || ''
  }
}

const normalizeVideoItem = (item) => {
  const result = item.analysisResult || {}
  const draft = item.publishDraft && Object.keys(item.publishDraft).length > 0 ? item.publishDraft : result
  return {
    ...item,
    analysisDraft: Number(item.analysisStatus) === 1 ? buildAnalysisDraft(draft, result) : null
  }
}

const videoThumbnail = (item) => {
  const videoId = String(item?.id || '').trim()
  return videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : item?.thumbnail || ''
}

const showInlinePublishDraft = (item) => {
  return Number(item.analysisStatus) === 1 && item.analysisDraft
}

const isPublishDraftEditing = (item) => editingPublishDraftIds.value.has(item.id)

const cloneAnalysisDraft = (draft = {}) => ({
  titleOptions: [...(draft.titleOptions || [])],
  selectedTitle: draft.selectedTitle || '',
  customTitleEnabled: Boolean(draft.customTitleEnabled),
  coverTitleOptions: [...(draft.coverTitleOptions || [])],
  coverTitle: draft.coverTitle || '',
  customCoverTitleEnabled: Boolean(draft.customCoverTitleEnabled),
  coverContext: draft.coverContext || '',
  publishCopy: draft.publishCopy || '',
  tags: [...(draft.tags || [])],
  customTags: [...(draft.customTags || [])],
  tagOptions: [...(draft.tagOptions || [])],
  newTag: '',
  summary: draft.summary || '',
  chinaViewAngle: draft.chinaViewAngle || ''
})

const addDraftTag = (item) => {
  const draft = publishDraftForm(item)
  const tag = cleanTopicList(draft.newTag)[0] || ''
  if (!tag) {
    ElMessage.warning('请输入话题内容')
    return
  }
  if (draft.tags.includes(tag) || draft.customTags.includes(tag)) {
    ElMessage.warning('话题已存在')
    return
  }
  draft.customTags.push(tag)
  draft.newTag = ''
}

const removeDraftCustomTag = (item, tag) => {
  const draft = publishDraftForm(item)
  draft.customTags = draft.customTags.filter(itemTag => itemTag !== tag)
}

const handleTitleOptionChange = (item, value) => {
  const draft = publishDraftForm(item)
  if (value !== CUSTOM_TITLE_VALUE) {
    draft.selectedTitle = value || ''
    draft.customTitleEnabled = false
    return
  }
  customTitleDialogKind.value = 'title'
  customTitleDialogRow.value = item
  customTitlePrevious.value = draft.selectedTitle || ''
  customTitlePreviousEnabled.value = Boolean(draft.customTitleEnabled)
  customTitleDraft.value = draft.customTitleEnabled ? draft.selectedTitle : ''
  customTitleDialogVisible.value = true
}

const handleCoverTitleOptionChange = (item, value) => {
  const draft = publishDraftForm(item)
  if (value !== CUSTOM_COVER_TITLE_VALUE) {
    draft.coverTitle = value || ''
    draft.customCoverTitleEnabled = false
    return
  }
  draft.customCoverTitleEnabled = true
  draft.coverTitle = ''
}

const confirmCustomTitle = () => {
  const value = String(customTitleDraft.value || '').trim()
  if (!value) {
    ElMessage.warning('请输入自定义发布标题')
    return
  }
  const item = customTitleDialogRow.value
  const draft = item ? publishDraftForm(item) : null
  if (draft) {
    draft.selectedTitle = value
    draft.customTitleEnabled = true
    draft.titleOptions = Array.from(new Set([value, ...draft.titleOptions].filter(Boolean)))
  }
  customTitleDialogVisible.value = false
}

const cancelCustomTitle = () => {
  const item = customTitleDialogRow.value
  const draft = item ? publishDraftForm(item) : null
  if (draft) {
    draft.selectedTitle = customTitlePrevious.value
    draft.customTitleEnabled = customTitlePreviousEnabled.value
  }
  customTitleDialogVisible.value = false
}

const publishDraftForm = (item) => {
  if (!editingPublishDraftForms[item.id]) {
    editingPublishDraftForms[item.id] = cloneAnalysisDraft(item.analysisDraft || {})
  }
  return editingPublishDraftForms[item.id]
}

const startPublishDraftEditing = (item) => {
  editingPublishDraftForms[item.id] = cloneAnalysisDraft(item.analysisDraft || {})
  editingPublishDraftIds.value = new Set([...editingPublishDraftIds.value, item.id])
}

const stopPublishDraftEditing = (item) => {
  const nextIds = new Set(editingPublishDraftIds.value)
  nextIds.delete(item.id)
  editingPublishDraftIds.value = nextIds
  delete editingPublishDraftForms[item.id]
}

const cancelPublishDraftEditing = (item) => {
  stopPublishDraftEditing(item)
}

const currentStage = (item) => {
  const runningJob = activeJobForVideo(item)
  if (runningJob) {
    const stepMap = {
      queued: '排队中',
      download: '下载中',
      subtitle: '处理中',
      analysis: '分析中',
      publish: '发布中',
      done: '收尾中'
    }
    return { label: stepMap[runningJob.step] || '执行中', className: 'is-running' }
  }

  const latestJob = latestJobForVideo(item)
  if (isFailedJobRelevantToCurrentStage(item, latestJob)) {
    if (latestJob.status === 'abnormal') return { label: '任务异常', className: 'is-failed' }
    if (latestJob.status === 'failed') return { label: '任务失败', className: 'is-failed' }
  }
  if (!isDownloaded(item)) return { label: '待下载', className: 'is-pending' }
  if (!isTranslated(item) && !isTranslationSkipped(item)) return { label: '待处理', className: 'is-warning' }
  if (isTranslationSkipped(item)) return { label: '已跳过', className: 'is-warning' }
  if (item.publishDelivery?.status === 'uncertain') return { label: '发布待核验', className: 'is-warning' }
  if (item.publishDelivery?.status === 'partial') return { label: '部分发布', className: 'is-warning' }
  if (['failed', 'cancelled'].includes(item.publishDelivery?.status)) return { label: '发布失败', className: 'is-failed' }
  if (['queued', 'running', 'waiting_existing'].includes(item.publishDelivery?.status)) return { label: '发布中', className: 'is-running' }
  if (!isPublished(item)) return { label: '待发布', className: 'is-ready' }
  return { label: '已完成', className: 'is-complete' }
}

const rowWorkflowSteps = (item) => {
  const runningJob = activeJobForVideo(item)
  const runningStep = runningJob?.step || ''
  const latestJob = latestJobForVideo(item)
  const failed = isFailedJobRelevantToCurrentStage(item, latestJob)
  const steps = [
    { key: 'lead', label: '线索', done: true },
    { key: 'download', label: '下载', done: isDownloaded(item), running: runningStep === 'download' },
    {
      key: 'translate',
      label: isTranslationSkipped(item) ? '跳过' : '处理',
      done: isTranslated(item) || isTranslationSkipped(item),
      skipped: isTranslationSkipped(item),
      running: runningStep === 'subtitle' || runningStep === 'analysis'
    },
    {
      key: 'publish',
      label: '发布',
      done: ['confirmed', 'reused'].includes(item.publishDelivery?.status),
      running: runningStep === 'publish' || ['queued', 'running', 'waiting_existing'].includes(item.publishDelivery?.status),
      warning: ['partial', 'uncertain'].includes(item.publishDelivery?.status),
      failed: ['failed', 'cancelled'].includes(item.publishDelivery?.status)
    }
  ]
  return steps.map(step => ({
    ...step,
    className: {
      'is-done': step.done && !step.skipped,
      'is-running': step.running,
      'is-muted': !step.done && !step.running,
      'is-warning': step.skipped || step.warning,
      'is-failed': step.failed || (failed && step.key === 'publish')
    }
  }))
}

watch(
  () => [videoFilter.status, videoFilter.sort, videoFilter.groupId, videoFilter.keyword],
  () => {
    videoPagination.page = 1
    videoTableRef.value?.clearSelection?.()
    selectedVideos.value = []
    loadVideos(false, { force: true })
  }
)

watch(
  () => videoPagination.page,
  () => {
    loadVideos(false)
  }
)

const summaryStats = computed(() => {
  const summary = videoSummary.value || {}
  const total = Number(summary.total || videoTotal.value || 0)
  const pendingDownload = Number(summary.pendingDownload || 0)
  const pendingTranslate = Number(summary.pendingTranslate || 0)
  const readyPublish = Number(summary.readyPublish || 0)
  const running = Number(summary.running || 0)
  const completed = Number(summary.completed || 0)

  return [
    { label: '全部线索', value: total, meta: '当前入库', tone: 'tone-primary', filter: 'all' },
    { label: '待下载', value: pendingDownload, meta: pendingDownload ? '需要获取素材' : '无待下载', tone: 'tone-info', filter: 'initial' },
    { label: '待处理', value: pendingTranslate, meta: pendingTranslate ? '需要处理素材' : '无待处理', tone: 'tone-warning', filter: 'downloaded' },
    { label: '待发布', value: readyPublish, meta: readyPublish ? '可进入发布' : '无待发布', tone: 'tone-ready', filter: 'processed' },
    { label: '运行中', value: running, meta: running ? '执行中' : '暂无队列', tone: 'tone-running', filter: 'running' },
    { label: '已完成', value: completed, meta: completed ? '已发布' : '等待完成', tone: 'tone-success', filter: 'published' }
  ]
})

const pipelineStages = computed(() => [
  { label: '导入/查询', value: `${Number(videoSummary.value?.total || videoTotal.value || 0)} 条线索`, icon: Search },
  { label: '下载', value: `${Number(videoSummary.value?.downloaded || 0)} 个素材`, icon: Download },
  { label: '处理', value: `${Number(videoSummary.value?.translated || 0)} 条完成`, icon: VideoCamera },
  { label: '发布', value: `${Number(videoSummary.value?.completed || 0)} 条完成`, icon: VideoPlay }
])

const searchProgressPercent = computed(() => {
  if (!searchProgress.requested) return 0
  return Math.min(100, Math.round((searchProgress.found / searchProgress.requested) * 100))
})

const searchProgressSummary = computed(() => {
  const parts = [
    `已检索 ${searchProgress.found} / ${searchProgress.requested}`,
    `新增 ${searchProgress.created}`,
    `重复 ${searchProgress.duplicate}`
  ]
  if (searchProgress.skipped > 0) parts.push(`跳过 ${searchProgress.skipped}`)
  if (searchProgress.failed > 0) parts.push(`失败 ${searchProgress.failed}`)
  return parts.join(' · ')
})

const searchProgressStatus = computed(() => {
  if (searchProgress.status === 'failed') return 'exception'
  if (searchProgress.status === 'success') return 'success'
  return undefined
})

const applySearchJobProgress = (job = {}) => {
  searchProgress.jobId = String(job.jobId || searchProgress.jobId || '')
  searchProgress.found = Number(job.found || 0)
  searchProgress.requested = Number(job.requested || searchProgress.requested || 0)
  searchProgress.created = Number(job.created || 0)
  searchProgress.duplicate = Number(job.duplicate || 0)
  searchProgress.skipped = Number(job.skipped || 0)
  searchProgress.failed = Number(job.failed || 0)
  searchProgress.status = String(job.status || '')
  searchProgress.message = job.message || '正在查询候选视频'
  lastResult.value = job
}

const coverTitleOptionLabel = (title) => String(title || '').replace(/\r?\n/g, ' / ')

const stopSearchJobPolling = () => {
  if (searchJobTimer) {
    window.clearTimeout(searchJobTimer)
    searchJobTimer = null
  }
}

const scheduleSearchJobPoll = (jobId, delay = SEARCH_JOB_POLL_MS) => {
  stopSearchJobPolling()
  searchJobTimer = window.setTimeout(() => pollSearchJob(jobId), delay)
}

const finishSearchJobPolling = (job) => {
  stopSearchJobPolling()
  searchLoading.value = false
  videoGroupStore.invalidateRelatedCaches()
  void videoGroupStore.load({ force: true })
  if (job.status === 'failed') {
    notificationStore.addSearchFailureMessage(job)
    ElMessage.error(job.message || '关键词查询失败')
    return
  }
  const warnings = []
  if (Number(job.skipped || 0) > 0) warnings.push(`跳过 ${job.skipped} 条`)
  if (Number(job.failed || 0) > 0) warnings.push(`失败 ${job.failed} 条`)
  if (warnings.length > 0) {
    ElMessage.warning(`查询完成，新增 ${job.created || 0} 条，${warnings.join('，')}`)
  } else {
    showImportResultMessage(job, '查询完成')
  }
}

const pollSearchJob = async (jobId) => {
  if (!jobId || jobId !== searchProgress.jobId || searchJobRequesting) return
  searchJobRequesting = true
  const previousFound = searchProgress.found
  try {
    const res = await youtubeApi.getSearchJob(jobId)
    const job = res.data || {}
    searchJobPollFailures = 0
    applySearchJobProgress(job)
    const terminal = ['success', 'failed'].includes(job.status)
    if (searchProgress.found !== previousFound || terminal) {
      try {
        await loadVideos(false, { force: true })
      } catch (refreshError) {
        console.warn('查询进度对应的候选列表刷新失败', refreshError)
      }
    }
    if (terminal) {
      finishSearchJobPolling(job)
    } else {
      scheduleSearchJobPoll(jobId)
    }
  } catch (error) {
    searchJobPollFailures += 1
    searchProgress.message = '查询仍在后台执行，正在重新获取进度'
    if (searchJobPollFailures >= 3) {
      searchLoading.value = false
      searchProgress.status = 'failed'
      searchProgress.message = '连续读取查询进度失败，请稍后刷新页面确认结果'
      stopSearchJobPolling()
    } else {
      scheduleSearchJobPoll(jobId)
    }
  } finally {
    searchJobRequesting = false
  }
}

const handleSearch = async () => {
  if (searchLoading.value) return
  const query = form.query.trim()
  if (!query) {
    ElMessage.warning('请输入英文关键词')
    return
  }
  searchLoading.value = true
  stopSearchJobPolling()
  searchProgress.visible = true
  searchProgress.jobId = ''
  searchProgress.found = 0
  searchProgress.requested = Number(form.limit || 0)
  searchProgress.created = 0
  searchProgress.duplicate = 0
  searchProgress.skipped = 0
  searchProgress.failed = 0
  searchProgress.status = 'queued'
  searchProgress.message = '正在提交查询任务'
  try {
    const res = await youtubeApi.createSearchJob({
      query,
      limit: form.limit,
      groupId: form.groupId || undefined
    })
    applySearchJobProgress(res.data || {})
    searchProgress.message = res.data?.message || '查询任务已提交'
    scheduleSearchJobPoll(searchProgress.jobId, 100)
  } catch (error) {
    searchLoading.value = false
    searchProgress.status = 'failed'
    searchProgress.message = '查询失败，请检查网络或关键词后重试'
  }
}

const setStatusFilter = (filter) => {
  videoFilter.status = filter
  router.replace({ path: route.path, query: { ...route.query, status: filter === 'all' ? undefined : filter } })
  nextTick(() => videoListSectionRef.value?.$el?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

const scanLocalRetention = async () => {
  retentionScanning.value = true
  try {
    const res = await youtubeApi.scanLocalRetention()
    const result = res?.data || {}
    appStore.clearListCache('youtube:videos:')
    await loadVideos(false, { force: true })
    const overdueCount = Number(result.overdueCount || 0)
    const movedCount = Number(result.purgedCount || 0) + Number(result.repairedCount || 0)
    if (overdueCount > 0) {
      ElMessage.warning(`扫描完成，仍有 ${overdueCount} 条符合留存期限的视频未清理`)
    } else {
      ElMessage.success(`扫描完成，已清理或移入历史线索 ${movedCount} 条`)
    }
  } catch (error) {
    ElMessage.error(error?.message || '扫描本地留存失败')
  } finally {
    retentionScanning.value = false
  }
}

const handleVideoSelectionChange = (rows) => {
  selectedVideos.value = rows
}

const moveRowsToGroup = async (rows, groupId) => {
  const videoIds = rows.map(row => row.id).filter(Boolean)
  if (!videoIds.length) return
  const result = await videoGroupStore.moveVideos(videoIds, groupId)
  videoTableRef.value?.clearSelection?.()
  selectedVideos.value = []
  await loadVideos(false, { force: true })
  if (items.value.length === 0 && videoPagination.page > 1) {
    videoPagination.page -= 1
  }
  ElMessage.success(`已移动 ${result.movedCount || 0} 条线索`)
}

const moveSelectedVideos = (groupId) => moveRowsToGroup(selectedVideos.value, groupId)
const moveVideoToGroup = (row, groupId) => moveRowsToGroup([row], groupId)
const openMoveVideoDialog = (row) => {
  movingVideo.value = row
  moveTargetGroupId.value = ''
  moveVideoDialogVisible.value = true
}
const confirmMoveVideo = async () => {
  if (!moveTargetGroupId.value) {
    ElMessage.warning('请选择目标分组')
    return
  }
  movingVideoGroup.value = true
  try {
    await moveVideoToGroup(movingVideo.value, moveTargetGroupId.value)
    moveVideoDialogVisible.value = false
  } finally {
    movingVideoGroup.value = false
  }
}

const importVideo = async () => {
  const url = manualForm.url.trim()
  if (!url) {
    ElMessage.warning('请先粘贴 YouTube 视频链接')
    return
  }
  importing.value = true
  try {
    const res = await youtubeApi.importVideo({ url, groupId: manualForm.groupId || undefined })
    lastResult.value = res.data
    manualForm.url = ''
    videoGroupStore.invalidateRelatedCaches()
    await videoGroupStore.load({ force: true })
    await loadVideos(false, { force: true })
    showImportResultMessage(res.data, '导入完成')
  } finally {
    importing.value = false
  }
}

const showImportResultMessage = (result = {}, title = '处理完成') => {
  const created = Number(result.created ?? result.total ?? 0)
  const duplicate = Number(result.duplicate || 0)
  const publishedDuplicate = Number(result.publishedDuplicate || 0)

  if (publishedDuplicate > 0) {
    ElMessage.warning(`${title}，${publishedDuplicate} 条已发布链接已跳过，实际导入 ${created} 条视频`)
    return
  }
  if (duplicate > 0) {
    ElMessage.warning(`${title}，发现 ${duplicate} 条重复链接，实际导入 ${created} 条视频`)
    return
  }

  ElMessage.success(`${title}，实际导入 ${created} 条视频`)
}

const uniqueValues = (values = []) => Array.from(new Set(values.filter(Boolean).map(value => String(value))))

const videoCacheKey = (params) => `youtube:videos:${JSON.stringify(params)}`

const applyVideoPage = (payload = {}) => {
  items.value = (payload.items || []).map(normalizeVideoItem)
  videoTotal.value = Number(payload.total || 0)
  videoPagination.page = Number(payload.page || videoPagination.page)
  videoPagination.pageSize = Number(payload.pageSize || videoPagination.pageSize)
  videoSummary.value = payload.summary || videoSummary.value || {}
}

const loadVideos = async (showLoading = true, options = {}) => {
    const params = {
    page: videoPagination.page,
    pageSize: videoPagination.pageSize,
    status: videoFilter.status,
    sort: videoFilter.sort,
    storageScope: historyMode.value ? 'history' : 'active',
    groupId: videoFilter.groupId || undefined,
    keyword: videoFilter.keyword.trim() || undefined
  }
  const cacheKey = videoCacheKey(params)
  if (!options.force && !options.ids) {
    const cached = appStore.getListCache(cacheKey)
    if (cached) {
      applyVideoPage(cached)
      showLoading = false
    }
  }

  if (showLoading) loading.value = true
  try {
    const res = await youtubeApi.list(params)
    applyVideoPage(res.data || {})
    appStore.setListCache(cacheKey, res.data || {})
  } finally {
    if (showLoading) loading.value = false
  }
}

const refreshVideosByIds = async (videoIds = []) => {
  const ids = uniqueValues(videoIds)
  if (ids.length === 0) return null
  try {
    const res = await youtubeApi.list({
      ids: ids.join(','),
      storageScope: historyMode.value ? 'history' : 'active',
      page: 1,
      pageSize: Math.min(ids.length, 100)
    })
    const nextItems = (res.data?.items || []).map(normalizeVideoItem)
    const nextMap = new Map(nextItems.map(item => [String(item.id), item]))
    items.value = items.value.map(item => nextMap.get(String(item.id)) || item)
    if (res.data?.summary) {
      videoSummary.value = res.data.summary
    }
    return nextItems[0] || null
  } catch (error) {
    console.warn('局部刷新视频线索失败:', error)
    return null
  }
}

const loadJobs = async ({ silent = false, recentOnly = false } = {}) => {
  if (jobsRequesting) return []
  jobsRequesting = true
  if (!silent) jobsLoading.value = true
  try {
    const res = await youtubeApi.listWorkflowJobs({ page: 1, pageSize: 50, status: 'recent' })
    const nextJobs = res.data?.items || []
    const previousStatuses = new Map(jobs.value.map(job => [job.id, job.status]))
    const changedVideoIds = []

    nextJobs.forEach(job => {
      const previousStatus = previousStatuses.get(job.id)
      if (previousStatus && isRunningJob({ status: previousStatus }) && !isRunningJob(job)) {
        changedVideoIds.push(job.videoId)
      }
      if (isRunningJob(job) && ['subtitle', 'analysis', 'editing', 'publish', 'publish_confirmation'].includes(String(job.step || ''))) {
        changedVideoIds.push(job.videoId)
      }
    })

    nextJobs.forEach(job => {
      const previousStatus = previousStatuses.get(job.id)
      const popup = Boolean(previousStatus && previousStatus !== job.status)
      if (job.status === 'failed') {
        const handledAsUploadPaused = notificationStore.addPublishUploadPausedMessage(job, { popup })
        if (!handledAsUploadPaused) notificationStore.addWorkflowFailureMessage(job, { popup })
      }
      if (job.status === 'abnormal') notificationStore.addWorkflowAbnormalMessage(job, { popup })
    })
    notificationStore.syncPublishConfirmationMessages(nextJobs)

    jobs.value = nextJobs
    promptPendingPublishConfirmations(nextJobs)
    return uniqueValues(changedVideoIds)
  } finally {
    jobsRequesting = false
    if (!silent) jobsLoading.value = false
  }
}

const publishConfirmationDialogIds = new Set()

const resolveWorkflowPublishConfirmation = async (job, confirmed) => {
  const response = await youtubeApi.confirmWorkflowPublish(job.id, confirmed)
  if (confirmed) {
    ElMessage.success('已确认内容风险，任务将继续发布')
  } else {
    ElMessage.info('已取消发布，处理后视频已保留到素材库')
  }
  const changedVideoIds = await loadJobs({ silent: true, recentOnly: true })
  refreshVideosByIds([...changedVideoIds, job.videoId])
  return response
}

const promptPendingPublishConfirmations = (workflowJobs = []) => {
  workflowJobs
    .filter(job => job.status === 'waiting_confirmation' && job.publishConfirmationRequired)
    .forEach(job => {
      if (publishConfirmationDialogIds.has(job.id)) return
      publishConfirmationDialogIds.add(job.id)
      void (async () => {
        try {
          await ElMessageBox.confirm(
            '检测到转写中含明确粗口，中文字幕已打码，但原声及原音识别文本可能仍含风险。是否继续发布？',
            '发布前内容确认',
            {
              confirmButtonText: '继续发布',
              cancelButtonText: '暂不发布',
              type: 'warning',
              closeOnClickModal: false,
              closeOnPressEscape: false
            }
          )
          await resolveWorkflowPublishConfirmation(job, true)
        } catch (action) {
          if (action === 'cancel' || action === 'close') {
            try {
              await resolveWorkflowPublishConfirmation(job, false)
            } catch (error) {
              ElMessage.error(error?.response?.data?.msg || error.message || '取消发布失败')
            }
          } else if (action) {
            ElMessage.error(action?.response?.data?.msg || action.message || '处理发布确认失败')
          }
        } finally {
          publishConfirmationDialogIds.delete(job.id)
        }
      })()
    })
}

const startJobsPolling = () => {
  if (jobsTimer) return
  const poll = async () => {
    const hasRunning = jobs.value.some(isRunningJob) || Number(videoSummary.value?.running || 0) > 0
    try {
      if (hasRunning) {
        const changedVideoIds = await loadJobs({ silent: true, recentOnly: true })
        refreshVideosByIds(changedVideoIds)
      } else {
        await loadJobs({ silent: true, recentOnly: true })
      }
    } finally {
      jobsTimer = window.setTimeout(poll, hasRunning ? JOBS_POLL_ACTIVE_MS : JOBS_POLL_IDLE_MS)
    }
  }
  jobsTimer = window.setTimeout(poll, JOBS_POLL_ACTIVE_MS)
}

const hasActiveWorkflowJobs = () => jobs.value.some(isRunningJob)

const handleBeforeUnload = (event) => {
  if (!hasActiveWorkflowJobs()) return
  event.preventDefault()
  event.returnValue = '当前有任务正在执行，关闭页面不会停止后端任务，但如果后端服务被关闭，任务会被标记异常。'
}

const startClock = () => {
  if (clockTimer) return
  clockTimer = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
}

const parseJobTime = (value) => {
  const time = Date.parse(value || '')
  return Number.isNaN(time) ? 0 : time
}

const formatDuration = (seconds) => {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0))
  const minutes = Math.floor(safeSeconds / 60)
  const remainSeconds = safeSeconds % 60
  if (minutes <= 0) return `${remainSeconds}s`
  return `${minutes}m${String(remainSeconds).padStart(2, '0')}s`
}

const displayProgress = (job) => {
  const rawProgress = Number(job.progress || 0)
  const publishProgress = job.publishProgress || {}
  const publishTotal = Number(publishProgress.total || 0)
  const publishCompleted = Number(publishProgress.completed || 0)
  const boundedProgress = Math.max(0, Math.min(100, rawProgress))
  if (job.step === 'publish' && publishTotal > 0) {
    return Math.round(Math.min(publishCompleted, publishTotal) * 100 / publishTotal)
  }
  if (job.status !== 'running') return boundedProgress
  return Math.max(0, Math.min(99, boundedProgress))
}

const workflowProgressText = (job = {}) => {
  const progress = job.publishProgress || {}
  if (Number(progress.total || 0) > 0) {
    const completed = Number(progress.completed || 0)
    const total = Number(progress.total || 0)
    return job.status === 'waiting_publish' ? `发布排队中 - ${completed} / ${total}` : `发布中 - ${completed} / ${total}`
  }
  return job.message || jobStatusText(job.status, job.step)
}

const jobTimeText = (job) => {
  const createdAt = parseJobTime(job.createdAt)
  if (job.status === 'queued') {
    return createdAt ? `排队 ${formatDuration((nowTick.value - createdAt) / 1000)}` : '等待执行'
  }

  const startedAt = parseJobTime(job.startedAt)
  const executionStartedAt = startedAt || createdAt
  if (!executionStartedAt) return job.status === 'running' ? '计时中' : '-'

  const endedAt = job.status === 'running'
    ? nowTick.value
    : (parseJobTime(job.updatedAt) || nowTick.value)
  const elapsedSeconds = (endedAt - executionStartedAt) / 1000

  if (job.status !== 'running') {
    return `${startedAt ? '耗时' : '总历时'} ${formatDuration(elapsedSeconds)}`
  }

  if (job.step === 'download' && job.eta) {
    return `已用 ${formatDuration(elapsedSeconds)} / 剩余约 ${job.eta}`
  }
  return `已用 ${formatDuration(elapsedSeconds)}`
}

const confirmReplacingCurrentVersion = async (row) => {
  if (!hasCurrentProcessVersion(row) || workflowForm.processVersion === 'editing_v1') {
    return true
  }
  try {
    await ElMessageBox.confirm(
      `该视频已存在${processVersionLabel(workflowForm.processVersion)}成品。继续处理会在成功后替换该版本旧成品，失败时旧成品会保留。`,
      '替换处理版本',
      {
        confirmButtonText: '继续处理',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    return true
  } catch (error) {
    return false
  }
}

const pendingWorkflowPublishPlatforms = (row) => {
  const publishedTypes = new Set((row.publishedPlatforms || []).map(platform => Number(platform.type)))
  return workflowPublishPlatforms.filter(item => Boolean(workflowForm[item.enabledKey]) && !publishedTypes.has({ douyin: 3, bilibili: 5, xiaohongshu: 1, kuaishou: 4, tencent: 2 }[item.key]))
}

const validateWorkflowPublishAccounts = async (row) => {
  const enabledPlatforms = pendingWorkflowPublishPlatforms(row)

  if (enabledPlatforms.length === 0) {
    await ElMessageBox.alert(
      '当前选择的平台都已有发布记录。请先在视频线索的已发布标签或发布中心删除对应本地记录，再重新发布。',
      '没有可发布的平台',
      {
        confirmButtonText: '去设置',
        type: 'warning'
      }
    )
    return false
  }

  for (const item of enabledPlatforms) {
    const accountName = String(workflowForm[item.accountKey] || '').trim()
    if (!accountName) {
      await ElMessageBox.alert(
        `已开启发${item.label}，但还没有选择正常的${item.label}账号。请先在下拉框选择账号后再一键发布。`,
        `缺少${item.label}账号`,
        {
          confirmButtonText: '去设置',
          type: 'warning'
        }
      )
      return false
    }
    if (!isNormalAccountName(item.platform, accountName)) {
      await ElMessageBox.alert(
        `当前${item.label}账号不存在或状态异常，请在账号管理中重新连接后再选择。`,
        `${item.label}账号不可用`,
        {
          confirmButtonText: '去设置',
          type: 'warning'
        }
      )
      return false
    }
  }

  return true
}

const createJob = async (row) => {
  const latestRow = await refreshVideosByIds([row.id])
  row = latestRow || row
  if (!(await validateWorkflowPublishAccounts(row))) return
  const pendingPlatforms = new Set(pendingWorkflowPublishPlatforms(row).map(item => item.key))
  const shouldProcessBeforePublish = !(isTranslated(row) || isTranslationSkipped(row))
  if (shouldProcessBeforePublish && !(await confirmReplacingCurrentVersion(row))) return
  creatingJobId.value = row.id
  try {
    const res = await youtubeApi.createWorkflowJob({
      videoId: row.id,
      url: row.url,
      publishAccountGroupId: workflowForm.publishAccountGroupId || undefined,
      account: workflowForm.account.trim(),
      publishToDouyin: pendingPlatforms.has('douyin'),
      publishToBilibili: pendingPlatforms.has('bilibili'),
      bilibiliAccount: workflowForm.bilibiliAccount.trim(),
      bilibiliTid: workflowForm.bilibiliTid,
      publishToXiaohongshu: pendingPlatforms.has('xiaohongshu'),
      xiaohongshuAccount: workflowForm.xiaohongshuAccount.trim(),
      publishToKuaishou: pendingPlatforms.has('kuaishou'),
      kuaishouAccount: workflowForm.kuaishouAccount.trim(),
      publishToTencent: pendingPlatforms.has('tencent'),
      tencentAccount: workflowForm.tencentAccount.trim(),
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      description: '',
      schedule: '',
      processVersion: workflowForm.processVersion,
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel,
      coverTitle: row.analysisDraft?.coverTitle || '',
      coverSignature: workflowForm.coverSignature,
      watermarkEnabled: workflowForm.watermarkEnabled,
      watermarkText: workflowForm.watermarkText,
      subtitleMode: workflowForm.subtitleMode,
      translationEnabled: workflowForm.translationEnabled,
      highlightIntroEnabled: workflowForm.highlightIntroEnabled,
      coverIntroEnabled: workflowForm.coverIntroEnabled,
      commentBurnEnabled: workflowForm.commentBurnEnabled,
      subtitleMaskEnabled: workflowForm.subtitleMaskEnabled,
      commentBurnCount: workflowForm.commentBurnCount,
      commentTranslationMode: workflowForm.commentTranslationMode,
      contentSafetyReviewEnabled: workflowForm.contentSafetyReviewEnabled
    })
    const existingIndex = jobs.value.findIndex(job => String(job.id) === String(res.data?.id))
    if (existingIndex >= 0) jobs.value[existingIndex] = res.data
    else jobs.value.unshift(res.data)
    ElMessage.success('一键发布任务已创建')
    startJobsPolling()
    refreshVideosByIds([row.id])
  } finally {
    creatingJobId.value = ''
  }
}

const downloadVideo = async (row) => {
  if (row.downloadStatus === 1) {
    ElMessage.info('该视频已下载')
    return
  }
  downloadingId.value = row.id
  try {
    const res = await youtubeApi.createDownloadJob({
      videoId: row.id,
      url: row.url,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频'
    })
    jobs.value.unshift(res.data)
    ElMessage.success('下载任务已创建')
    startJobsPolling()
    setTimeout(async () => {
      const changedVideoIds = await loadJobs({ silent: true, recentOnly: true })
      refreshVideosByIds([...changedVideoIds, row.id])
    }, 1500)
  } finally {
    downloadingId.value = ''
  }
}

const deleteVideo = async (row) => {
  const blockReason = deleteBlockReason(row)
  if (blockReason) {
    ElMessage.warning(blockReason)
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除视频线索「${row.title || row.url}」吗？只有下载视频和处理后视频都不存在时才能删除线索；如果仍有关联视频，系统会阻止删除并提示原因。`,
      '删除视频线索',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (error) {
    return
  }

  deletingId.value = row.id
  try {
    await youtubeApi.deleteVideo(row.id)
    items.value = items.value.filter(item => item.id !== row.id)
    videoTotal.value = Math.max(0, videoTotal.value - 1)
    if (videoSummary.value?.total) {
      videoSummary.value = {
        ...videoSummary.value,
        total: Math.max(0, Number(videoSummary.value.total || 0) - 1)
      }
    }
    ElMessage.success('视频线索已删除')
  } catch (error) {
    console.warn('删除视频线索失败:', error)
  } finally {
    deletingId.value = ''
  }
}

const batchDeleteVideos = async () => {
  const selectedRows = [...selectedVideos.value]
  if (selectedRows.length === 0) {
    ElMessage.warning('请先选择要删除的视频线索')
    return
  }

  const blockedRows = selectedRows
    .map(row => ({ row, reason: deleteBlockReason(row) }))
    .filter(item => item.reason)

  if (blockedRows.length > 0) {
    await showDeleteBlockedDetails(blockedRows, '批量删除受限')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedRows.length} 条视频线索吗？删除后线索数据将不存在；如果仍有关联下载视频或处理后视频，请先到视频素材页删除文件后再删除线索。`,
      '批量删除视频线索',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (error) {
    return
  }

  batchDeleting.value = true
  try {
    const res = await youtubeApi.deleteVideos(selectedRows.map(row => row.id))
    const successItems = (res.data?.items || []).filter(item => item.success)
    const successCount = Number(res.data?.success ?? successItems.length)
    const failedCount = Number(res.data?.failed ?? 0)
    const deletedIds = new Set(successItems.map(item => String(item.videoId)))

    if (deletedIds.size > 0) {
      items.value = items.value.filter(item => !deletedIds.has(String(item.id)))
      videoTotal.value = Math.max(0, videoTotal.value - deletedIds.size)
      if (videoSummary.value?.total) {
        videoSummary.value = {
          ...videoSummary.value,
          total: Math.max(0, Number(videoSummary.value.total || 0) - deletedIds.size)
        }
      }
    }
    selectedVideos.value = []
    videoTableRef.value?.clearSelection?.()

    if (failedCount > 0) {
      const failedItems = (res.data?.items || [])
        .filter(item => !item.success)
        .map(item => ({
          row: selectedRows.find(row => String(row.id) === String(item.videoId)) || { id: item.videoId },
          reason: item.message || '请先删除对应视频后再试。'
        }))
      ElMessage.warning(`已删除 ${successCount} 条，${failedCount} 条未删除`)
      await showDeleteBlockedDetails(failedItems, '部分线索未删除')
    } else {
      ElMessage.success(`批量删除成功，共删除 ${successCount} 条`)
    }
  } catch (error) {
    console.warn('批量删除视频线索失败:', error)
  } finally {
    batchDeleting.value = false
  }
}

const resetProcessing = (row) => {
  if (activeJobForVideo(row)) {
    ElMessage.warning('该视频还有任务执行中，结束后再重新处理')
    return
  }
  resetTarget.value = row
  refreshTranscriptOnReset.value = false
  resetDialogVisible.value = true
}

const confirmResetProcessing = async () => {
  const row = resetTarget.value
  if (!row) return
  resettingId.value = row.id
  try {
    const res = await youtubeApi.resetProcessing(row.id, {
      deleteProcessed: true,
      processVersion: workflowForm.processVersion,
      refreshTranscript: refreshTranscriptOnReset.value
    })
    const updatedVideo = res.data.video
    items.value = items.value.map(item => item.id === row.id ? normalizeVideoItem(updatedVideo) : item)
    await refreshVideosByIds([row.id])
    await loadJobs({ silent: true })
    resetDialogVisible.value = false
    ElMessage.success(refreshTranscriptOnReset.value ? '已删除成品和转写缓存，可重新处理' : '已删除成品，重新处理时将复用现有转写')
  } finally {
    resettingId.value = ''
  }
}

const deletePublishedPlatform = async (row, platform) => {
  if (!platform.recordId) return
  try {
    await ElMessageBox.confirm(
      `确认删除「${platform.name}」的本地发布记录？不会删除平台上的视频，删除后可重新发布。`,
      '删除本地发布记录',
      { confirmButtonText: '删除记录', cancelButtonText: '取消', type: 'warning' }
    )
    const response = await materialApi.deletePublishTargetRecord(platform.recordId)
    row.publishedPlatforms = (row.publishedPlatforms || []).filter(item => item.recordId !== platform.recordId)
    row.publishStatus = Number(response.data?.publishStatus || 0)
    appStore.invalidatePublishRecords(response.data?.videoId || row.id)
    ElMessage.success(response.msg || '已删除本地发布记录')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  }
}

const handleAnalysisAction = async (row) => {
  if (activeAnalysisJobForVideo(row) || Number(row.analysisStatus) === 2) {
    ElMessage.info('发布文案正在生成中')
    return
  }
  if (Number(row.analysisStatus) === 3) {
    await createAnalysisJob(row)
    return
  }
  if (row.hasAnalysis || Number(row.analysisStatus) === 1) {
    await showAnalysis(row)
    return
  }
  await createAnalysisJob(row)
}

const createAnalysisJob = async (row, force = false) => {
  if (row.downloadStatus !== 1) {
    ElMessage.warning('请先下载视频，再生成发布文案')
    return
  }
  analyzingId.value = row.id
  try {
    const res = await youtubeApi.createAnalysisJob({
      videoId: row.id,
      url: row.url,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      processVersion: 'editing_v1',
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel,
      coverTitle: row.analysisDraft?.coverTitle || '',
      coverSignature: workflowForm.coverSignature,
      watermarkEnabled: workflowForm.watermarkEnabled,
      watermarkText: workflowForm.watermarkText,
      highlightCount: workflowForm.highlightCount,
      force
    })
    jobs.value.unshift(res.data)
    items.value = items.value.map(item => item.id === row.id ? { ...item, analysisStatus: 2, hasAnalysis: false, analysisDraft: null } : item)
    ElMessage.success(Number(row.analysisStatus) === 3 ? '发布文案重新生成任务已创建' : '发布文案生成任务已创建')
    startJobsPolling()
    refreshVideosByIds([row.id])
  } finally {
    analyzingId.value = ''
  }
}

const regenerateAnalysis = async (row) => {
  try {
    await ElMessageBox.confirm(
      '重新生成会更新内容分析和建议，已手工保存的发布稿将继续保留。',
      '重新生成发布文案',
      { type: 'warning', confirmButtonText: '重新生成', cancelButtonText: '取消' }
    )
    analysisDialogVisible.value = false
    await createAnalysisJob(row, true)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  }
}

const showAnalysis = async (row) => {
  currentAnalysisRow.value = row
  analysisDialogVisible.value = true
  analysisLoading.value = true
  analysisResult.value = null
  analysisStatus.value = 0
  try {
    const res = await youtubeApi.getVideoAnalysis(row.id)
    analysisStatus.value = Number(res.data.status || 0)
    analysisResult.value = res.data.result || null
    row.analysisResult = res.data.result || row.analysisResult || {}
    row.publishDraft = res.data.draft || row.publishDraft || {}
    row.analysisDraft = Number(res.data.status || 0) === 1
      ? buildAnalysisDraft(row.publishDraft && Object.keys(row.publishDraft).length > 0 ? row.publishDraft : row.analysisResult, row.analysisResult)
      : row.analysisDraft
    if (!analysisResult.value || analysisStatus.value === 0) {
      ElMessage.info('该视频还没有生成发布文案')
    } else if (analysisStatus.value === 3) {
      ElMessage.warning('发布文案生成失败，可重新生成')
    }
  } finally {
    analysisLoading.value = false
  }
}

const analysisErrorText = computed(() => {
  const error = analysisResult.value?.error || {}
  return error.reason || '模型配置、网络请求或转写内容可能存在问题，请检查后重试。'
})

const saveInlineAnalysis = async (row) => {
  if (!row.analysisDraft) return
  const form = publishDraftForm(row)
  if (form.customCoverTitleEnabled) {
    const coverTitle = String(form.coverTitle || '').replace(/\r\n/g, '\n').trim()
    const coverLines = coverTitle.split('\n').map(line => line.trim()).filter(Boolean)
    if (coverLines.length !== 2) {
      ElMessage.warning('自定义封面标题需要填写两行内容')
      return
    }
    if (coverTitle.length > 25) {
      ElMessage.warning('封面标题不能超过 25 个字符')
      return
    }
  }
  savingAnalysisId.value = row.id
  try {
    const nextTitleOptions = form.selectedTitle
      ? Array.from(new Set([form.selectedTitle, ...form.titleOptions].filter(Boolean)))
      : form.titleOptions.filter(Boolean)
    const payload = {
      title: form.selectedTitle || nextTitleOptions[0] || '',
      coverTitle: form.coverTitle || '',
      coverContext: form.coverContext || '',
      description: form.publishCopy || '',
      tags: cleanTopicList(form.tags),
      customTags: cleanTopicList(form.customTags).filter(tag => !form.tags.includes(tag))
    }
    const response = await youtubeApi.updatePublishDraft(row.id, payload)
    const savedDraft = response.data?.draft || payload
    row.publishDraft = savedDraft
    row.analysisDraft = buildAnalysisDraft(savedDraft, row.analysisResult || {})
    stopPublishDraftEditing(row)
    await refreshVideosByIds([row.id])
    ElMessage.success('发布稿已保存')
  } finally {
    savingAnalysisId.value = ''
  }
}

const processVideo = async (row) => {
  if (row.downloadStatus !== 1) {
    ElMessage.warning('请先下载视频，再进行处理')
    return
  }
  if (!(await confirmReplacingCurrentVersion(row))) return
  translatingId.value = row.id
  try {
    const payload = {
      videoId: row.id,
      url: row.url,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      processVersion: workflowForm.processVersion,
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel,
      coverTitle: row.analysisDraft?.coverTitle || '',
      coverSignature: workflowForm.coverSignature,
      watermarkEnabled: workflowForm.watermarkEnabled,
      watermarkText: workflowForm.watermarkText,
      highlightCount: workflowForm.highlightCount,
      subtitleMode: workflowForm.subtitleMode,
      translationEnabled: workflowForm.translationEnabled,
      highlightIntroEnabled: workflowForm.highlightIntroEnabled,
      coverIntroEnabled: workflowForm.coverIntroEnabled,
      commentBurnEnabled: workflowForm.commentBurnEnabled,
      subtitleMaskEnabled: workflowForm.subtitleMaskEnabled,
      commentBurnCount: workflowForm.commentBurnCount,
      commentTranslationMode: workflowForm.commentTranslationMode,
      contentSafetyReviewEnabled: workflowForm.contentSafetyReviewEnabled
    }
    const res = await youtubeApi.createTranslateJob(payload)
    jobs.value.unshift(res.data)
    ElMessage.success(workflowForm.processVersion === 'editing_v1' ? '剪辑处理任务已创建' : '处理任务已创建')
    startJobsPolling()
    setTimeout(async () => {
      const changedVideoIds = await loadJobs({ silent: true, recentOnly: true })
      refreshVideosByIds([...changedVideoIds, row.id])
    }, 1500)
  } catch (error) {
    const message = error?.message || '创建处理任务失败'
    if (message.includes('2K 高画质（需 2K 原片）仅支持')) {
      await ElMessageBox.alert(message, '无法创建 2K 处理任务', { type: 'warning', confirmButtonText: '知道了' })
    } else {
      ElMessage.error(message)
    }
  } finally {
    translatingId.value = ''
  }
}

const formatSegmentRange = (segment) => {
  const format = (value) => {
    const totalSeconds = Math.max(0, Math.floor(Number(value || 0)))
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    return `${minutes}:${String(seconds).padStart(2, '0')}`
  }
  return `${format(segment.start)} - ${format(segment.end)}`
}

const updateEditingIntro = async (row) => {
  const coverOnly = needsCoverReburn(row)
  translatingId.value = row.id
  try {
    const res = await youtubeApi.createEditingIntroJob({
      videoId: row.id, url: row.url, channel: row.channel, subscribers: row.subscribers,
      publishedAt: row.publishedAt, title: row.title || 'YouTube 视频', processVersion: 'editing_v1',
      operation: coverOnly ? 'cover_reburn' : 'intro_refresh',
      subtitleLanguage: workflowForm.subtitleLanguage, burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize, translatorLabel: workflowForm.translatorLabel,
      coverTitle: row.analysisDraft?.coverTitle || '', coverSignature: workflowForm.coverSignature,
      watermarkEnabled: workflowForm.watermarkEnabled, watermarkText: workflowForm.watermarkText,
      highlightCount: workflowForm.highlightCount, highlightIntroEnabled: workflowForm.highlightIntroEnabled,
      coverIntroEnabled: workflowForm.coverIntroEnabled,
      commentBurnEnabled: workflowForm.commentBurnEnabled,
      subtitleMode: workflowForm.subtitleMode,
      subtitleMaskEnabled: workflowForm.subtitleMaskEnabled,
      commentBurnCount: workflowForm.commentBurnCount,
      commentTranslationMode: workflowForm.commentTranslationMode
    })
    jobs.value.unshift(res.data)
    ElMessage.success(coverOnly ? '封面重烧任务已创建' : '片头高光更新任务已创建')
    startJobsPolling()
  } finally {
    translatingId.value = ''
  }
}

const highlightCandidates = computed(() => {
  const result = analysisResult.value || {}
  return result.highlight_candidates || result.highlight_segments || []
})

const highlightSelection = (candidate) => {
  const selected = (analysisResult.value?.selected_highlight_segments || []).find((segment) => {
    if (candidate.candidateId && segment.candidateId) return candidate.candidateId === segment.candidateId
    return Number(candidate.start) === Number(segment.originalStart ?? segment.start)
      && Number(candidate.end) === Number(segment.originalEnd ?? segment.end)
  })
  return {
    selected: Boolean(selected),
    adjusted: Boolean(selected?.reviewAdjusted),
    score: Number.isFinite(Number(highlightReview(candidate).visionScore)) ? Number(highlightReview(candidate).visionScore) : null,
    segment: selected || candidate
  }
}

const highlightShortlist = (candidate) => {
  const selected = (analysisResult.value?.highlightReview?.shortlistedCandidates || []).find((item) => item.candidateId === candidate.candidateId)
  return {
    selected: Boolean(selected),
    rank: selected?.textShortlistRank || null,
    reason: selected?.textShortlistReason || ''
  }
}

const highlightReview = (candidate) => (analysisResult.value?.highlightReview?.reviewedCandidates || []).find((item) => item.candidateId === candidate.candidateId) || {}

const jobStatusText = (status, step = '') => {
  const map = {
    queued: '排队中',
    running: '执行中',
    waiting_confirmation: step === 'content_safety_confirm' ? '等待视频处理确认' : '等待发布确认',
    waiting_publish: '发布排队中',
    success: '成功',
    reused: '复用已有发布',
    partial: '部分完成',
    needs_verification: '发布待核验',
    failed: '失败',
    abnormal: step === 'publish_confirmation' ? '发布结果待核验' : '异常'
  }
  return map[status] || status || '-'
}

const jobStatusType = (status) => {
  const map = {
    queued: 'info',
    running: 'warning',
    waiting_confirmation: 'warning',
    waiting_publish: 'warning',
    success: 'success',
    reused: 'info',
    partial: 'warning',
    needs_verification: 'warning',
    failed: 'danger',
    abnormal: 'danger'
  }
  return map[status] || 'info'
}

const progressStatus = (job) => {
  const map = {
    success: 'success',
    reused: 'success',
    partial: 'exception',
    needs_verification: 'exception',
    failed: 'exception',
    abnormal: 'exception'
  }
  return map[job.status] || undefined
}

const translateStatusText = (status) => {
  const map = {
    1: '已处理',
    2: '已跳过'
  }
  return map[Number(status)] || '未处理'
}

const translateStatusType = (status) => {
  const map = {
    1: 'success',
    2: 'warning'
  }
  return map[Number(status)] || 'info'
}

const statusChipClass = (type, status) => {
  if (type === 'translate' && Number(status) === 2) return 'is-warning'
  return translateStatusType(status) === 'success' ? 'is-success' : 'is-muted'
}

const askAgentAboutVideo = (row) => {
  window.dispatchEvent(new CustomEvent('vidferry:ask-agent', {
    detail: {
      videoContext: {
        source: 'youtube-research',
        videoId: String(row?.id || ''),
        title: row?.chineseTitle || row?.title || '',
        originalTitle: row?.title || '',
        url: row?.url || '',
        channel: row?.channel || '',
        subscribers: row?.subscribers || '',
        sourcePublishedAt: row?.publishedAt || '',
        duration: row?.duration || '',
        processVersion: row?.processVersion || '',
        downloadStatus: Number(row?.downloadStatus || 0),
        translateStatus: Number(row?.translateStatus || 0),
        publishStatus: Number(row?.publishStatus || 0),
        publishedPlatforms: (row?.publishedPlatforms || []).map(platform => platform.name || '')
      }
    }
  }))
}

const copyUrl = async (url) => {
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

const copyText = async (text) => {
  if (!text) {
    ElMessage.warning('没有可复制的内容')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

const handleAgentLeadsImported = () => {
  loadVideos(false, { force: true })
}

const handleAgentPublishDraftUpdated = (event) => {
  const videoId = String(event?.detail?.videoId || '').trim()
  if (videoId) refreshVideosByIds([videoId])
}

onMounted(async () => {
  loadingWorkflowSettings = true
  await Promise.all([loadBilibiliCategories(), loadAccounts(), loadPublishAccountGroups(), videoGroupStore.load()])
  form.groupId = videoGroupStore.defaultGroupId || ''
  manualForm.groupId = videoGroupStore.defaultGroupId || ''
  await loadWorkflowSettings()
  syncWorkflowAccountSelections()
  await nextTick()
  loadingWorkflowSettings = false
  workflowSettingsLoaded = true
  await Promise.all([loadVideos(), loadJobs()])
  startJobsPolling()
  startClock()
  window.__VIDFERRY_OPEN_PROCESS_SETTINGS__ = openSettingsFromLayout
  await consumeOpenSettingsQuery()
  await consumeFocusJobQuery()
  consumeAgentStatusQuery()
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('vidferry:youtube-leads-imported', handleAgentLeadsImported)
  window.addEventListener('vidferry:youtube-publish-draft-updated', handleAgentPublishDraftUpdated)
})

watch(() => route.query.openSettings, () => {
  consumeOpenSettingsQuery()
})

watch(() => route.query.focusJob, () => {
  consumeFocusJobQuery()
})

watch(() => route.query.status, () => {
  consumeAgentStatusQuery()
})

watch(historyMode, () => {
  videoPagination.page = 1
  selectedVideos.value = []
  loadVideos(true, { force: true })
})

watch(() => appStore.publishRecordsRevision, () => {
  const videoId = appStore.lastChangedPublishedVideoId
  if (videoId) refreshVideosByIds([videoId])
  else loadVideos()
})

onBeforeUnmount(() => {
  if (window.__VIDFERRY_OPEN_PROCESS_SETTINGS__ === openSettingsFromLayout) {
    delete window.__VIDFERRY_OPEN_PROCESS_SETTINGS__
  }
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('vidferry:youtube-leads-imported', handleAgentLeadsImported)
  window.removeEventListener('vidferry:youtube-publish-draft-updated', handleAgentPublishDraftUpdated)
  if (jobsTimer) {
    window.clearTimeout(jobsTimer)
    jobsTimer = null
  }
  stopSearchJobPolling()
  if (clockTimer) {
    window.clearInterval(clockTimer)
    clockTimer = null
  }
  if (workflowSettingsSaveTimer) {
    window.clearTimeout(workflowSettingsSaveTimer)
    workflowSettingsSaveTimer = null
  }
  flushWorkflowSettings()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: var(--vf-border);
$panel-shadow: var(--vf-shadow-md);
$accent-blue: var(--vf-primary);
$accent-teal: var(--vf-success);
$accent-amber: #d97706;
$surface-soft: var(--vf-page-bg);
$ink-strong: var(--vf-text-primary);

.youtube-research {
  display: grid;
  gap: 16px;

  :deep(.el-card) {
    border: 1px solid $panel-border;
    border-radius: 8px;
    box-shadow: $panel-shadow;
  }

  :deep(.el-card__header) {
    padding: 14px 16px;
    border-bottom: 1px solid $border-lighter;
  }

  :deep(.el-card__body) {
    padding: 16px;
  }

  :deep(.el-form-item) {
    margin-bottom: 0;
  }

  :deep(.el-table th.el-table__cell) {
    background: var(--vf-surface-hover);
    color: var(--vf-text-regular);
    font-weight: 600;
  }

  :deep(.el-table td.el-table__cell) {
    padding: 10px 0;
  }
}

:deep(.delete-block-details) {
  p {
    margin: 0 0 10px;
    color: var(--vf-text-regular);
  }

  ol {
    display: grid;
    gap: 8px;
    margin: 0;
    padding-left: 20px;
  }

  li {
    color: $ink-strong;
    line-height: 1.5;
  }

  strong {
    display: block;
    margin-bottom: 2px;
    word-break: break-word;
  }

  span {
    display: block;
    color: $text-secondary;
    font-size: 13px;
    word-break: break-word;
  }
}

.workspace-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(460px, 1.4fr);
  gap: 16px;
  align-items: stretch;
  padding: 18px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: var(--vf-surface);
  box-shadow: $panel-shadow;
}

.hero-copy {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;

  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    max-width: 680px;
    color: var(--vf-text-regular);
    font-size: 14px;
    line-height: 1.7;
  }
}

.eyebrow,
.panel-kicker {
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  display: grid;
  gap: 4px;
  min-height: 92px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.82);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;

  &:hover,
  &.is-active {
    border-color: rgba(37, 99, 235, 0.45);
    box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12);
    transform: translateY(-1px);
  }

  strong {
    color: $ink-strong;
    font-size: 26px;
    line-height: 1;
  }

  &.tone-success {
    border-color: rgba(15, 159, 143, 0.2);
  }

  &.tone-warning {
    border-color: rgba(217, 119, 6, 0.2);
  }

  &.tone-running {
    border-color: rgba(37, 99, 235, 0.25);
  }

  &.tone-ready {
    border-color: rgba(124, 58, 237, 0.18);
  }
}

.metric-label {
  color: var(--vf-text-regular);
  font-size: 13px;
}

.metric-meta {
  color: $text-secondary;
  font-size: 12px;
}

.pipeline-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: $panel-border;
  box-shadow: 0 8px 18px rgba(28, 55, 90, 0.05);
}

.pipeline-stage {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 66px;
  padding: 12px 14px;
  background: var(--vf-surface);

  &:not(:last-child)::after {
    content: '';
    position: absolute;
    top: 50%;
    right: 12px;
    width: 18px;
    height: 1px;
    background: #b7c3d6;
  }

  strong {
    display: block;
    margin-top: 2px;
    color: $ink-strong;
    font-size: 13px;
  }
}

.stage-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  color: $accent-blue;
  background: rgba(37, 99, 235, 0.1);
}

.stage-label {
  color: $text-secondary;
  font-size: 12px;
}

.command-card {
  :deep(.el-card__body) {
    display: grid;
    gap: 14px;
  }
}

.command-header,
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  h2 {
    margin: 2px 0 0;
    color: $ink-strong;
    font-size: 18px;
    line-height: 1.3;
  }
}

.command-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(420px, 1.25fr);
  gap: 14px;
}

.entry-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: $surface-soft;
}

.entry-heading {
  display: flex;
  align-items: center;
  gap: 10px;

  > .el-icon {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 8px;
    color: #fff;
    background: $accent-blue;
  }

  h3 {
    margin: 0;
    color: $ink-strong;
    font-size: 15px;
    line-height: 1.3;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.import-panel .entry-heading > .el-icon {
  background: $accent-teal;
}

.entry-control {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
}

.import-panel .entry-control {
  grid-template-columns: minmax(0, 1fr) minmax(150px, 190px) auto;
}

.search-control {
  grid-template-columns: minmax(220px, 1fr) minmax(150px, 190px) 110px auto;
}

.keyword-field {
  grid-column: auto;
}

.keyword-presets {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;

  .el-button {
    margin: 0;
  }
}

.keyword-presets-label {
  color: $text-secondary;
  font-size: 12px;
}

.group-filter {
  width: 150px;
}

.search-progress-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: var(--vf-surface);
}

.search-progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  color: $text-secondary;
  font-size: 12px;

  span {
    min-width: 0;
  }

  strong {
    min-width: 0;
    color: $accent-blue;
    font-size: 13px;
    text-align: right;
  }
}

.limit-field {
  :deep(.el-input-number) {
    width: 100%;
  }
}


.workflow-config {
  display: grid;
  grid-template-columns: minmax(174px, 0.42fr) minmax(0, 1fr);
  align-items: start;
  gap: 12px 20px;
  padding: 12px;
  border: 1px solid #e2eaf5;
  border-radius: 8px;
  background: var(--vf-surface);
}

.config-title {
  display: grid;
  gap: 2px;
  flex: 0 0 auto;

  span:last-child {
    color: $text-secondary;
    font-size: 12px;
  }
}

.publish-config-controls {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.account-group-config,
.publish-platform-row,
.publish-account-fields {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.account-group-config {
  min-height: 32px;

  :deep(.el-select) {
    width: min(280px, 100%);
  }
}

.config-group-hint {
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.5;
}

.publish-platform-row {
  padding-top: 10px;
  border-top: 1px solid #edf2f8;
}

.publish-platform-label {
  flex: 0 0 auto;
  color: $text-secondary;
  font-size: 12px;
  font-weight: 650;
}

.publish-platform-switches {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.publish-account-fields {
  padding-left: 68px;
}

.config-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: $text-regular;
  font-size: 13px;
  white-space: nowrap;
}

.compact-input {
  width: 150px;
}

.tid-input {
  width: 220px;
}

.query-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  color: $text-secondary;
  font-size: 12px;
}

.data-panel {
  overflow: hidden;
}

.panel-count {
  color: $text-secondary;
  font-size: 13px;
}

.list-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.job-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 14px 4px 2px;
}

.status-select {
  width: 132px;
}

.sort-select {
  width: 128px;
}

.job-status-select {
  width: 120px;
}

.video-cell {
  display: grid;
  grid-template-columns: 116px minmax(0, 1fr);
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.thumbnail {
  width: 116px;
  height: 65px;
  object-fit: cover;
  border-radius: 6px;
  background: $border-extra-light;
  flex: 0 0 auto;
}

.thumbnail-empty {
  display: grid;
  place-items: center;
  color: $text-secondary;
  border: 1px dashed $border-base;
}

.video-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: nowrap;
  overflow: hidden;
}

.stage-badge {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  height: 24px;
  padding: 0 8px;
  border: 1px solid #d5deec;
  border-radius: 6px;
  color: #69758a;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 600;

  &.is-running {
    color: #1d4ed8;
    border-color: rgba(37, 99, 235, 0.26);
    background: rgba(37, 99, 235, 0.1);
  }

  &.is-warning {
    color: $accent-amber;
    border-color: rgba(217, 119, 6, 0.24);
    background: rgba(245, 158, 11, 0.12);
  }

  &.is-ready {
    color: #6d28d9;
    border-color: rgba(109, 40, 217, 0.22);
    background: rgba(124, 58, 237, 0.1);
  }

  &.is-complete {
    color: #047857;
    border-color: rgba(4, 120, 87, 0.22);
    background: rgba(16, 185, 129, 0.1);
  }

  &.is-failed {
    color: #b91c1c;
    border-color: rgba(185, 28, 28, 0.24);
    background: rgba(239, 68, 68, 0.1);
  }
}

.stage-badge-button {
  cursor: pointer;
  font-family: inherit;

  &:hover {
    filter: brightness(0.97);
    box-shadow: 0 0 0 3px rgba(185, 28, 28, 0.08);
  }
}

.video-title {
  display: block;
  min-width: 0;
  color: $ink-strong;
  font-weight: 650;
  line-height: 1.45;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    color: $accent-blue;
  }
}

.video-title-stack {
  display: grid;
  flex: 1 1 96px;
  min-width: 0;
  gap: 2px;
}

.video-original-title {
  min-width: 0;
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-detail-trigger {
  flex: 0 0 auto;
  color: #64748b;

  &:hover,
  &:focus-visible {
    color: $accent-blue;
  }
}

.job-error-detail {
  display: grid;
  gap: 10px;
}

.detail-row {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 10px 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface-hover);

  > span {
    color: $text-secondary;
    font-size: 13px;
    font-weight: 650;
  }

  strong,
  p,
  code {
    margin: 0;
    color: $ink-strong;
    font-size: 13px;
    line-height: 1.6;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

.publish-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;

  span {
    flex: 0 0 auto;
    color: #ef4444;
    font-size: 13px;
    font-weight: 700;
  }

  strong {
    min-width: 0;
    color: #b91c1c;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.45;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.video-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  color: #6b7484;
  font-size: 12px;

  span {
    display: inline-flex;
    align-items: center;

    &:not(:last-child)::after {
      content: '';
      width: 3px;
      height: 3px;
      margin-left: 8px;
      border-radius: 50%;
      background: #b7c3d6;
    }
  }
}

.video-url {
  max-width: 560px;
  color: $text-secondary;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-cluster {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.workflow-track {
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
}

.processed-version-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: $text-secondary;
  font-size: 12px;
}

.workflow-step {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  color: #8a94a6;
  font-size: 12px;
  font-weight: 600;

  &:not(:last-child) {
    padding-right: 18px;
  }

  &:not(:last-child)::after {
    content: '';
    position: absolute;
    right: 5px;
    width: 8px;
    height: 1px;
    background: #ccd6e5;
  }

  &.is-done {
    color: #047857;

    .step-dot,
    &::after {
      background: #10b981;
    }
  }

  &.is-running {
    color: #1d4ed8;

    .step-dot {
      background: #2563eb;
      box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12);
    }
  }

  &.is-warning {
    color: $accent-amber;

    .step-dot {
      background: #f59e0b;
    }
  }

  &.is-failed {
    color: #b91c1c;

    .step-dot {
      background: #ef4444;
    }
  }
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c8d2e2;
  flex: 0 0 auto;
}

.inline-job {
  display: grid;
  grid-template-columns: minmax(0, 256px) minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: min(100%, 560px);
  padding: 6px 8px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 6px;
  color: #4b5a70;
  background: var(--vf-surface-hover);
  font-size: 12px;

  :deep(.el-progress) {
    width: 100%;
    min-width: 0;
  }

  .inline-job-status {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.processing-settings-trigger {
  flex: 0 0 auto;
  color: #2563eb;
}

.processing-settings-popover {
  color: $text-regular;

  strong {
    display: block;
    margin-bottom: 8px;
    color: $ink-strong;
    font-size: 13px;
  }

  dl {
    display: grid;
    grid-template-columns: 94px minmax(0, 1fr);
    gap: 6px 10px;
    margin: 0;
    font-size: 12px;
    line-height: 1.45;
  }

  dt { color: $text-secondary; }
  dd { min-width: 0; margin: 0; color: $ink-strong; overflow-wrap: anywhere; }
}

.analysis-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  max-width: 360px;
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid #d5deec;
  color: #69758a;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 600;

  &.is-running {
    color: #1d4ed8;
    border-color: rgba(37, 99, 235, 0.26);
    background: rgba(37, 99, 235, 0.1);
  }

  &.is-ready {
    color: #047857;
    border-color: rgba(4, 120, 87, 0.22);
    background: rgba(16, 185, 129, 0.1);
  }

  &.is-failed {
    color: #b91c1c;
    border-color: rgba(185, 28, 28, 0.24);
    background: rgba(239, 68, 68, 0.1);
  }

  :deep(.el-button) {
    min-height: 20px;
    padding: 2px 4px;
    color: inherit;
    font-size: 12px;
    font-weight: 650;
  }
}

.video-detail-panel {
  display: grid;
  gap: 18px;
}

.video-detail-section {
  display: grid;
  gap: 8px;

  :deep(.el-descriptions__label) {
    color: $text-secondary;
    font-weight: 600;
  }

  :deep(.el-descriptions__content) {
    color: $ink-strong;
    overflow-wrap: anywhere;
  }
}

.video-detail-link {
  color: $accent-blue;
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.detail-job-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 6px;
  background: var(--vf-surface-hover);
  color: $text-regular;
  font-size: 12px;

  span {
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.detail-settings-list,
.detail-target-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.detail-target-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: $text-secondary;
  font-size: 12px;
}

.detail-subtitle-loading,
.detail-subtitle-reason {
  padding: 8px 10px;
  border-radius: 4px;
  color: $text-secondary;
  background: var(--vf-surface-hover);
  font-size: 12px;
  line-height: 1.5;
}

.detail-settings-list span {
  padding: 3px 6px;
  border-radius: 4px;
  color: $text-regular;
  background: var(--vf-surface-hover);
  font-size: 12px;
}

.processed-version-details {
  display: grid;
  gap: 8px;
}

.processed-version-detail {
  display: flex;
  align-items: center;
  gap: 6px 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid $border-lighter;
  border-radius: 6px;
  background: var(--vf-surface-hover);
  color: $text-regular;
  font-size: 12px;

  strong {
    color: $ink-strong;
    font-size: 13px;
  }
}

.detail-publish-draft {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid rgba(4, 120, 87, 0.16);
  border-radius: 6px;
  background: rgba(16, 185, 129, 0.06);

  strong {
    color: $ink-strong;
    font-size: 14px;
  }

  p {
    margin: 0;
    color: $text-regular;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.processed-preview-container {
  display: flex;
  justify-content: center;
  min-height: 180px;
  background: #101820;
}

.processed-preview-video {
  display: block;
  width: 100%;
  max-height: 70vh;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid #d5deec;
  color: #69758a;
  background: #f8fafc;
  font-size: 12px;
  line-height: 1;

  &.is-success {
    color: #047857;
    border-color: rgba(4, 120, 87, 0.22);
    background: rgba(16, 185, 129, 0.1);
  }

  &.is-warning {
    color: $accent-amber;
    border-color: rgba(217, 119, 6, 0.22);
    background: rgba(245, 158, 11, 0.12);
  }
}

.action-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;

  :deep(.el-button + .el-button) {
    margin-left: 0;
  }
}

.more-button {
  color: $text-secondary;
}

.reset-processing-dialog {
  display: grid;
  gap: 14px;
  color: $text-regular;

  p { margin: 0; line-height: 1.7; }
  > span { color: $text-secondary; font-size: 12px; line-height: 1.6; }
}

:deep(.danger-item) {
  color: $danger-color;
}

.job-card {
  margin-bottom: 4px;
}

:deep(.job-row-focused > td.el-table__cell) {
  background: #fff7df !important;
  box-shadow: inset 3px 0 0 #d8a10d;
}

.settings-panel {
  min-height: 356px;
}

:global(.process-settings-dialog) {
  max-width: calc(100vw - 32px);

  .el-dialog__body {
    padding: 22px 28px 18px;
  }

  .el-dialog__footer {
    padding: 14px 28px 20px;

    .el-button {
      min-height: 40px;
      padding: 0 24px;
    }
  }
}

.settings-section {
  display: grid;
  gap: 18px;
}

.process-settings-tabs {
  :deep(.el-tabs__header) {
    margin: 0 0 26px;
  }

  :deep(.el-tabs__nav-wrap::after) {
    height: 1px;
    background: #dbe5f1;
  }

  :deep(.el-tabs__item) {
    height: 42px;
    padding: 0 22px;
    color: #66758a;
    font-size: 15px;
    font-weight: 600;
  }

  :deep(.el-tabs__item.is-active) {
    color: #1769aa;
  }

  :deep(.el-tabs__active-bar) {
    height: 3px;
    border-radius: 2px;
    background: #169c98;
  }

  :deep(.el-input__wrapper),
  :deep(.el-select__wrapper) {
    min-height: 42px;
    padding: 1px 14px;
  }
}

.settings-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 28px;
}

.settings-span-full {
  grid-column: 1 / -1;
}

.cover-title-fields {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.cover-draft-value {
  white-space: pre-line;
}

.cover-settings {
  max-width: 680px;
  margin: 2px auto 0;
}

.cover-signature-preview {
  min-height: 72px;
  padding: 22px;
  border-left: 3px solid #d8a10d;
  background: #f7f8fa;
  color: #182735;
  font-size: 22px;
  font-weight: 700;
}

.cover-analysis-preview {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.cover-analysis-preview p {
  margin: 0;
  padding: 10px 12px;
  border-left: 3px solid #d8a10d;
  background: #f7f8fa;
}

.watermark-settings {
  max-width: 680px;
  margin: 2px auto 0;
}

.watermark-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 76px;
  padding: 0 22px;
  border-left: 3px solid #169c98;
  background: #f1f9f8;
}

.setting-hint {
  display: block;
  margin-top: 5px;
  color: $text-secondary;
  font-size: 13px;
}

.setting-status {
  padding-top: 2px;
  color: #39708a;
  font-size: 14px;
  font-weight: 600;
}

.watermark-preview {
  position: relative;
  display: flex;
  justify-content: flex-end;
  align-items: flex-start;
  height: 144px;
  padding: 26px 32px;
  overflow: hidden;
  border: 1px solid #d7e7e5;
  background: #f1f7f7;

  span {
    color: rgba(23, 45, 62, 0.30);
    font-size: 22px;
    font-weight: 700;
    transform: rotate(-15deg);
  }

  &.is-muted span {
    opacity: 0.35;
  }
}

.settings-section-header {
  display: grid;
  gap: 2px;

  h3 {
    margin: 0;
    color: $ink-strong;
    font-size: 16px;
    line-height: 1.35;
  }
}

.settings-field {
  display: grid;
  gap: 10px;
}

.settings-label {
  color: $text-regular;
  font-size: 14px;
  font-weight: 600;
}

.process-version-select {
  width: 100%;
}

.version-note {
  display: grid;
  gap: 8px;
  padding: 16px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: #f7faff;

  strong {
    color: $ink-strong;
    font-size: 15px;
  }

  span {
    color: $text-secondary;
    font-size: 14px;
    line-height: 1.6;
  }
}

.param-info-button {
  color: $text-secondary;

  &:hover {
    color: $accent-blue;
  }
}

.version-note-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

:global(.profile-popover) {
  display: grid;
  gap: 10px;
  color: #4b5a70;
  font-size: 12px;
  line-height: 1.6;

  p {
    margin: 0;
  }

  dl {
    display: grid;
    gap: 8px;
    margin: 0;
  }

  dt {
    color: var(--vf-text-primary);
    font-weight: 700;
  }

  dd {
    margin: 2px 0 0;
  }
}

.analysis-panel {
  display: grid;
  gap: 14px;
  width: 100%;
  min-width: 0;
  min-height: 180px;
}

.analysis-section {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 14px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: var(--vf-surface-hover);

  h3 {
    margin: 0;
    color: $ink-strong;
    font-size: 16px;
    line-height: 1.35;
  }

  p {
    margin: 0;
    color: #4b5a70;
    font-size: 13px;
    line-height: 1.7;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

.analysis-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.analysis-muted {
  color: $text-secondary;
}

.title-options,
.tag-list,
.risk-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.title-options :deep(.el-tag),
.tag-list :deep(.el-tag),
.risk-list :deep(.el-tag) {
  max-width: 100%;
  height: auto;
  min-height: 24px;
  white-space: normal;
  line-height: 1.45;
}

.publish-copy {
  padding: 10px;
  border-radius: 8px;
  background: var(--vf-surface);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.publish-draft-card {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 8px;
  width: 100%;
  max-width: none;
  min-width: 0;
  box-sizing: border-box;
  padding: 10px;
  border: 1px solid var(--vf-border);
  border-radius: 8px;
  background: var(--vf-surface-hover);
}

.publish-draft-card.is-editing {
  width: 100%;
  max-width: none;
  min-width: 0;
  padding: 12px;
  border-color: var(--vf-primary);
  background: var(--vf-surface);
  box-shadow: var(--vf-shadow-md);
}

.draft-editor-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  min-width: 0;
}

.draft-editor-primary {
  display: grid;
  gap: 10px;
  align-content: start;
  min-width: 0;
}

.draft-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 4px;
  align-items: start;
}

.topic-add-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  margin-top: 4px;
}

.draft-field-label {
  display: grid;
  gap: 2px;
  padding-top: 6px;
  min-width: 0;

  span {
    color: var(--vf-text-primary);
    font-size: 12px;
    font-weight: 700;
  }

  small {
    color: var(--vf-text-secondary);
    font-size: 10px;
    line-height: 1.45;
  }
}

.draft-description-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  min-width: 0;

  .draft-field-label {
    padding-top: 0;
  }

  :deep(.el-textarea__inner) {
    min-height: 190px !important;
    resize: vertical;
    line-height: 1.6;
  }
}

.publish-draft-card.is-editing :deep(.el-select),
.publish-draft-card.is-editing :deep(.el-input),
.publish-draft-card.is-editing :deep(.el-textarea) {
  width: 100%;
}

.publish-draft-card.is-editing :deep(.el-select__wrapper) {
  min-height: 36px;
}

.draft-readonly {
  display: grid;
  gap: 8px;
  min-width: 0;

  strong,
  p {
    min-width: 0;
    margin: 0;
    color: var(--vf-text-primary);
    font-size: 13px;
    line-height: 1.55;
    overflow-wrap: anywhere;
  }

  p {
    color: var(--vf-text-regular);
  }
}

.draft-readonly-compact {
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: 6px;
  padding: 2px 0;

  .draft-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .draft-summary strong,
  .draft-summary-copy {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .draft-summary-tags {
    flex: 0 0 auto;
    color: $text-secondary;
    font-size: 11px;
  }

  .draft-summary-copy {
    color: $text-secondary;
    font-size: 12px;
    line-height: 1.55;
    white-space: normal;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 5;
  }
}

.draft-content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  min-width: 0;

  > div {
    display: grid;
    gap: 4px;
    min-width: 0;
  }
}

.draft-label {
  color: var(--vf-primary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.55;
  white-space: nowrap;
}

.draft-topic-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
  color: $text-secondary;
  font-size: 12px;
}

.draft-summary {
  color: #4b5a70;
  font-size: 12px;
  line-height: 1.6;
}

.draft-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.highlight-list {
  display: grid;
  gap: 8px;
}

.highlight-item {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--vf-border);
  border-radius: 8px;
  background: var(--vf-surface);
}

.highlight-item.is-selected {
  border-color: #8ed2aa;
  box-shadow: inset 3px 0 0 #28a86b;
}

.highlight-time {
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;
}

.highlight-body {
  display: grid;
  gap: 5px;
  min-width: 0;

  strong {
    color: $ink-strong;
    font-size: 14px;
    line-height: 1.45;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  p {
    margin: 0;
    color: #4b5a70;
    font-size: 13px;
    line-height: 1.6;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

.highlight-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.highlight-markers {
  display: inline-flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}

.highlight-adjustment {
  color: #a86c12 !important;
}

.error-code {
  color: #b42318;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  font-weight: 700;
}

@media (max-width: 1200px) {
  .workspace-hero,
  .command-grid {
    grid-template-columns: 1fr;
  }

  .metric-strip {
    grid-template-columns: repeat(4, minmax(130px, 1fr));
  }

  .video-title {
    order: -1;
    min-width: 48px;
    flex-basis: 48px;
  }

}

@media (max-width: 1400px) {
  .draft-editor-grid {
    grid-template-columns: 1fr;
  }

  .draft-description-panel :deep(.el-textarea__inner) {
    min-height: 150px !important;
  }
}

@media (max-width: 900px) {
  .metric-strip,
  .pipeline-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pipeline-stage:not(:last-child)::after {
    display: none;
  }

  .entry-control,
  .import-panel .entry-control,
  .search-control {
    grid-template-columns: 1fr;
  }

  .keyword-field {
    grid-column: auto;
  }

  .group-filter {
    width: 100%;
  }

  .workflow-config {
    grid-template-columns: 1fr;
  }

  .publish-account-fields {
    padding-left: 0;
    width: 100%;
  }

  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .list-tools,
  .job-tools {
    justify-content: flex-start;
    width: 100%;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}

@media (max-width: 640px) {
  .settings-panel {
    min-height: 0;
  }

  .process-settings-tabs {
    :deep(.el-tabs__item) {
      padding: 0 10px;
      font-size: 13px;
    }
  }

  .settings-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .settings-span-full {
    grid-column: auto;
  }

  .workspace-hero {
    padding: 14px;
  }

  .hero-copy h1 {
    font-size: 22px;
  }

  .metric-strip,
  .pipeline-strip {
    grid-template-columns: 1fr;
  }

  .compact-input,
  .tid-input {
    width: 100%;
  }

  .account-group-config,
  .publish-platform-row,
  .publish-account-fields,
  .publish-platform-switches {
    align-items: flex-start;
    width: 100%;
  }

  .publish-platform-row {
    display: grid;
    gap: 8px;
  }

  .publish-platform-switches {
    gap: 10px 14px;
  }

  .publish-draft-card {
    max-width: none;
  }

  .status-select,
  .sort-select,
  .job-status-select {
    width: 100%;
  }

  .highlight-item {
    grid-template-columns: 1fr;
  }

  .video-cell {
    align-items: flex-start;
    grid-template-columns: 96px minmax(0, 1fr);
  }

  .thumbnail {
    width: 96px;
    height: 54px;
  }

  .publish-draft-card {
    grid-column: 1 / -1;
    grid-row: auto;
  }

  .video-url {
    max-width: 330px;
  }

  .publish-draft-card.is-editing {
    width: 100%;
    min-width: 0;
  }

  .draft-editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>
