<template>
  <div class="youtube-research">
    <section class="workspace-hero">
      <div class="hero-copy">
        <span class="eyebrow">VIDFERRY PIPELINE</span>
        <h1>Vidferry 视频采集处理</h1>
        <p>集中管理 YouTube 视频线索，按链接导入、批量查询、下载处理，并跟踪后续发布任务。</p>
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
            <el-form-item label="搜索关键词" class="keyword-field">
              <el-input
                v-model="form.query"
                clearable
                placeholder="foreigner China travel vlog first time in China"
              />
            </el-form-item>
            <el-form-item label="数量" class="limit-field">
              <el-input-number v-model="form.limit" :min="1" :max="30" controls-position="right" />
            </el-form-item>
            <el-button type="primary" :loading="loading" @click="handleSearch">
              <el-icon><Search /></el-icon>
              <span>开始查询</span>
            </el-button>
          </div>
          <div v-if="searchProgress.visible" class="search-progress-panel">
            <div class="search-progress-text">
              <span>{{ searchProgress.message }}</span>
              <strong>{{ searchProgress.loaded }} / {{ searchProgress.total }}</strong>
            </div>
            <el-progress :percentage="searchProgressPercent" :stroke-width="8" :status="loading ? undefined : 'success'" />
          </div>
        </div>
      </el-form>

      <div class="workflow-config">
        <div class="config-title">
          <span class="panel-kicker">任务默认配置</span>
          <span>用于下载后创建处理任务</span>
        </div>
        <div class="config-items">
          <label class="config-item">
            <span>发抖音</span>
            <el-switch v-model="workflowForm.publishToDouyin" />
          </label>
          <el-input
            v-if="workflowForm.publishToDouyin"
            v-model="workflowForm.account"
            class="compact-input"
            clearable
            placeholder="抖音账号"
          />
          <label class="config-item">
            <span>发B站</span>
            <el-switch v-model="workflowForm.publishToBilibili" />
          </label>
          <el-input
            v-if="workflowForm.publishToBilibili"
            v-model="workflowForm.bilibiliAccount"
            class="compact-input"
            clearable
            placeholder="B站账号"
          />
          <el-input-number
            v-if="workflowForm.publishToBilibili"
            v-model="workflowForm.bilibiliTid"
            :min="1"
            :max="999"
            controls-position="right"
            class="tid-input"
          />
          <el-input
            v-model="workflowForm.tags"
            class="tag-input"
            clearable
            placeholder="默认话题：中国旅行,外国人在中国"
          />
        </div>
      </div>

      <div class="query-meta" v-if="lastResult">
        <span>来源：{{ lastResult.source }}</span>
        <span>查询时间：{{ lastResult.searchedAt }}</span>
        <span>入库/更新：{{ lastResult.total }}</span>
      </div>
    </el-card>

    <el-card class="result-card data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">线索列表</span>
            <h2>候选视频</h2>
          </div>
          <div class="list-tools">
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="selectedVideos.length === 0"
              @click="batchDeleteVideos"
            >
              批量删除 {{ selectedVideos.length || '' }}
            </el-button>
            <el-select v-model="videoFilter.status" class="status-select" size="small" aria-label="显示状态">
              <el-option label="全部状态" value="all" />
              <el-option label="未下载" value="notDownloaded" />
              <el-option label="已下载" value="downloaded" />
              <el-option label="未处理" value="notTranslated" />
              <el-option label="已处理" value="translated" />
              <el-option label="已跳过处理" value="translationSkipped" />
              <el-option label="未发布" value="notPublished" />
              <el-option label="已发布" value="published" />
              <el-option label="运行中" value="running" />
            </el-select>
            <el-select v-model="videoFilter.sort" class="sort-select" size="small" aria-label="排序方式">
              <el-option label="默认顺序" value="default" />
              <el-option label="待处理优先" value="pendingFirst" />
              <el-option label="已下载优先" value="downloadedFirst" />
              <el-option label="已处理优先" value="translatedFirst" />
              <el-option label="已发布优先" value="publishedFirst" />
            </el-select>
            <span class="panel-count">第 {{ videoPagination.page }} 页 · {{ filteredItems.length }} / {{ items.length }} 条</span>
          </div>
        </div>
      </template>

      <el-table
        :data="pagedItems"
        v-loading="loading"
        empty-text="暂无匹配的视频记录"
        class="research-table"
        style="width: 100%"
        @selection-change="handleVideoSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="视频" min-width="420">
          <template #default="{ row }">
            <div class="video-cell">
              <img v-if="row.thumbnail" :src="row.thumbnail" alt="" class="thumbnail">
              <div v-else class="thumbnail thumbnail-empty">
                <el-icon><VideoCamera /></el-icon>
              </div>
              <div class="video-info">
                <div class="title-line">
                  <span class="stage-badge" :class="currentStage(row).className">{{ currentStage(row).label }}</span>
                  <a :href="row.url" target="_blank" rel="noopener noreferrer" class="video-title">
                    {{ row.title || '未获取到标题' }}
                  </a>
                </div>
                <div v-if="showInlinePublishDraft(row) && !isPublishDraftEditing(row)" class="publish-title-line">
                  <span></span>
                  <strong>{{ row.analysisDraft.selectedTitle || '暂无发布标题' }}</strong>
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
                <div v-if="activeJobForVideo(row)" class="inline-job">
                  <el-progress :percentage="displayProgress(activeJobForVideo(row))" :stroke-width="6" />
                  <span>{{ activeJobForVideo(row).message || jobStatusText(activeJobForVideo(row).status) }}</span>
                </div>
                <div v-else-if="analysisHint(row)" class="analysis-hint" :class="analysisHint(row).className">
                  {{ analysisHint(row).label }}
                </div>
                <span class="video-url">{{ row.url }}</span>
              </div>
              <div
                v-if="showInlinePublishDraft(row)"
                class="publish-draft-card"
                :class="{ 'is-editing': isPublishDraftEditing(row) }"
              >
                  <template v-if="isPublishDraftEditing(row)">
                    <div class="draft-editor-grid">
                      <div class="draft-editor-primary">
                        <div class="draft-row">
                          <span>标题</span>
                          <el-select v-model="row.analysisDraft.selectedTitle" placeholder="选择或编辑标题" filterable allow-create default-first-option>
                            <el-option
                              v-for="title in row.analysisDraft.titleOptions"
                              :key="title"
                              :label="title"
                              :value="title"
                            />
                          </el-select>
                        </div>
                        <div class="draft-row">
                          <span>话题</span>
                          <el-select v-model="row.analysisDraft.tags" multiple filterable allow-create default-first-option placeholder="选择或新增话题">
                            <el-option
                              v-for="tag in row.analysisDraft.tagOptions"
                              :key="tag"
                              :label="tag"
                              :value="tag"
                            />
                          </el-select>
                        </div>
                      </div>
                      <div class="draft-row draft-description-row">
                        <span>描述</span>
                        <el-input v-model="row.analysisDraft.publishCopy" type="textarea" :rows="5" maxlength="500" show-word-limit />
                      </div>
                    </div>
                  </template>
                  <template v-else>
                    <div class="draft-readonly">
                      <div class="draft-content-grid">
                        <div>
                          <span class="draft-label">文案</span>
                          <p>{{ row.analysisDraft.publishCopy || '暂无发布文案' }}</p>
                        </div>
                        <div>
                          <span class="draft-label">话题</span>
                          <div class="draft-topic-tags">
                            <el-tag v-for="tag in row.analysisDraft.tags" :key="tag" size="small" type="success" effect="plain">#{{ tag }}</el-tag>
                            <span v-if="row.analysisDraft.tags.length === 0">暂无话题</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </template>
                  <div class="draft-actions">
                    <el-button
                      v-if="isPublishDraftEditing(row)"
                      size="small"
                      type="primary"
                      text
                      :loading="savingAnalysisId === row.id"
                      @click="saveInlineAnalysis(row)"
                    >
                      保存修改
                    </el-button>
                    <el-button v-else size="small" type="primary" text @click="startPublishDraftEditing(row)">编辑文案</el-button>
                    <el-button size="small" text @click="showAnalysis(row)">查看详情</el-button>
                  </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260">
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
              <el-button
                v-if="row.downloadStatus === 1"
                size="small"
                type="warning"
                :disabled="row.downloadStatus !== 1"
                :loading="translatingId === row.id"
                @click="processVideo(row)"
              >
                <el-icon><VideoCamera /></el-icon>
                <span>{{ hasCurrentProcessVersion(row) ? '替换处理' : '处理' }}</span>
              </el-button>
              <el-button
                size="small"
                type="success"
                plain
                :loading="creatingJobId === row.id"
                @click="createJob(row)"
              >
                <el-icon><VideoPlay /></el-icon>
                <span>一键处理</span>
              </el-button>
              <el-dropdown trigger="click">
                <el-button size="small" text class="more-button">
                  更多
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="copyUrl(row.url)">
                      <el-icon><DocumentCopy /></el-icon>
                      <span>复制链接</span>
                    </el-dropdown-item>
                    <el-dropdown-item @click="handleAnalysisAction(row)">
                      <el-icon><VideoPlay /></el-icon>
                      <span v-if="analyzingId === row.id">生成中</span>
                      <span v-else>{{ analysisActionText(row) }}</span>
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-if="Number(row.translateStatus) === 1 || Number(row.translateStatus) === 2"
                      @click="resetProcessing(row)"
                    >
                      <el-icon><Refresh /></el-icon>
                      <span>{{ resettingId === row.id ? '回退中' : '重新处理' }}</span>
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
      <div class="table-pagination" v-if="filteredItems.length > videoPagination.pageSize">
        <el-pagination
          v-model:current-page="videoPagination.page"
          :page-size="videoPagination.pageSize"
          :total="filteredItems.length"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>

    <el-card class="job-card data-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <div>
            <span class="panel-kicker">任务监控</span>
            <h2>工作流任务</h2>
          </div>
          <div class="job-tools">
            <el-select v-model="jobFilter.status" class="job-status-select" size="small" aria-label="任务状态筛选">
              <el-option label="全部任务" value="all" />
              <el-option label="执行中" value="running" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="异常" value="abnormal" />
            </el-select>
            <span class="panel-count">第 {{ jobPagination.page }} 页 · {{ filteredJobs.length }} / {{ jobs.length }} 个</span>
            <el-button text type="primary" :loading="jobsLoading" @click="loadJobs()">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="pagedJobs" empty-text="暂无匹配任务" class="job-table" style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="account" label="抖音账号" width="110" />
        <el-table-column prop="status" label="状态" width="105">
          <template #default="{ row }">
            <el-tag :type="jobStatusType(row.status)" effect="light">{{ jobStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="step" label="步骤" width="110" />
        <el-table-column label="进度" width="190">
          <template #default="{ row }">
            <el-progress :percentage="displayProgress(row)" :stroke-width="8" :status="progressStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column label="耗时/预计" width="150">
          <template #default="{ row }">
            {{ jobTimeText(row) }}
          </template>
        </el-table-column>
        <el-table-column label="速率" width="115">
          <template #default="{ row }">
            {{ row.speed || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="剩余" width="90">
          <template #default="{ row }">
            {{ row.eta || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" min-width="240" show-overflow-tooltip />
        <el-table-column label="异常编号" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.errorCode" class="error-code">{{ row.errorCode }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="updatedAt" label="更新时间" width="165" />
      </el-table>
      <div class="table-pagination" v-if="filteredJobs.length > jobPagination.pageSize">
        <el-pagination
          v-model:current-page="jobPagination.page"
          :page-size="jobPagination.pageSize"
          :total="filteredJobs.length"
          layout="total, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>

    <el-dialog
      v-model="settingsDialogVisible"
      title="设置"
      width="460px"
      class="process-settings-dialog"
    >
      <div class="settings-panel">
        <div class="settings-section">
          <div class="settings-section-header">
            <span class="panel-kicker">基础设置</span>
            <h3>处理方式</h3>
          </div>
        <div class="settings-field">
          <span class="settings-label">字幕语言</span>
          <el-select v-model="workflowForm.subtitleLanguage" class="process-version-select">
            <el-option
              v-for="language in subtitleLanguages"
              :key="language.value"
              :label="language.label"
              :value="language.value"
            />
          </el-select>
        </div>
        <div class="settings-field">
          <span class="settings-label">处理版本</span>
          <el-select v-model="workflowForm.processVersion" class="process-version-select">
            <el-option
              v-for="version in processVersions"
              :key="version.value"
              :label="version.label"
              :value="version.value"
            />
          </el-select>
        </div>
        <div class="version-note">
          <strong>{{ currentProcessVersion.label }}</strong>
          <span>{{ currentProcessVersion.description }}</span>
        </div>
        <div class="version-note">
          <strong>当前字幕语言：{{ currentSubtitleLanguage.label }}</strong>
          <span>处理版本一会把识别到的字幕翻译成该语言后再烧录到视频中；处理版本二会在此基础上提取前三个高光片段并拼接到视频开头。</span>
        </div>
        </div>

        <div class="settings-section">
          <div class="settings-section-header">
            <span class="panel-kicker">烧录设置</span>
            <h3>FFmpeg 输出预设</h3>
          </div>
          <div class="settings-field">
            <span class="settings-label">烧录预设</span>
            <el-select v-model="workflowForm.burnProfile" class="process-version-select">
              <el-option
                v-for="profile in burnProfiles"
                :key="profile.value"
                :label="profile.label"
                :value="profile.value"
              />
            </el-select>
          </div>
          <div class="settings-field">
            <span class="settings-label">字幕字号</span>
            <el-select v-model="workflowForm.subtitleSize" class="process-version-select">
              <el-option
                v-for="size in subtitleSizes"
                :key="size.value"
                :label="size.label"
                :value="size.value"
              />
            </el-select>
          </div>
          <div class="settings-field">
            <span class="settings-label">翻译署名</span>
            <el-input
              v-model="workflowForm.translatorLabel"
              maxlength="32"
              show-word-limit
              placeholder="例如：AI中文字幕"
            />
          </div>
          <div class="version-note">
            <div class="version-note-title">
              <strong>{{ currentBurnProfile.label }}</strong>
              <el-popover placement="left" trigger="click" width="340">
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
                  <el-button class="param-info-button" text circle aria-label="查看预设参数说明">
                    <el-icon><InfoFilled /></el-icon>
                  </el-button>
                </template>
              </el-popover>
            </div>
            <span>点击感叹号查看该预设的编码参数和说明。</span>
          </div>
          <div class="version-note">
            <strong>{{ currentSubtitleSize.label }}</strong>
            <span>{{ currentSubtitleSize.description }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="settingsDialogVisible = false">确定</el-button>
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
            <span class="panel-kicker">内容判断</span>
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
            <p class="publish-copy">{{ analysisResult.publish_copy || '暂无文案' }}</p>
            <div class="tag-list">
              <el-tag v-for="tag in analysisResult.tags || []" :key="tag" type="success" effect="light">#{{ tag }}</el-tag>
              <el-button size="small" text type="primary" @click="copyText((analysisResult.tags || []).map(tag => `#${tag}`).join(' '))">复制标签</el-button>
            </div>
          </div>

          <div class="analysis-section">
            <span class="panel-kicker">高光片段</span>
            <h3>震惊点与中外对比</h3>
            <div class="highlight-list">
              <div
                v-for="segment in analysisResult.highlight_segments || []"
                :key="`${segment.start}-${segment.end}-${segment.suggested_caption}`"
                class="highlight-item"
              >
                <div class="highlight-time">{{ formatSegmentRange(segment) }}</div>
                <div class="highlight-body">
                  <strong>{{ segment.suggested_caption || '建议字幕条待补充' }}</strong>
                  <p>{{ segment.reason || '暂无理由' }}</p>
                  <span>{{ segment.type || 'highlight' }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-if="(analysisResult.risk_notes || []).length" class="analysis-section">
            <span class="panel-kicker">人工确认</span>
            <div class="risk-list">
              <el-tag v-for="note in analysisResult.risk_notes" :key="note" type="warning" effect="light">{{ note }}</el-tag>
            </div>
          </div>
        </template>
        <el-empty v-else description="暂无发布文案与内容分析" />
      </div>
      <template #footer>
        <el-button v-if="analysisStatus === 3 && currentAnalysisRow" type="primary" @click="createAnalysisJob(currentAnalysisRow)">重新生成</el-button>
        <el-button @click="analysisDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Download, InfoFilled, Link, Refresh, Search, Setting, VideoCamera, VideoPlay } from '@element-plus/icons-vue'
import { youtubeApi } from '@/api/youtube'
import { useNotificationStore } from '@/stores/notification'

const loading = ref(false)
const jobsLoading = ref(false)
const importing = ref(false)
const downloadingId = ref('')
const translatingId = ref('')
const creatingJobId = ref('')
const analyzingId = ref('')
const savingAnalysisId = ref('')
const deletingId = ref('')
const resettingId = ref('')
const settingsDialogVisible = ref(false)
const route = useRoute()
const router = useRouter()
const analysisDialogVisible = ref(false)
const analysisLoading = ref(false)
const analysisResult = ref(null)
const analysisStatus = ref(0)
const currentAnalysisRow = ref(null)
const items = ref([])
const jobs = ref([])
const lastResult = ref(null)
const nowTick = ref(Date.now())
const editingPublishDraftIds = ref(new Set())
const selectedVideos = ref([])
const searchProgress = reactive({
  visible: false,
  loaded: 0,
  total: 0,
  message: ''
})
const notificationStore = useNotificationStore()
let jobsTimer = null
let clockTimer = null
let jobsRequesting = false
let workflowSettingsLoaded = false
let loadingWorkflowSettings = false

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
  query: 'foreigner China travel vlog first time in China',
  limit: 12
})

const manualForm = reactive({
  url: ''
})

const workflowForm = reactive({
  publishToDouyin: true,
  account: 'creator',
  publishToBilibili: false,
  bilibiliAccount: 'creator',
  bilibiliTid: 249,
  tags: '中国旅行,外国人在中国',
  processVersion: 'translation_v1',
  subtitleLanguage: 'zh-CN',
  burnProfile: 'stable',
  subtitleSize: 'douyin',
  translatorLabel: 'AI中文字幕'
})

const WORKFLOW_SETTINGS_STORAGE_KEY = 'vidferry.youtube.workflowSettings'

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
    label: '处理版本一：基础处理',
    description: '保留当前链路：生成目标语言字幕，并添加左上角原作者信息。'
  },
  {
    value: 'editing_v1',
    label: '处理版本二：剪辑',
    description: '保留字幕处理链路，并把外国人震惊点、中外对比等前三个高光片段拼接到视频开头。'
  }
]

const burnProfiles = [
  {
    value: 'stable',
    label: '兼容优先（推荐）',
    description: '适合要发布到国内平台或普通播放器预览的视频，优先降低解码压力和播放卡顿。',
    params: [
      { name: 'preset', value: 'fast', description: 'H.264 编码使用更轻的兼容档，避免 medium/slow 输出导致普通设备解码压力过高。' },
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
    label: '速度优先',
    description: '适合短视频或临时预览，烧录更快，画质和码率控制比兼容优先略弱。',
    params: [
      { name: 'preset', value: 'veryfast', description: '更快的 H.264 编码档位，处理时间更短。' },
      { name: 'crf', value: '24', description: '画质略低于兼容优先，文件更小，速度更快。' },
      { name: 'fps', value: '最高 30', description: '仍保留固定帧率和 30fps 限制，避免明显时间戳卡顿。' },
      { name: '分辨率', value: '最高 1080p', description: '同样限制输出尺寸，保证基础播放兼容性。' },
      { name: '码率峰值', value: '4500k', description: '使用更低峰值码率，减少临时预览文件体积。' },
      { name: 'genpts', value: '开启', description: '仍保留时间戳重建，保证基础稳定性。' },
      { name: 'audio', value: 'AAC', description: '仍统一输出 AAC，保证平台和本地播放器兼容性。' }
    ]
  }
]

const subtitleSizes = [
  {
    value: 'standard',
    label: '标准',
    description: '适合横屏长视频留白较少的情况，字号相对克制。'
  },
  {
    value: 'large',
    label: '大号',
    description: '比标准字号更醒目，适合大多数手机端播放场景。'
  },
  {
    value: 'douyin',
    label: '抖音醒目（推荐）',
    description: '适合手机竖屏和国内平台预览，中文、英文和左上角说明都会明显放大。'
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
    next.translatorLabel = settings.translatorLabel.trim().slice(0, 32)
  }
  return next
}

const loadWorkflowSettings = () => {
  try {
    const raw = localStorage.getItem(WORKFLOW_SETTINGS_STORAGE_KEY)
    if (!raw) return
    Object.assign(workflowForm, normalizeStoredWorkflowSettings(JSON.parse(raw)))
  } catch (error) {
    console.warn('读取处理设置失败', error)
  }
}

const saveWorkflowSettings = () => {
  try {
    const settings = {
      processVersion: workflowForm.processVersion,
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel
    }
    localStorage.setItem(WORKFLOW_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  } catch (error) {
    console.warn('保存处理设置失败', error)
  }
}

const processVersionLabel = (value) => {
  return processVersions.find(version => version.value === value)?.label?.split('：')[0] || value || '未知版本'
}

watch(() => workflowForm.processVersion, (nextVersion, previousVersion) => {
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

watch(
  () => ({
    processVersion: workflowForm.processVersion,
    subtitleLanguage: workflowForm.subtitleLanguage,
    burnProfile: workflowForm.burnProfile,
    subtitleSize: workflowForm.subtitleSize,
    translatorLabel: workflowForm.translatorLabel
  }),
  saveWorkflowSettings,
  { deep: true }
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
  sort: 'default'
})

const videoPagination = reactive({
  page: 1,
  pageSize: 10
})

const jobFilter = reactive({
  status: 'all'
})

const jobPagination = reactive({
  page: 1,
  pageSize: 10
})

const isDownloaded = (item) => Number(item.downloadStatus) === 1
const isTranslated = (item) => Number(item.translateStatus) === 1
const isTranslationSkipped = (item) => Number(item.translateStatus) === 2
const isPublished = (item) => item.publishStatus === 1
const isRunningJob = (job) => job.status === 'queued' || job.status === 'running'
const isAbnormalJob = (job) => job.status === 'abnormal'

const latestJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id)
const activeJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id && isRunningJob(job))
const activeAnalysisJobForVideo = (item) => jobs.value.find(job => job.videoId === item.id && isRunningJob(job) && job.step === 'analysis')

const hasDownloadedVideo = (item) => {
  return Number(item.downloadStatus) === 1 || Boolean(item.downloadedFilePath)
}

const hasProcessedVideo = (item) => {
  return [1, 2].includes(Number(item.translateStatus)) || Boolean(item.processedFilePath)
}

const deleteBlockReason = (item) => {
  if (activeJobForVideo(item)) return '该视频存在运行中任务，请等待任务结束后再删除线索。'
  if (isPublished(item)) return ''
  if (hasProcessedVideo(item)) return '该视频已存在处理后视频，请先到素材管理删除对应处理后视频，再删除线索。'
  if (hasDownloadedVideo(item)) return '该视频已存在下载视频，请先到素材管理删除对应下载视频，再删除线索。'
  return ''
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

const analysisActionText = (item) => {
  if (activeAnalysisJobForVideo(item) || Number(item.analysisStatus) === 2) return '文案生成中'
  if (item.hasAnalysis || Number(item.analysisStatus) === 1) return '查看发布文案'
  if (Number(item.analysisStatus) === 3) return '重新生成文案'
  return '生成发布文案'
}

const cleanTopicList = (topics = []) => {
  const values = Array.isArray(topics) ? topics : String(topics || '').split(/[，,\s]+/)
  return Array.from(new Set(
    values
      .map(tag => String(tag || '').trim().replace(/^#+/, ''))
      .filter(Boolean)
  ))
}

const defaultWorkflowTopics = computed(() => cleanTopicList(workflowForm.tags))

const buildAnalysisDraft = (draft = {}, result = {}) => {
  const llmTitleOptions = Array.isArray(result.title_options) ? result.title_options.filter(Boolean) : []
  const draftTitleOptions = Array.isArray(draft.title_options) ? draft.title_options.filter(Boolean) : []
  const selectedTitle = draft.title || draft.selectedTitle || draftTitleOptions[0] || llmTitleOptions[0] || ''
  const titleOptions = Array.from(new Set([selectedTitle, ...draftTitleOptions, ...llmTitleOptions].filter(Boolean)))
  const draftTags = cleanTopicList(draft.tags)
  const resultTags = cleanTopicList(result.tags)
  const selectedTags = draftTags.length ? draftTags : resultTags
  const tagOptions = Array.from(new Set([...selectedTags, ...resultTags, ...defaultWorkflowTopics.value]))
  return {
    titleOptions,
    selectedTitle,
    publishCopy: draft.description || draft.publish_copy || result.publish_copy || '',
    tags: selectedTags,
    tagOptions,
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

const showInlinePublishDraft = (item) => {
  return Number(item.translateStatus) === 1 && Number(item.publishStatus) !== 1 && Number(item.analysisStatus) === 1 && item.analysisDraft
}

const isPublishDraftEditing = (item) => editingPublishDraftIds.value.has(item.id)

const startPublishDraftEditing = (item) => {
  editingPublishDraftIds.value = new Set([...editingPublishDraftIds.value, item.id])
}

const stopPublishDraftEditing = (item) => {
  const nextIds = new Set(editingPublishDraftIds.value)
  nextIds.delete(item.id)
  editingPublishDraftIds.value = nextIds
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
  if (latestJob?.status === 'abnormal') return { label: '任务异常', className: 'is-failed' }
  if (latestJob?.status === 'failed') return { label: '任务失败', className: 'is-failed' }
  if (!isDownloaded(item)) return { label: '待下载', className: 'is-pending' }
  if (!isTranslated(item) && !isTranslationSkipped(item)) return { label: '待处理', className: 'is-warning' }
  if (isTranslationSkipped(item)) return { label: '已跳过', className: 'is-warning' }
  if (!isPublished(item)) return { label: '待发布', className: 'is-ready' }
  return { label: '已完成', className: 'is-complete' }
}

const rowWorkflowSteps = (item) => {
  const runningJob = activeJobForVideo(item)
  const runningStep = runningJob?.step || ''
  const latestJob = latestJobForVideo(item)
  const failed = latestJob?.status === 'failed' || latestJob?.status === 'abnormal'
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
    { key: 'publish', label: '发布', done: isPublished(item), running: runningStep === 'publish' }
  ]
  return steps.map(step => ({
    ...step,
    className: {
      'is-done': step.done && !step.skipped,
      'is-running': step.running,
      'is-muted': !step.done && !step.running,
      'is-warning': step.skipped,
      'is-failed': failed && step.running
    }
  }))
}

const matchesVideoStatus = (item) => {
  const status = videoFilter.status
  if (status === 'notDownloaded') return !isDownloaded(item)
  if (status === 'downloaded') return isDownloaded(item)
  if (status === 'notTranslated') return !isTranslated(item) && !isTranslationSkipped(item)
  if (status === 'translated') return isTranslated(item)
  if (status === 'translationSkipped') return isTranslationSkipped(item)
  if (status === 'notPublished') return !isPublished(item)
  if (status === 'published') return isPublished(item)
  if (status === 'running') return Boolean(activeJobForVideo(item))
  return true
}

const scoreVideo = (item, sort) => {
  if (sort === 'pendingFirst') {
    return [
      isDownloaded(item) && isTranslated(item) ? 1 : 0,
      isDownloaded(item) ? 1 : 0,
      isTranslated(item) ? 1 : 0,
      isPublished(item) ? 1 : 0
    ]
  }
  if (sort === 'downloadedFirst') return [isDownloaded(item) ? 0 : 1, isTranslated(item) ? 0 : 1]
  if (sort === 'translatedFirst') return [isTranslated(item) ? 0 : 1, isDownloaded(item) ? 0 : 1]
  if (sort === 'publishedFirst') return [isPublished(item) ? 0 : 1, isTranslated(item) ? 0 : 1]
  return [0]
}

const compareScore = (left, right) => {
  const maxLength = Math.max(left.length, right.length)
  for (let index = 0; index < maxLength; index += 1) {
    const diff = (left[index] || 0) - (right[index] || 0)
    if (diff !== 0) return diff
  }
  return 0
}

const filteredItems = computed(() => {
  const sort = videoFilter.sort
  return items.value
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => matchesVideoStatus(item))
    .sort((left, right) => {
      if (sort === 'default') return left.index - right.index
      return compareScore(scoreVideo(left.item, sort), scoreVideo(right.item, sort)) || left.index - right.index
    })
    .map(({ item }) => item)
})

watch(
  () => [videoFilter.status, videoFilter.sort],
  () => {
    videoPagination.page = 1
  }
)

const pagedItems = computed(() => {
  const totalPages = Math.max(1, Math.ceil(filteredItems.value.length / videoPagination.pageSize))
  const page = Math.min(videoPagination.page, totalPages)
  const start = (page - 1) * videoPagination.pageSize
  return filteredItems.value.slice(start, start + videoPagination.pageSize)
})

const getJobTimeValue = (job) => {
  return parseJobTime(job.updatedAt) || parseJobTime(job.createdAt)
}

const matchesJobStatus = (job) => {
  if (jobFilter.status === 'running') return isRunningJob(job)
  if (jobFilter.status === 'success') return job.status === 'success'
  if (jobFilter.status === 'failed') return job.status === 'failed'
  if (jobFilter.status === 'abnormal') return isAbnormalJob(job)
  return true
}

const filteredJobs = computed(() => {
  return jobs.value
    .filter(matchesJobStatus)
    .sort((left, right) => {
      const leftRank = isRunningJob(left) ? 0 : 1
      const rightRank = isRunningJob(right) ? 0 : 1
      if (leftRank !== rightRank) return leftRank - rightRank
      return getJobTimeValue(right) - getJobTimeValue(left)
    })
})

watch(
  () => jobFilter.status,
  () => {
    jobPagination.page = 1
  }
)

const pagedJobs = computed(() => {
  const totalPages = Math.max(1, Math.ceil(filteredJobs.value.length / jobPagination.pageSize))
  const page = Math.min(jobPagination.page, totalPages)
  const start = (page - 1) * jobPagination.pageSize
  return filteredJobs.value.slice(start, start + jobPagination.pageSize)
})

const summaryStats = computed(() => {
  const total = items.value.length
  const pendingDownload = items.value.filter(item => !isDownloaded(item)).length
  const pendingTranslate = items.value.filter(item => isDownloaded(item) && !isTranslated(item) && !isTranslationSkipped(item)).length
  const readyPublish = items.value.filter(item => isTranslated(item) && !isPublished(item)).length
  const running = jobs.value.filter(job => job.status === 'queued' || job.status === 'running').length
  const completed = items.value.filter(item => isPublished(item)).length

  return [
    { label: '全部线索', value: total, meta: '当前入库', tone: 'tone-primary', filter: 'all' },
    { label: '待下载', value: pendingDownload, meta: pendingDownload ? '需要获取素材' : '无待下载', tone: 'tone-info', filter: 'notDownloaded' },
    { label: '待处理', value: pendingTranslate, meta: pendingTranslate ? '需要处理素材' : '无待处理', tone: 'tone-warning', filter: 'notTranslated' },
    { label: '待发布', value: readyPublish, meta: readyPublish ? '可进入发布' : '无待发布', tone: 'tone-ready', filter: 'notPublished' },
    { label: '运行中', value: running, meta: running ? '执行中' : '暂无队列', tone: 'tone-running', filter: 'running' },
    { label: '已完成', value: completed, meta: completed ? '已发布' : '等待完成', tone: 'tone-success', filter: 'published' }
  ]
})

const pipelineStages = computed(() => [
  { label: '导入/查询', value: `${items.value.length} 条线索`, icon: Search },
  { label: '下载', value: `${items.value.filter(item => item.downloadStatus === 1).length} 个素材`, icon: Download },
  { label: '处理', value: `${items.value.filter(item => Number(item.translateStatus) === 1).length} 条完成`, icon: VideoCamera },
  { label: '发布', value: `${items.value.filter(item => item.publishStatus === 1).length} 条完成`, icon: VideoPlay }
])

const searchProgressPercent = computed(() => {
  if (!searchProgress.total) return 0
  return Math.min(100, Math.round((searchProgress.loaded / searchProgress.total) * 100))
})

const handleSearch = async () => {
  loading.value = true
  searchProgress.visible = true
  searchProgress.loaded = 0
  searchProgress.total = Number(form.limit || 0)
  searchProgress.message = '正在向 YouTube 请求候选视频'
  try {
    const res = await youtubeApi.search({
      query: form.query,
      limit: form.limit
    })
    lastResult.value = res.data
    const loadedCount = Array.isArray(res.data?.items) ? res.data.items.length : Number(res.data?.created || 0) + Number(res.data?.duplicate || 0)
    searchProgress.loaded = loadedCount
    searchProgress.total = Number(res.data?.requested || form.limit || loadedCount)
    searchProgress.message = `查询完成，实际加载 ${searchProgress.loaded} 条`
    await loadVideos(false)
    showImportResultMessage(res.data, '查询完成')
  } catch (error) {
    searchProgress.message = '查询失败，请检查网络或关键词后重试'
  } finally {
    loading.value = false
  }
}

const setStatusFilter = (filter) => {
  videoFilter.status = videoFilter.status === filter ? 'all' : filter
}

const handleVideoSelectionChange = (rows) => {
  selectedVideos.value = rows
}

const importVideo = async () => {
  const url = manualForm.url.trim()
  if (!url) {
    ElMessage.warning('请先粘贴 YouTube 视频链接')
    return
  }
  importing.value = true
  try {
    const res = await youtubeApi.importVideo({ url })
    lastResult.value = res.data
    manualForm.url = ''
    await loadVideos(false)
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

const loadVideos = async (showLoading = true) => {
  if (showLoading) loading.value = true
  try {
    const res = await youtubeApi.list()
    items.value = (res.data.items || []).map(normalizeVideoItem)
  } finally {
    if (showLoading) loading.value = false
  }
}

const loadJobs = async ({ silent = false } = {}) => {
  if (jobsRequesting) return
  jobsRequesting = true
  if (!silent) jobsLoading.value = true
  try {
    const res = await youtubeApi.listWorkflowJobs({ limit: 50 })
    const nextJobs = res.data.items || []
    const previousStatuses = new Map(jobs.value.map(job => [job.id, job.status]))
    const shouldNotifyFailures = jobs.value.length > 0

    if (shouldNotifyFailures) {
      nextJobs.forEach(job => {
        if (job.status === 'failed' && previousStatuses.get(job.id) !== 'failed') {
          notificationStore.addWorkflowFailureMessage(job)
        }
        if (job.status === 'abnormal' && previousStatuses.get(job.id) !== 'abnormal') {
          notificationStore.addWorkflowAbnormalMessage(job)
        }
      })
    }

    jobs.value = nextJobs
  } finally {
    jobsRequesting = false
    if (!silent) jobsLoading.value = false
  }
}

const startJobsPolling = () => {
  if (jobsTimer) return
  jobsTimer = window.setInterval(() => {
    if (jobs.value.some(job => job.status === 'queued' || job.status === 'running')) {
      loadJobs({ silent: true })
      loadVideos(false)
    }
  }, 1500)
}

const hasActiveWorkflowJobs = () => jobs.value.some(job => job.status === 'queued' || job.status === 'running')

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
  const boundedProgress = Math.max(0, Math.min(100, rawProgress))
  if (job.status !== 'running') return boundedProgress
  return Math.max(0, Math.min(99, boundedProgress))
}

const jobTimeText = (job) => {
  const startedAt = parseJobTime(job.createdAt)
  if (!startedAt) return job.status === 'running' ? '计时中' : '-'

  const endedAt = job.status === 'running'
    ? nowTick.value
    : (parseJobTime(job.updatedAt) || nowTick.value)
  const elapsedSeconds = (endedAt - startedAt) / 1000

  if (job.status !== 'running') return `耗时 ${formatDuration(elapsedSeconds)}`

  const progress = displayProgress(job)
  if (progress <= 0) return `已用 ${formatDuration(elapsedSeconds)}`

  const estimatedTotal = elapsedSeconds / (progress / 100)
  const remainingSeconds = Math.max(0, estimatedTotal - elapsedSeconds)
  return `已用 ${formatDuration(elapsedSeconds)} / 约 ${formatDuration(remainingSeconds)}`
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

const createJob = async (row) => {
  if (!(await confirmReplacingCurrentVersion(row))) return
  creatingJobId.value = row.id
  try {
    const res = await youtubeApi.createWorkflowJob({
      videoId: row.id,
      url: row.url,
      account: workflowForm.account.trim(),
      publishToDouyin: workflowForm.publishToDouyin,
      publishToBilibili: workflowForm.publishToBilibili,
      bilibiliAccount: workflowForm.bilibiliAccount.trim(),
      bilibiliTid: workflowForm.bilibiliTid,
      channel: row.channel,
      subscribers: row.subscribers,
      publishedAt: row.publishedAt,
      title: row.title || 'YouTube 视频',
      description: '',
      tags: workflowForm.tags,
      schedule: '',
      processVersion: workflowForm.processVersion,
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel
    })
    jobs.value.unshift(res.data)
    ElMessage.success('工作流任务已创建')
    startJobsPolling()
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
    setTimeout(() => {
      loadJobs({ silent: true })
      loadVideos(false)
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
    ElMessage.success('视频线索已删除')
  } catch (error) {
    console.warn('删除视频线索失败:', error)
  } finally {
    deletingId.value = ''
  }
}

const resetProcessing = async (row) => {
  if (activeJobForVideo(row)) {
    ElMessage.warning('该视频还有任务执行中，结束后再重新处理')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除「${row.title || row.url}」的${processVersionLabel(workflowForm.processVersion)}处理后视频吗？其他处理版本和下载原视频会保留。`,
      '重新处理视频',
      {
        confirmButtonText: '删除该版本成品',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch (error) {
    return
  }

  resettingId.value = row.id
  try {
    const res = await youtubeApi.resetProcessing(row.id, {
      deleteProcessed: true,
      processVersion: workflowForm.processVersion
    })
    const updatedVideo = res.data.video
    items.value = items.value.map(item => item.id === row.id ? normalizeVideoItem(updatedVideo) : item)
    await loadVideos(false)
    await loadJobs({ silent: true })
    ElMessage.success(`已回退为可重新处理状态，删除处理后素材 ${res.data.deletedMaterialCount || 0} 个`)
  } finally {
    resettingId.value = ''
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

const createAnalysisJob = async (row) => {
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
      tags: workflowForm.tags,
      processVersion: 'editing_v1',
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel
    })
    jobs.value.unshift(res.data)
    items.value = items.value.map(item => item.id === row.id ? { ...item, analysisStatus: 2, hasAnalysis: false, analysisDraft: null } : item)
    ElMessage.success(Number(row.analysisStatus) === 3 ? '发布文案重新生成任务已创建' : '发布文案生成任务已创建')
    startJobsPolling()
  } finally {
    analyzingId.value = ''
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
  savingAnalysisId.value = row.id
  try {
    const nextTitleOptions = row.analysisDraft.selectedTitle
      ? Array.from(new Set([row.analysisDraft.selectedTitle, ...row.analysisDraft.titleOptions].filter(Boolean)))
      : row.analysisDraft.titleOptions.filter(Boolean)
    const payload = {
      title: row.analysisDraft.selectedTitle || nextTitleOptions[0] || '',
      description: row.analysisDraft.publishCopy || '',
      tags: row.analysisDraft.tags.filter(Boolean)
    }
    const response = await youtubeApi.updatePublishDraft(row.id, payload)
    const savedDraft = response.data?.draft || payload
    row.publishDraft = savedDraft
    row.analysisDraft = buildAnalysisDraft(savedDraft, row.analysisResult || {})
    stopPublishDraftEditing(row)
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
      tags: workflowForm.tags,
      processVersion: workflowForm.processVersion,
      subtitleLanguage: workflowForm.subtitleLanguage,
      burnProfile: workflowForm.burnProfile,
      subtitleSize: workflowForm.subtitleSize,
      translatorLabel: workflowForm.translatorLabel
    }
    const res = await youtubeApi.createTranslateJob(payload)
    jobs.value.unshift(res.data)
    ElMessage.success(workflowForm.processVersion === 'editing_v1' ? '剪辑处理任务已创建' : '处理任务已创建')
    startJobsPolling()
    setTimeout(() => {
      loadJobs({ silent: true })
      loadVideos(false)
    }, 1500)
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

const jobStatusText = (status) => {
  const map = {
    queued: '排队中',
    running: '执行中',
    success: '成功',
    failed: '失败',
    abnormal: '异常'
  }
  return map[status] || status || '-'
}

const jobStatusType = (status) => {
  const map = {
    queued: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger',
    abnormal: 'danger'
  }
  return map[status] || 'info'
}

const progressStatus = (job) => {
  const map = {
    success: 'success',
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

onMounted(async () => {
  loadingWorkflowSettings = true
  loadWorkflowSettings()
  await nextTick()
  loadingWorkflowSettings = false
  workflowSettingsLoaded = true
  loadVideos()
  loadJobs()
  startJobsPolling()
  startClock()
  window.__VIDFERRY_OPEN_PROCESS_SETTINGS__ = openSettingsFromLayout
  consumeOpenSettingsQuery()
  window.addEventListener('beforeunload', handleBeforeUnload)
})

watch(() => route.query.openSettings, () => {
  consumeOpenSettingsQuery()
})

onBeforeUnmount(() => {
  if (window.__VIDFERRY_OPEN_PROCESS_SETTINGS__ === openSettingsFromLayout) {
    delete window.__VIDFERRY_OPEN_PROCESS_SETTINGS__
  }
  window.removeEventListener('beforeunload', handleBeforeUnload)
  if (jobsTimer) {
    window.clearInterval(jobsTimer)
    jobsTimer = null
  }
  if (clockTimer) {
    window.clearInterval(clockTimer)
    clockTimer = null
  }
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$accent-teal: #0f9f8f;
$accent-amber: #d97706;
$surface-soft: #f7faff;
$ink-strong: #172033;

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
    background: #f8fbff;
    color: #5c6678;
    font-weight: 600;
  }

  :deep(.el-table td.el-table__cell) {
    padding: 10px 0;
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
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(15, 159, 143, 0.08) 42%, rgba(255, 255, 255, 0.92)),
    #fff;
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
    color: #5b667a;
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
  color: #5b667a;
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
  background: #fff;

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

.search-control {
  grid-template-columns: minmax(220px, 1fr) 110px auto;
}

.search-progress-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: #fff;
}

.search-progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: $text-secondary;
  font-size: 12px;

  strong {
    color: $accent-blue;
    font-size: 13px;
  }
}

.limit-field {
  :deep(.el-input-number) {
    width: 100%;
  }
}

.workflow-config {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  border: 1px solid #e2eaf5;
  border-radius: 8px;
  background: #fff;
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

.config-items {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
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
  width: 140px;
}

.tid-input {
  width: 108px;
}

.tag-input {
  width: 260px;
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
  grid-template-columns: 116px minmax(300px, 0.72fr) minmax(520px, 1.28fr);
  align-items: center;
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

.video-title {
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
  grid-template-columns: minmax(120px, 220px) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  max-width: 620px;
  padding: 6px 8px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 6px;
  color: #4b5a70;
  background: #f8fbff;
  font-size: 12px;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.analysis-hint {
  display: inline-flex;
  align-items: center;
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

:deep(.danger-item) {
  color: $danger-color;
}

.job-card {
  margin-bottom: 4px;
}

.settings-panel {
  display: grid;
  gap: 16px;
}

.settings-section {
  display: grid;
  gap: 12px;
}

.settings-section + .settings-section {
  padding-top: 14px;
  border-top: 1px solid #e2eaf5;
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
  gap: 8px;
}

.settings-label {
  color: $text-regular;
  font-size: 13px;
  font-weight: 600;
}

.process-version-select {
  width: 100%;
}

.version-note {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: #f7faff;

  strong {
    color: $ink-strong;
    font-size: 14px;
  }

  span {
    color: $text-secondary;
    font-size: 13px;
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
    color: #172033;
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
  background: #f8fbff;

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
  background: #fff;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.publish-draft-card {
  display: grid;
  gap: 8px;
  width: 100%;
  max-width: none;
  min-width: 0;
  padding: 10px;
  border: 1px solid #dce6f2;
  border-radius: 8px;
  background: #f8fbff;
}

.publish-draft-card.is-editing {
  width: 100%;
  max-width: none;
  min-width: 0;
  padding: 12px;
  border-color: #bdd3f0;
  background: linear-gradient(180deg, #fafdff 0%, #f5f9ff 100%);
  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.08);
}

.draft-editor-grid {
  display: grid;
  grid-template-columns: minmax(210px, 0.68fr) minmax(360px, 1.32fr);
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
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 8px;
  align-items: start;

  > span {
    padding-top: 6px;
    color: $text-secondary;
    font-size: 12px;
    font-weight: 650;
  }
}

.draft-description-row {
  grid-template-columns: 42px minmax(0, 1fr);
  min-width: 0;

  :deep(.el-textarea__inner) {
    min-height: 132px !important;
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
    color: $ink-strong;
    font-size: 13px;
    line-height: 1.55;
    overflow-wrap: anywhere;
  }

  p {
    color: #4b5a70;
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
  color: $accent-blue;
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
  border: 1px solid #e2eaf5;
  border-radius: 8px;
  background: #fff;
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
  .search-control {
    grid-template-columns: 1fr;
  }

  .workflow-config {
    align-items: flex-start;
    flex-direction: column;
  }

  .config-items {
    justify-content: flex-start;
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
  .tag-input,
  .tid-input {
    width: 100%;
  }

  .config-items {
    display: grid;
    grid-template-columns: 1fr;
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
  }

  .video-url {
    max-width: 220px;
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
