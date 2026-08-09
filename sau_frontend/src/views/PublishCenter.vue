<template>
  <div class="publish-center">
    <section class="page-hero">
      <div>
        <span class="eyebrow">PUBLISH DESK</span>
        <h1>发布中心</h1>
        <p>按批次组织素材、平台账号、发布内容和执行时间。</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="addTab">
          <el-icon><Plus /></el-icon>
          <span>新增批次</span>
        </el-button>
        <el-button type="success" :loading="batchPublishing" @click="batchPublish">批量发布</el-button>
      </div>
    </section>

    <div class="publish-workbench">
      <aside class="batch-panel">
        <div class="panel-title">
          <span class="panel-kicker">BATCHES</span>
          <h2>发布批次</h2>
        </div>
        <div class="batch-list">
          <button
            v-for="tab in tabs"
            :key="tab.name"
            type="button"
            class="batch-item"
            :class="{ active: activeTab === tab.name }"
            @click="activeTab = tab.name"
          >
            <span>{{ tab.label }}</span>
            <small>{{ tab.fileList.length }} 个素材 · {{ publishTargets(tab).length }} 个平台</small>
            <el-icon v-if="tabs.length > 1" class="close-icon" @click.stop="removeTab(tab.name)"><Close /></el-icon>
          </button>
        </div>
      </aside>

      <main class="compose-panel">
        <div v-for="tab in tabs" :key="tab.name" v-show="activeTab === tab.name" class="compose-content">
          <el-alert v-if="tab.publishStatus" :title="tab.publishStatus.message" :type="tab.publishStatus.type" :closable="false" show-icon />
          <section v-if="tab.lastPublishResults.length > 0" class="publish-receipt" aria-live="polite">
            <div class="publish-receipt-heading">
              <div>
                <span class="panel-kicker">LATEST DELIVERY</span>
                <h2>本次发布结果</h2>
              </div>
              <span>{{ tab.lastPublishTaskId ? `任务 ${tab.lastPublishTaskId.slice(0, 8)}` : '' }}</span>
            </div>
            <div class="publish-receipt-list">
              <div v-for="result in tab.lastPublishResults" :key="result.platformType" class="publish-receipt-item">
                <div>
                  <strong>{{ result.platformName }}</strong>
                  <span>{{ result.accountName || '默认账号' }}</span>
                </div>
                <el-tag size="small" :type="publishStatusTagType(result.status)">{{ publishStatusLabel(result.status) }}</el-tag>
                <span class="publish-receipt-duration">{{ formatPublishDuration(result.durationMs) }}</span>
                <p>{{ result.message || '发布完成' }}</p>
              </div>
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading">
              <span class="step-index">1</span>
              <div>
                <h3>视频素材</h3>
                <p>仅支持选择已完成处理的视频，避免误发布原始下载素材。</p>
              </div>
              <el-button type="primary" :disabled="tab.fileList.length > 0" @click="selectMaterialLibrary(tab)">
                <el-icon><Folder /></el-icon>
                <span>选择处理后视频</span>
              </el-button>
            </div>
            <div v-if="tab.fileList.length > 0" class="selection-note">如需更换视频，请先删除当前视频，发布内容会同步清空。</div>
            <div v-if="tab.fileList.length > 0" class="file-list">
              <div v-for="(file, index) in tab.fileList" :key="index" class="file-item">
                <div class="selected-video-main">
                  <el-link :href="file.url" target="_blank" type="primary">{{ file.displayTitle || file.name }}</el-link>
                  <div class="selected-video-meta">
                    <span>{{ file.channel || '未知博主' }}</span>
                    <span>{{ file.processType || '处理后视频' }}</span>
                    <span>{{ file.subtitleLanguageLabel || '字幕语言未知' }}</span>
                    <span>{{ formatFileSize(file.size) }}</span>
                  </div>
                  <el-tag v-if="sourceContentRisk(tab)?.requiresPublishConfirmation" size="small" type="warning" effect="light">
                    内容风险需确认
                  </el-tag>
                </div>
                <el-button type="danger" size="small" text @click="removeFile(tab, index)">删除</el-button>
              </div>
            </div>
            <el-empty v-else description="暂无视频素材" :image-size="72" />
          </section>

          <section class="form-section">
            <div class="sub-panel">
              <div class="section-heading compact">
                <span class="step-index">2</span>
                <div>
                  <h3>平台账号</h3>
                  <p>可同时选择多个平台，但每个平台只能选择一个账号。</p>
                </div>
              </div>
              <div class="tag-cloud">
                <el-tag v-for="target in publishTargets(tab)" :key="target.platformType" closable @close="removePlatformAccount(tab, target.platformType)">
                  {{ target.platformName }} · {{ target.accountName }}
                </el-tag>
                <el-tag v-if="publishTargets(tab).length === 0" type="info" effect="plain">暂无发布平台</el-tag>
                <el-button type="primary" plain @click="openAccountDialog(tab)">选择账号</el-button>
              </div>
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading compact">
              <span class="step-index">3</span>
              <div>
                <h3>发布内容</h3>
                <p>读取采集页已保存的发布稿；修改文案请回到来源页。</p>
              </div>
            </div>
            <el-carousel
              v-if="publishTargets(tab).length > 0"
              class="target-carousel"
              height="340px"
              indicator-position="outside"
              :autoplay="false"
              arrow="always"
            >
              <el-carousel-item v-for="target in publishTargets(tab)" :key="target.platformType">
                <div class="target-slide">
                  <div>
                    <strong>{{ target.platformName }}</strong>
                    <span>{{ target.accountName }}</span>
                  </div>
                  <div class="target-preview-grid">
                    <span>标题</span>
                    <p>{{ tab.title || '选择素材后自动填充标题' }}</p>
                    <span>描述</span>
                    <p>{{ tab.description || '选择素材后自动填充文案' }}</p>
                    <span>话题</span>
                    <p>{{ formatTopicsForTarget(tab, target) }}</p>
                    <span>发布</span>
                    <p>{{ tab.scheduleEnabled ? `定时发布 · ${tab.scheduledAt || '未选择时间'}` : '立即发布' }}</p>
                  </div>
                  <el-alert
                    v-if="isDouyinTopicTruncated(tab, target)"
                    title="抖音最多支持一次选择 5 条话题，本次将只发布前 5 条。"
                    type="warning"
                    :closable="false"
                    show-icon
                  />
                  <div v-if="Number(target.platformType) === 3" class="platform-specific-panel">
                    <span class="platform-specific-title">抖音专属设置</span>
                    <div class="two-col">
                      <el-input v-model="tab.productTitle" placeholder="商品名称（可选）" maxlength="200" />
                      <el-input v-model="tab.productLink" placeholder="商品链接（可选）" maxlength="200" />
                    </div>
                  </div>
                  <div v-if="Number(target.platformType) === 5" class="platform-specific-panel">
                    <span class="platform-specific-title">B站专属设置</span>
                    <el-select v-model="tab.bilibiliTid" filterable placeholder="选择 B站分区">
                      <el-option
                        v-for="category in bilibiliCategories"
                        :key="category.tid"
                        :label="`${category.label}（${category.tid}）`"
                        :value="category.tid"
                      />
                      <el-option
                        v-if="isUnknownBilibiliTid(tab.bilibiliTid)"
                        :label="`未知分区（${tab.bilibiliTid}）`"
                        :value="tab.bilibiliTid"
                      />
                    </el-select>
                  </div>
                </div>
              </el-carousel-item>
            </el-carousel>
            <el-alert v-else title="请选择至少一个平台账号，选择后这里会按平台分页展示发布内容。" type="info" :closable="false" show-icon />
            <div v-if="targetStatusList(tab).length > 0" class="target-status-panel">
              <div v-for="status in targetStatusList(tab)" :key="status.platformType" class="target-status-item">
                <div>
                  <strong>{{ status.platformName }}</strong>
                  <span>{{ status.accountName }}</span>
                </div>
                <el-tag size="small" :type="publishStatusTagType(status.status)">
                  {{ publishStatusLabel(status.status) }}
                </el-tag>
                <p>{{ status.message || '等待发布' }}</p>
              </div>
            </div>
            <div class="publish-readonly-card">
              <div>
                <span>标题</span>
                <strong>{{ tab.title || '暂无发布标题' }}</strong>
              </div>
              <div>
                <span>描述</span>
                <p>{{ tab.description || '暂无发布文案' }}</p>
              </div>
              <div>
                <span>话题</span>
                <div class="tag-cloud topic-cloud">
                  <el-tag v-for="topic in tab.selectedTopics" :key="topic">#{{ topic }}</el-tag>
                  <el-tag v-if="tab.selectedTopics.length === 0" type="info" effect="plain">暂无已保存话题</el-tag>
                </div>
              </div>
            </div>
            <div class="inline-options">
              <el-checkbox v-model="tab.isOriginal" label="声明原创" />
              <el-checkbox v-if="hasSelectedPlatform(tab, 2)" v-model="tab.isDraft" label="视频号仅保存草稿" />
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading compact">
              <span class="step-index">4</span>
              <div>
                <h3>发布时间</h3>
                <p>立即发布，或由本机后端在指定时间自动执行。</p>
              </div>
            </div>
            <div class="schedule-controls">
              <el-switch v-model="tab.scheduleEnabled" active-text="定时发布" inactive-text="立即发布" />
              <div v-if="tab.scheduleEnabled" class="schedule-settings">
                <div class="schedule-item wide">
                  <span>计划发布时间</span>
                  <el-date-picker
                    v-model="tab.scheduledAt"
                    type="datetime"
                    value-format="YYYY-MM-DD HH:mm:ss"
                    format="YYYY-MM-DD HH:mm"
                    placeholder="选择今天起 10 天内的时间"
                    :disabled-date="disabledScheduleDate"
                    :disabled-hours="(_, comparingDate) => disabledScheduleHours(tab, comparingDate)"
                    :disabled-minutes="(hour, _, comparingDate) => disabledScheduleMinutes(tab, hour, comparingDate)"
                  />
                </div>
              </div>
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading compact">
              <span class="step-index">5</span>
              <div>
                <h3>发布前质检</h3>
                <p>Agent 质检是可选的，用于检查发布文案和视频关键帧。</p>
              </div>
              <el-button
                size="small"
                :loading="tab.agentChecking || tab.agentGuardLoading"
                :disabled="tab.fileList.length === 0 || tab.agentChecking || tab.agentGuardLoading"
                @click="runAgentPrepublishCheck(tab)"
              >
                {{ tab.agentChecking ? '质检中...' : (tab.agentGuardLoading ? '读取中...' : '立即质检') }}
              </el-button>
            </div>
            <div v-if="tab.agentGuardStatus !== 'idle'" class="agent-guard-card" :class="`is-${tab.agentGuardStatus}`">
              <div class="agent-guard-header">
                <div class="agent-guard-summary">
                  <el-tag size="small" :type="agentGuardTagType(tab)">
                    {{ agentGuardLabel(tab) }}
                  </el-tag>
                  <el-tag v-if="isAgentGuardStale(tab)" size="small" type="warning" effect="plain">配置已变化</el-tag>
                  <span>{{ agentGuardSummary(tab) }}</span>
                </div>
                <span v-if="tab.agentGuardResult?.checkedAt" class="agent-guard-time">
                  <el-icon><Clock /></el-icon>
                  质检时间 {{ formatAgentGuardTime(tab.agentGuardResult.checkedAt) }}
                </span>
              </div>
              <el-alert
                v-if="isAgentGuardStale(tab)"
                title="当前发布文案、话题或平台配置与上次质检时不同，建议重新质检。"
                type="warning"
                :closable="false"
                show-icon
              />
              <div v-if="agentGuardIssues(tab).length" class="agent-guard-issues">
                <div v-for="(issue, index) in agentGuardIssues(tab)" :key="index" class="agent-guard-issue">
                  <strong>{{ issue.category || '风险项' }} · {{ issue.severity || 'unknown' }}</strong>
                  <p>{{ issue.reason || issue.evidence || '请检查该风险项。' }}</p>
                  <small>{{ issue.suggestion || '' }}</small>
                </div>
              </div>
            </div>
          </section>

          <div class="submit-bar">
            <el-button @click="cancelPublish(tab)">取消</el-button>
            <el-button type="primary" @click="confirmPublish(tab)" :loading="tab.publishing || false">
              {{ tab.publishing ? '提交中...' : (tab.scheduleEnabled ? '创建定时任务' : '发布') }}
            </el-button>
          </div>
        </div>
      </main>
    </div>

    <section class="published-panel">
      <div class="panel-heading-row">
        <div>
          <span class="panel-kicker">PUBLISHED</span>
          <h2>已发布视频</h2>
          <p>汇总已经提交到国内平台的处理后视频，方便从发布中心追踪结果。</p>
        </div>
        <div class="published-toolbar">
          <el-radio-group v-model="publishedRecordScope" size="small">
            <el-radio-button label="active">当前记录</el-radio-button>
            <el-radio-button label="archived">已归档</el-radio-button>
          </el-radio-group>
          <el-button :loading="publishedLoading" @click="loadPublishedVideos">
            <el-icon><Refresh /></el-icon>
            <span>刷新</span>
          </el-button>
        </div>
      </div>

      <div v-if="publishedRecordScope === 'active'" class="published-summary">
        <div class="summary-tile">
          <span>已发布</span>
          <strong>{{ publishedVideos.length }}</strong>
        </div>
        <div class="summary-tile">
          <span>抖音任务</span>
          <strong>{{ publishedPlatformStats.douyin }}</strong>
        </div>
        <div class="summary-tile">
          <span>B站任务</span>
          <strong>{{ publishedPlatformStats.bilibili }}</strong>
        </div>
        <div class="summary-tile">
          <span>处理后素材</span>
          <strong>{{ publishedMaterialCount }}</strong>
        </div>
      </div>

      <div v-if="publishedRecordScope === 'active' && publishedVideos.length > 0" class="published-list">
        <article v-for="video in publishedVideos" :key="video.id" class="published-card">
          <div class="published-cover">
            <img v-if="video.thumbnail" :src="video.thumbnail" :alt="video.title" />
            <span v-else>VIDEO</span>
          </div>
          <div class="published-body">
            <div class="published-title-row">
              <h3>{{ video.title || '未命名视频' }}</h3>
              <el-tag size="small" type="success">已发布</el-tag>
            </div>
            <div class="published-meta">
              <span>{{ video.channel || '未知博主' }}</span>
              <span>{{ video.subscribers || '粉丝未知' }}</span>
              <span>{{ video.publishedAt || '原发布时间未知' }}</span>
              <span>{{ video.duration || '-' }}</span>
            </div>
            <div class="published-tags">
              <el-tag v-for="tag in publishedPlatforms(video)" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
              <el-tag size="small" type="warning" effect="light">{{ video.processVersionLabel || '处理版本未知' }}</el-tag>
              <el-tag size="small" type="success" effect="plain">{{ video.subtitleLanguageLabel || '字幕语言未知' }}</el-tag>
              <span>{{ video.processedFileSizeLabel || '素材大小未知' }}</span>
            </div>
            <div class="published-record-list">
              <div v-for="record in video.publishedRecords" :key="record.id" class="published-record-row">
                <div>
                  <el-tag size="small" effect="plain">{{ record.platform }}</el-tag>
                  <span>{{ record.accountName || record.accountFile || '未记录账号' }}</span>
                </div>
                <span>{{ record.publishedAt || record.updatedAt || '-' }}</span>
                <el-button type="danger" text size="small" @click="deletePublishedRecord(record)">
                  <el-icon><Delete /></el-icon>
                  <span>删除记录</span>
                </el-button>
              </div>
            </div>
            <div class="published-actions">
              <span>{{ video.publishedLabel }}</span>
              <el-button type="primary" link @click="askAgentAboutPublishedVideo(video)">问 Agent</el-button>
            </div>
          </div>
        </article>
      </div>
      <div v-if="publishedRecordScope === 'active' && retryablePublishTasks.length" class="retry-task-list">
        <div v-for="task in retryablePublishTasks" :key="task.taskId" class="retry-task-row">
          <div>
            <strong>{{ task.chineseTitle || '未命名发布任务' }}</strong>
            <span>{{ (task.retryTargets || []).map(target => `${target.platform} · ${target.accountName || target.accountFile || '原账号缺失'}`).join(' / ') }}</span>
          </div>
          <el-button type="primary" plain size="small" @click="openRetryDialog(task)">重发失败项</el-button>
        </div>
      </div>
      <div v-if="publishedRecordScope === 'archived' && archivedPublishedRecords.length" class="archived-record-list">
        <div v-for="record in archivedPublishedRecords" :key="record.id" class="archived-record-row">
          <div>
            <strong>{{ record.publishTitle || record.title || record.filename }}</strong>
            <span>{{ record.platform }} · {{ record.accountName || record.accountFile || '未记录账号' }}</span>
          </div>
          <el-tag size="small" :type="publishStatusTagType(record.status)">{{ publishStatusLabel(record.status) }}</el-tag>
          <span>{{ record.publishedAt || '-' }}</span>
          <span>归档于 {{ record.deletedAt || record.updatedAt || '-' }}</span>
        </div>
      </div>
      <el-empty
        v-if="(publishedRecordScope === 'active' && !publishedVideos.length && !retryablePublishTasks.length) || (publishedRecordScope === 'archived' && !archivedPublishedRecords.length)"
        :description="publishedRecordScope === 'active' ? '暂无已发布视频，发布成功后会在这里汇总展示。' : '暂无已归档发布记录。'"
        :image-size="84"
      />
    </section>

    <PublishRetryDialog v-model="retryDialogVisible" :task="retryTask" @completed="refreshPublishRetryTasks" />

    <el-dialog v-model="batchPublishDialogVisible" title="批量发布进度" width="500px" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
      <div class="publish-progress">
        <el-progress :percentage="publishProgress" :status="publishProgress === 100 ? 'success' : ''" />
        <div v-if="currentPublishingTab" class="current-publishing">正在发布：{{ currentPublishingTab.label }}</div>
        <div class="publish-results" v-if="publishResults.length > 0">
          <div v-for="(result, index) in publishResults" :key="index" :class="['result-item', result.status]">
            <span class="label">{{ result.label }}</span>
            <span class="message">{{ result.message }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="cancelBatchPublish" :disabled="publishProgress === 100">取消发布</el-button>
          <el-button type="primary" @click="batchPublishDialogVisible = false" v-if="publishProgress === 100">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="materialLibraryVisible"
      title="选择处理后视频"
      width="min(960px, calc(100vw - 32px))"
      top="6vh"
      class="material-library-dialog"
    >
      <el-alert
        title="发布中心只显示已经完成字幕、作者信息和兼容转码的处理后视频。"
        type="info"
        :closable="false"
        show-icon
      />
      <div class="material-library-tools">
        <VideoGroupSelect v-model="materialLibraryGroupId" include-all class="publish-group-filter" />
        <el-input
          v-model="materialLibraryKeyword"
          clearable
          placeholder="搜索视频标题、博主、话题"
          @input="handleMaterialLibrarySearch"
          @clear="handleMaterialLibrarySearch"
        />
        <el-button :loading="materialLibraryLoading" @click="loadPublishableMaterials({ force: true })">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
      <el-radio-group v-model="selectedMaterial" class="material-radio-group">
        <div v-if="publishableMaterials.length > 0" v-loading="materialLibraryLoading" class="material-list publishable-list">
          <div v-for="material in publishableMaterials" :key="material.id" class="material-item publishable-item">
            <el-radio :label="material.id">
              <div class="material-info">
                <div class="material-name">{{ material.displayTitle || material.filename }}</div>
                <div class="material-details">
                  <span>{{ material.displayChannel || '未知博主' }}</span>
                  <span>{{ material.displaySubscribers || '粉丝未知' }}</span>
                  <span>{{ material.displayPublishedAt || '发布时间未知' }}</span>
                </div>
                <div class="material-publish-draft">
                  <span class="draft-label">发布标题</span>
                  <strong>{{ materialPublishDraft(material).title || '暂无已保存发布标题' }}</strong>
                </div>
                <div class="material-topic-list">
                  <span class="draft-label">话题</span>
                  <el-tag
                    v-for="tag in materialPublishDraft(material).tags"
                    :key="tag"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    #{{ tag }}
                  </el-tag>
                  <span v-if="materialPublishDraft(material).tags.length === 0" class="empty-topic">暂无话题</span>
                </div>
                <div class="material-badges">
                  <el-tag v-if="material.groupName" size="small" type="info" effect="plain">{{ material.groupName }}</el-tag>
                  <el-tag size="small" type="warning" effect="light">{{ material.processType || '处理后视频' }}</el-tag>
                  <el-tag size="small" type="success" effect="plain">{{ material.subtitleLanguageLabel || '字幕语言未知' }}</el-tag>
                  <el-tag size="small" effect="plain">{{ processVersionLabel(material.processVersion) }}</el-tag>
                  <el-tag
                    v-for="platformType in publishedPlatformTypesForVideo(material.source_video_id || material.metadata?.videoId)"
                    :key="platformType"
                    size="small"
                    type="danger"
                    effect="plain"
                  >
                    已发{{ platformNameByKey[platformType] }}
                  </el-tag>
                  <span>{{ material.duration || '-' }}</span>
                  <span>{{ material.filesize }} MB</span>
                </div>
              </div>
            </el-radio>
          </div>
        </div>
      <el-empty v-else v-loading="materialLibraryLoading" description="暂无可发布的处理后视频，请先在视频采集与处理页完成处理。" />
      </el-radio-group>
      <template #footer>
        <div class="material-library-footer">
          <el-pagination
            v-if="materialLibraryTotal > materialLibraryPagination.pageSize"
            v-model:current-page="materialLibraryPagination.page"
            :page-size="materialLibraryPagination.pageSize"
            :total="materialLibraryTotal"
            layout="total, prev, pager, next"
            background
          />
          <div class="dialog-footer">
            <el-button @click="materialLibraryVisible = false">取消</el-button>
            <el-button type="primary" :disabled="selectedMaterial === null" @click="confirmMaterialSelection">确定</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" title="选择平台账号" width="760px" class="account-dialog">
      <div class="account-platform-list">
        <div v-for="platform in platforms" :key="platform.key" class="account-platform-card" :class="{ disabled: isPlatformDisabledForCurrentTab(platform.key) }">
          <div class="account-platform-heading">
            <div>
              <strong>{{ platform.name }}</strong>
              <span v-if="isPlatformDisabledForCurrentTab(platform.key)">该视频已发布到{{ platform.name }}</span>
              <span v-else>每个平台只能选择一个账号</span>
            </div>
            <el-button v-if="tempPlatformAccounts[platform.key]" size="small" text type="danger" @click="tempPlatformAccounts[platform.key] = ''">清除</el-button>
          </div>
          <el-radio-group v-model="tempPlatformAccounts[platform.key]" :disabled="isPlatformDisabledForCurrentTab(platform.key)" class="platform-account-radios">
            <el-radio
              v-for="account in availableAccountsByPlatform(platform.name)"
              :key="account.id"
              :label="account.id"
              class="account-item"
            >
              <span>{{ account.name }}</span>
            </el-radio>
          </el-radio-group>
          <el-empty v-if="availableAccountsByPlatform(platform.name).length === 0" description="暂无正常账号，请先在账号管理中重新连接" :image-size="48" />
        </div>
      </div>
      <template #footer><div class="dialog-footer"><el-button @click="accountDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmAccountSelection">确定</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="topicDialogVisible" title="添加话题" width="600px" class="topic-dialog">
      <div class="custom-topic-input">
        <el-input v-model="customTopic" placeholder="输入自定义话题"><template #prepend>#</template></el-input>
        <el-button type="primary" @click="addCustomTopic">添加</el-button>
      </div>
      <div class="recommended-topics">
        <h4>推荐话题</h4>
        <div class="topic-grid">
          <el-button v-for="topic in recommendedTopics" :key="topic" :type="currentTab?.selectedTopics?.includes(topic) ? 'primary' : 'default'" @click="toggleRecommendedTopic(topic)">{{ topic }}</el-button>
        </div>
      </div>
      <template #footer><div class="dialog-footer"><el-button @click="topicDialogVisible = false">取消</el-button><el-button type="primary" @click="confirmTopicSelection">确定</el-button></div></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Plus, Close, Delete, Folder, Refresh, Clock } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { useAppStore } from '@/stores/app'
import { useNotificationStore } from '@/stores/notification'
import { agentApi } from '@/api/agent'
import { materialApi } from '@/api/material'
import { youtubeApi } from '@/api/youtube'
import { accountApi } from '@/api/account'
import { http } from '@/utils/request'
import VideoGroupSelect from '@/components/VideoGroupSelect.vue'
import PublishRetryDialog from '@/components/PublishRetryDialog.vue'

// 当前激活的tab
const activeTab = ref('tab1')

// tab计数器
let tabCounter = 1

const PUBLISH_DRAFT_STORAGE_KEY = 'vidferry:publish-center:draft:v1'

// 获取应用状态管理
const appStore = useAppStore()
const accountStore = useAccountStore()
const notificationStore = useNotificationStore()

// 上传相关状态
const materialLibraryVisible = ref(false)
const currentUploadTab = ref(null)
const selectedMaterial = ref(null)
const publishableMaterials = ref([])
const materialLibraryLoading = ref(false)
const materialLibraryKeyword = ref('')
const materialLibraryGroupId = ref('')
const materialLibraryTotal = ref(0)
const materialLibraryPagination = reactive({ page: 1, pageSize: 10 })
let materialLibrarySearchTimer = null
const publishedLoading = ref(false)
const publishedVideos = ref([])
const archivedPublishedRecords = ref([])
const publishedRecordScope = ref('active')
const retryablePublishTasks = ref([])
const retryDialogVisible = ref(false)
const retryTask = ref(null)

// 批量发布相关状态
const batchPublishing = ref(false)
const batchPublishMessage = ref('')
const batchPublishType = ref('info')

// 平台列表 - 对应后端type字段
const platforms = [
  { key: 3, name: '抖音' },
  { key: 5, name: 'B站' },
  { key: 4, name: '快手' },
  { key: 2, name: '视频号' },
  { key: 1, name: '小红书' }
]

const platformNameByKey = platforms.reduce((map, platform) => {
  map[platform.key] = platform.name
  return map
}, {})
const platformOrderByKey = new Map(platforms.map((platform, index) => [platform.key, index]))

const sortPublishedRecords = records => [...records].sort((left, right) => {
  const leftOrder = platformOrderByKey.get(Number(left.platformType)) ?? platforms.length
  const rightOrder = platformOrderByKey.get(Number(right.platformType)) ?? platforms.length
  return leftOrder - rightOrder
})

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
    }
  } catch (error) {
    console.warn('读取 B站分区失败，使用内置常用分区', error)
  }
}

const defaultTabInit = {
  name: 'tab1',
  label: '发布1',
  fileList: [], // 后端返回的文件名列表
  displayFileList: [], // 用于显示的文件列表
  selectedAccounts: [], // 选中的账号ID列表
  platformAccounts: {}, // 平台 -> 账号ID
  selectedPlatform: 1, // 选中的平台（单选）
  title: '',
  description: '',
  productLink: '', // 商品链接
  productTitle: '', // 商品名称
  bilibiliTid: 21,
  selectedTopics: [], // 话题列表（不带#号）
  contentLocked: false,
  publishTargetStatuses: [],
  lastPublishResults: [],
  lastPublishTaskId: '',
  agentChecking: false,
  agentGuardLoading: false,
  agentGuardRequestId: 0,
  agentGuardStatus: 'idle',
  agentGuardResult: null,
  agentGuardRunId: '',
  agentGuardConfirmReason: '',
  sourceContentConfirmed: false,
  scheduleEnabled: false, // 定时发布开关
  scheduledAt: '', // 本地定时发布时间
  publishStatus: null, // 发布状态，包含message和type
  publishing: false, // 发布状态，用于控制按钮loading效果
  isDraft: false, // 是否保存为草稿，仅视频号平台可见
  isOriginal: false // 是否标记为原创
}

// helper to create a fresh deep-copied tab from defaultTabInit
const makeNewTab = () => {
  // prefer structuredClone when available (newer browsers/node), fallback to JSON
  try {
    return typeof structuredClone === 'function' ? structuredClone(defaultTabInit) : JSON.parse(JSON.stringify(defaultTabInit))
  } catch (e) {
    return JSON.parse(JSON.stringify(defaultTabInit))
  }
}

const normalizeSelectedAccounts = (accounts = []) => {
  const existingAccountIds = new Set(accountStore.accounts.map(account => String(account.id)))
  const seen = new Set()
  return (Array.isArray(accounts) ? accounts : [])
    .filter(accountId => existingAccountIds.has(String(accountId)))
    .filter(accountId => {
      const key = String(accountId)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

const normalizePlatformAccounts = (platformAccounts = {}) => {
  const normalized = {}
  Object.entries(platformAccounts || {}).forEach(([platformType, accountId]) => {
    const key = String(platformType)
    const value = String(accountId || '')
    if (!value) return
    if (accountStore.accounts.some(account => String(account.id) === value)) {
      normalized[key] = value
    }
  })
  return normalized
}

const readPublishDraft = () => {
  try {
    const raw = localStorage.getItem(PUBLISH_DRAFT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed?.tabs) ? parsed : null
  } catch (error) {
    console.warn('读取发布中心草稿失败:', error)
    return null
  }
}

const normalizePublishTab = (tab, index) => {
  const nextTab = makeNewTab()
  Object.assign(nextTab, {
    ...tab,
    name: tab?.name || `tab${index + 1}`,
    label: tab?.label || `发布${index + 1}`,
    fileList: Array.isArray(tab?.fileList) ? tab.fileList.slice(0, 1) : [],
    selectedAccounts: normalizeSelectedAccounts(tab?.selectedAccounts),
    platformAccounts: normalizePlatformAccounts(tab?.platformAccounts),
    bilibiliTid: Number(tab?.bilibiliTid || defaultBilibiliTid.value),
    selectedTopics: Array.isArray(tab?.selectedTopics) ? tab.selectedTopics : [],
    scheduledAt: String(tab?.scheduledAt || ''),
    publishTargetStatuses: Array.isArray(tab?.publishTargetStatuses) ? tab.publishTargetStatuses : [],
    lastPublishResults: Array.isArray(tab?.lastPublishResults) ? tab.lastPublishResults : [],
    lastPublishTaskId: String(tab?.lastPublishTaskId || ''),
    agentChecking: false,
    agentGuardLoading: false,
    agentGuardRequestId: 0,
    agentGuardStatus: 'idle',
    sourceContentConfirmed: false,
    agentGuardResult: null,
    agentGuardRunId: '',
    agentGuardConfirmReason: '',
    publishStatus: null,
    publishing: false
  })
  nextTab.displayFileList = nextTab.fileList.map(item => ({
    name: item.name,
    url: item.url
  }))
  return nextTab
}

const serializePublishTab = (tab) => ({
  name: tab.name,
  label: tab.label,
  fileList: tab.fileList,
  displayFileList: tab.displayFileList,
  selectedAccounts: normalizeSelectedAccounts(tab.selectedAccounts),
  platformAccounts: normalizePlatformAccounts(tab.platformAccounts),
  selectedPlatform: tab.selectedPlatform,
  title: tab.title,
  description: tab.description,
  productLink: tab.productLink,
  productTitle: tab.productTitle,
  bilibiliTid: Number(tab.bilibiliTid || defaultBilibiliTid.value),
  selectedTopics: tab.selectedTopics,
  contentLocked: Boolean(tab.contentLocked),
  publishTargetStatuses: tab.publishTargetStatuses || [],
  lastPublishResults: tab.lastPublishResults || [],
  lastPublishTaskId: tab.lastPublishTaskId || '',
  scheduleEnabled: tab.scheduleEnabled,
  scheduledAt: tab.scheduledAt || '',
  isDraft: tab.isDraft,
  isOriginal: tab.isOriginal
})

const savePublishDraft = () => {
  try {
    localStorage.setItem(PUBLISH_DRAFT_STORAGE_KEY, JSON.stringify({
      activeTab: activeTab.value,
      tabCounter,
      tabs: tabs.map(serializePublishTab)
    }))
  } catch (error) {
    console.warn('保存发布中心草稿失败:', error)
  }
}

const restoredDraft = readPublishDraft()
const restoredTabs = restoredDraft?.tabs?.length
  ? restoredDraft.tabs.map(normalizePublishTab)
  : [makeNewTab()]

if (restoredDraft?.activeTab && restoredTabs.some(tab => tab.name === restoredDraft.activeTab)) {
  activeTab.value = restoredDraft.activeTab
}

tabCounter = Math.max(
  Number(restoredDraft?.tabCounter || 1),
  ...restoredTabs.map(tab => Number(String(tab.name).replace('tab', '')) || 1)
)

// tab页数据 - 默认只有一个tab (use deep copy to avoid shared refs)
const tabs = reactive(restoredTabs)

watch(activeTab, savePublishDraft)
watch(tabs, savePublishDraft, { deep: true })

// 账号相关状态
const accountDialogVisible = ref(false)
const tempPlatformAccounts = ref({})
const currentTab = ref(null)

// 话题相关状态
const topicDialogVisible = ref(false)
const customTopic = ref('')

// 推荐话题列表
const recommendedTopics = [
  '游戏', '电影', '音乐', '美食', '旅行', '文化',
  '科技', '生活', '娱乐', '体育', '教育', '艺术',
  '健康', '时尚', '美妆', '摄影', '宠物', '汽车'
]

// 添加新tab
const addTab = () => {
  tabCounter++
  const newTab = makeNewTab()
  newTab.name = `tab${tabCounter}`
  newTab.label = `发布${tabCounter}`
  tabs.push(newTab)
  activeTab.value = newTab.name
}

// 删除tab
const removeTab = (tabName) => {
  const index = tabs.findIndex(tab => tab.name === tabName)
  if (index > -1) {
    tabs.splice(index, 1)
    // 如果删除的是当前激活的tab，切换到第一个tab
    if (activeTab.value === tabName && tabs.length > 0) {
      activeTab.value = tabs[0].name
    }
  }
}

const resetAgentGuard = (tab) => {
  tab.agentGuardRequestId = Number(tab.agentGuardRequestId || 0) + 1
  tab.agentChecking = false
  tab.agentGuardLoading = false
  tab.agentGuardStatus = 'idle'
  tab.agentGuardResult = null
  tab.agentGuardRunId = ''
  tab.agentGuardConfirmReason = ''
}

const clearVideoDerivedContent = (tab) => {
  resetAgentGuard(tab)
  tab.title = ''
  tab.description = ''
  tab.selectedTopics = []
  tab.productLink = ''
  tab.productTitle = ''
  tab.bilibiliTid = defaultBilibiliTid.value
  tab.platformAccounts = {}
  tab.selectedAccounts = []
  tab.publishTargetStatuses = []
  tab.contentLocked = false
  tab.publishStatus = null
  tab.sourceContentConfirmed = false
}

// 删除已上传文件
const removeFile = (tab, index) => {
  // 从文件列表中删除
  tab.fileList.splice(index, 1)
  
  // 更新显示列表
  tab.displayFileList = [...tab.fileList.map(item => ({
    name: item.name,
    url: item.url
  }))]

  if (tab.fileList.length === 0) {
    clearVideoDerivedContent(tab)
  }
  
  ElMessage.success('文件删除成功')
}

const normalizeAnalysisTags = (tags = []) => {
  return Array.isArray(tags)
    ? tags.map(tag => String(tag || '').trim().replace(/^#/, '')).filter(Boolean)
    : []
}

const normalizePublishDraft = (material) => {
  const draft = material?.publishDraft || {}
  if (draft && Object.keys(draft).length > 0) {
    return {
      title: draft.title || '',
      description: draft.description || '',
      tags: normalizeAnalysisTags(draft.tags),
      fromSavedDraft: true
    }
  }

  const result = material?.analysisResult || {}
  const titleOptions = Array.isArray(result.title_options) ? result.title_options.filter(Boolean) : []
  return {
    title: titleOptions[0] || '',
    description: result.publish_copy || '',
    tags: normalizeAnalysisTags(result.tags),
    fromSavedDraft: false
  }
}

const materialPublishDraft = (material) => normalizePublishDraft(material)

const publishDraftSnapshot = (draft = {}) => ({
  title: String(draft.title || '').trim(),
  description: String(draft.description || '').trim(),
  tags: normalizeAnalysisTags(draft.tags)
})

const hasStalePublishDraft = (tab, draft) => {
  const current = publishDraftSnapshot(draft)
  const selected = publishDraftSnapshot({
    title: tab.title,
    description: tab.description,
    tags: tab.selectedTopics
  })
  return current.title !== selected.title
    || current.description !== selected.description
    || current.tags.join('\n') !== selected.tags.join('\n')
}

const ensureLatestPublishDraftConfirmation = async (tab) => {
  const videoId = selectedVideoId(tab)
  if (!videoId) return
  try {
    const response = await youtubeApi.getVideoAnalysis(videoId)
    if (!hasStalePublishDraft(tab, response.data?.draft)) return
  } catch (error) {
    ElMessage.warning('未能检查发布稿是否更新，将按当前批次内容继续提交')
    return
  }

  const scheduled = Boolean(tab.scheduleEnabled)
  const message = scheduled
    ? '当前批次仍显示选择素材时的旧发布稿。定时任务执行时会读取视频采集与处理页最新保存的发布稿，本页预览不会自动同步。'
    : '当前批次仍使用选择素材时的旧发布稿。立即发布将使用旧稿，不会使用视频采集与处理页后来保存的新稿。'
  try {
    await ElMessageBox.confirm(message, '发布稿已更新', {
      confirmButtonText: scheduled ? '创建定时任务' : '仍使用旧稿发布',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    throw new Error('已取消发布')
  }
}

const accountsByPlatform = (platformName) => {
  return accountStore.accounts.filter(account => account.platform === platformName)
}

const availableAccountsByPlatform = (platformName) => {
  return accountsByPlatform(platformName).filter(account => account.status === '正常')
}

const selectedVideoId = (tab) => {
  return tab.fileList[0]?.videoId || ''
}

const selectedMaterialId = (tab) => String(tab?.fileList?.[0]?.materialId || '')

const sourceContentRisk = (tab) => tab?.fileList?.[0]?.analysisResult?.contentRisk || null

const ensureSourceContentRiskConfirmation = async (tab) => {
  const risk = sourceContentRisk(tab)
  if (!risk?.requiresPublishConfirmation || tab.sourceContentConfirmed) return
  try {
    await ElMessageBox.confirm(
      '检测到转写中含明确粗口，中文字幕已打码，但原声及英文字幕可能仍含风险。是否继续发布？',
      '发布前内容确认',
      {
        confirmButtonText: '继续发布',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    tab.sourceContentConfirmed = true
  } catch {
    throw new Error('已取消发布')
  }
}

const publishedPlatformTypesForVideo = (videoId) => {
  if (!videoId) return []
  const video = publishedVideos.value.find(item => item.id === videoId)
  return video?.publishedPlatformTypes || []
}

const loadPublishableMaterials = async ({ force = false } = {}) => {
  const params = {
    sourceType: 'youtube_processed',
    page: materialLibraryPagination.page,
    pageSize: materialLibraryPagination.pageSize,
    keyword: materialLibraryKeyword.value.trim(),
    groupId: materialLibraryGroupId.value || undefined
  }
  const cacheKey = `publish:center:materials:${JSON.stringify(params)}`
  if (!force) {
    const cached = appStore.getListCache(cacheKey)
    if (cached) {
      publishableMaterials.value = cached.items || []
      materialLibraryTotal.value = Number(cached.total || 0)
    }
  }

  materialLibraryLoading.value = true
  try {
    const response = await materialApi.getAllMaterials(params)
    const payload = response.data || {}
    publishableMaterials.value = payload.items || []
    materialLibraryTotal.value = Number(payload.total || 0)
    materialLibraryPagination.page = Number(payload.page || materialLibraryPagination.page)
    materialLibraryPagination.pageSize = Number(payload.pageSize || materialLibraryPagination.pageSize)
    appStore.setListCache(cacheKey, payload)
  } catch (error) {
    console.error('获取可发布素材失败:', error)
    ElMessage.error('获取素材列表失败')
  } finally {
    materialLibraryLoading.value = false
  }
}

const loadAccounts = async () => {
  try {
    const response = await accountApi.getAccounts()
    accountStore.setAccounts(response.data || [])
  } catch (error) {
    console.error('刷新账号状态失败:', error)
  }
}

const handleMaterialLibrarySearch = () => {
  window.clearTimeout(materialLibrarySearchTimer)
  selectedMaterial.value = null
  materialLibrarySearchTimer = window.setTimeout(() => {
    materialLibraryPagination.page = 1
    loadPublishableMaterials({ force: true })
  }, 300)
}

watch(materialLibraryGroupId, () => {
  selectedMaterial.value = null
  materialLibraryPagination.page = 1
  if (materialLibraryVisible.value) loadPublishableMaterials({ force: true })
})

watch(
  () => materialLibraryPagination.page,
  () => {
    selectedMaterial.value = null
    if (materialLibraryVisible.value) {
      loadPublishableMaterials()
    }
  }
)

const isPlatformPublishedForTab = (tab, platformType) => {
  return publishedPlatformTypesForVideo(selectedVideoId(tab)).includes(Number(platformType))
}

const isPlatformDisabledForCurrentTab = (platformType) => {
  return currentTab.value ? isPlatformPublishedForTab(currentTab.value, platformType) : false
}

const publishTargets = (tab) => {
  return Object.entries(tab.platformAccounts || {})
    .map(([platformType, accountId]) => {
      const platform = platforms.find(item => String(item.key) === String(platformType))
      const account = accountStore.accounts.find(item => String(item.id) === String(accountId))
      if (!platform || !account || account.status !== '正常') return null
      return {
        platformType: platform.key,
        platformName: platform.name,
        accountId: account.id,
        accountName: account.name,
        accountFile: account.filePath
      }
    })
    .filter(Boolean)
}

const topicsForTarget = (tab, target) => {
  const topics = Array.isArray(tab?.selectedTopics) ? tab.selectedTopics : []
  return Number(target?.platformType) === 3 ? topics.slice(0, 5) : topics
}

const isDouyinTopicTruncated = (tab, target) => {
  return Number(target?.platformType) === 3 && Array.isArray(tab?.selectedTopics) && tab.selectedTopics.length > 5
}

const formatTopicsForTarget = (tab, target) => {
  const topics = topicsForTarget(tab, target)
  return topics.length ? topics.map(topic => `#${topic}`).join(' ') : '暂无话题'
}

const targetStatusList = (tab) => {
  const statusMap = new Map((tab.publishTargetStatuses || []).map(item => [Number(item.platformType), item]))
  return publishTargets(tab).map(target => ({
    ...target,
    status: statusMap.get(Number(target.platformType))?.status || 'pending',
    message: statusMap.get(Number(target.platformType))?.message || '等待发布'
  }))
}

const publishStatusLabel = (status) => {
  const map = {
    pending: '待发布',
    running: '发布中',
    success: '成功',
    failed: '失败',
    timeout: '超时',
    unknown: '待核验'
  }
  return map[status] || status || '待发布'
}

const publishStatusTagType = (status) => {
  if (status === 'success') return 'success'
  if (status === 'failed' || status === 'timeout') return 'danger'
  if (status === 'unknown') return 'warning'
  if (status === 'running') return 'warning'
  return 'info'
}

const hasSelectedPlatform = (tab, platformType) => {
  return publishTargets(tab).some(target => Number(target.platformType) === Number(platformType))
}

const applyPublishDraftToPublishTab = (tab, drafts = []) => {
  const firstDraft = drafts.find(draft => draft && (draft.title || draft.description || draft.tags.length > 0))
  if (!firstDraft) return

  tab.title = firstDraft.title || ''
  tab.description = firstDraft.description || ''
  tab.selectedTopics = firstDraft.tags || []
  tab.contentLocked = true

  if (!firstDraft.fromSavedDraft) {
    ElMessage.warning('该素材还没有保存发布稿，已用 LLM 原稿临时填充；如需修改请回到视频采集与处理页。')
  }
}

const saveTabPublishDraft = async (tab) => {
  const targetFile = tab.fileList.find(file => file.videoId)
  if (!targetFile) {
    ElMessage.warning('当前批次没有绑定视频线索的素材，无法保存发布稿')
    return
  }
  try {
    const response = await youtubeApi.updatePublishDraft(targetFile.videoId, {
      title: tab.title,
      description: tab.description,
      tags: tab.selectedTopics
    })
    const savedDraft = response.data?.draft || {
      title: tab.title,
      description: tab.description,
      tags: tab.selectedTopics
    }
    tab.fileList.forEach(file => {
      if (file.videoId === targetFile.videoId) {
        file.publishDraft = savedDraft
      }
    })
    const material = appStore.materials.find(item => String(item.id) === String(targetFile.materialId))
    if (material) {
      material.publishDraft = savedDraft
    }
    tab.contentLocked = true
    ElMessage.success('发布稿已保存到视频')
  } catch (error) {
    console.error('保存发布稿失败:', error)
    ElMessage.error('保存发布稿失败')
  }
}

// 话题相关方法
// 打开添加话题弹窗
const openTopicDialog = (tab) => {
  currentTab.value = tab
  topicDialogVisible.value = true
}

// 添加自定义话题
const addCustomTopic = () => {
  if (!customTopic.value.trim()) {
    ElMessage.warning('请输入话题内容')
    return
  }
  if (currentTab.value && !currentTab.value.selectedTopics.includes(customTopic.value.trim())) {
    currentTab.value.selectedTopics.push(customTopic.value.trim())
    customTopic.value = ''
    ElMessage.success('话题添加成功')
  } else {
    ElMessage.warning('话题已存在')
  }
}

// 切换推荐话题
const toggleRecommendedTopic = (topic) => {
  if (!currentTab.value) return
  
  const index = currentTab.value.selectedTopics.indexOf(topic)
  if (index > -1) {
    currentTab.value.selectedTopics.splice(index, 1)
  } else {
    currentTab.value.selectedTopics.push(topic)
  }
}

// 删除话题
const removeTopic = (tab, index) => {
  if (tab.contentLocked) {
    ElMessage.info('发布内容需在视频采集与处理页修改并保存')
    return
  }
  tab.selectedTopics.splice(index, 1)
}

// 确认添加话题
const confirmTopicSelection = () => {
  topicDialogVisible.value = false
  customTopic.value = ''
  currentTab.value = null
  ElMessage.success('添加话题完成')
}

// 账号选择相关方法
// 打开账号选择弹窗
const openAccountDialog = (tab) => {
  currentTab.value = tab
  tempPlatformAccounts.value = { ...(tab.platformAccounts || {}) }
  accountDialogVisible.value = true
}

// 确认账号选择
const confirmAccountSelection = () => {
  if (currentTab.value) {
    const normalized = normalizePlatformAccounts(tempPlatformAccounts.value)
    Object.keys(normalized).forEach(platformType => {
      if (isPlatformPublishedForTab(currentTab.value, platformType)) {
        delete normalized[platformType]
        return
      }
      const account = accountStore.accounts.find(item => String(item.id) === String(normalized[platformType]))
      if (!account || account.status !== '正常') {
        delete normalized[platformType]
      }
    })
    currentTab.value.platformAccounts = normalized
    currentTab.value.selectedAccounts = Object.values(normalized)
    currentTab.value.publishTargetStatuses = publishTargets(currentTab.value).map(target => ({
      platformType: target.platformType,
      platformName: target.platformName,
      accountName: target.accountName,
      status: 'pending',
      message: '等待发布'
    }))
  }
  accountDialogVisible.value = false
  currentTab.value = null
  ElMessage.success('账号选择完成')
}

// 删除选中的账号
const removeAccount = (tab, index) => {
  tab.selectedAccounts.splice(index, 1)
  tab.selectedAccounts = normalizeSelectedAccounts(tab.selectedAccounts)
  savePublishDraft()
}

const removePlatformAccount = (tab, platformType) => {
  delete tab.platformAccounts[String(platformType)]
  tab.selectedAccounts = Object.values(tab.platformAccounts)
  tab.publishTargetStatuses = (tab.publishTargetStatuses || []).filter(item => Number(item.platformType) !== Number(platformType))
  savePublishDraft()
}

// 获取账号显示名称
const getAccountDisplayName = (accountId) => {
  const account = accountStore.accounts.find(acc => acc.id === accountId)
  return account ? account.name : accountId
}

const processVersionLabel = (value) => {
  const labelMap = {
    translation_v1: '处理版本一',
    editing_v1: '处理版本二'
  }
  return labelMap[value] || value || '处理版本未知'
}

const formatFileSize = (size) => {
  const bytes = Number(size || 0)
  if (!bytes) return '-'
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const formatMaterialSizeMb = (size) => {
  const mb = Number(size || 0)
  if (!mb) return ''
  return `${mb.toFixed(2)} MB`
}

const materialByVideoId = computed(() => {
  const map = new Map()
  appStore.materials.forEach(material => {
    if (material.source_type !== 'youtube_processed') return
    const videoId = material.source_video_id || material.metadata?.videoId
    if (!videoId) return
    const existing = map.get(videoId)
    if (!existing || Number(material.id || 0) > Number(existing.id || 0)) {
      map.set(videoId, material)
    }
  })
  return map
})

const publishedMaterialCount = computed(() => {
  return publishedVideos.value.filter(video => Boolean(video.processedFilePath)).length
})

const allPublishedRecords = computed(() => {
  return publishedVideos.value.flatMap(video => video.publishedRecords || [])
})

const publishedPlatformStats = computed(() => {
  return allPublishedRecords.value.reduce((stats, record) => {
    if (Number(record.platformType) === 3) stats.douyin += 1
    if (Number(record.platformType) === 5) stats.bilibili += 1
    return stats
  }, { douyin: 0, bilibili: 0 })
})

const publishedPlatforms = (video) => {
  const tags = (video.publishedPlatformTypes || [])
    .map(platformType => platformNameByKey[platformType])
    .filter(Boolean)
  if (tags.length === 0) tags.push('发布中心')
  return tags
}

const formatPublishDuration = (durationMs) => {
  const seconds = Math.round(Number(durationMs || 0) / 1000)
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

const askAgentAboutPublishedVideo = (video) => {
  window.dispatchEvent(new CustomEvent('vidferry:ask-agent', {
    detail: {
      videoContext: {
        source: 'publish-center',
        videoId: String(video.id || ''),
        title: video.title || '',
        url: video.url || '',
        channel: video.channel || '',
        subscribers: video.subscribers || '',
        sourcePublishedAt: video.publishedAt || '',
        duration: video.duration || '',
        processVersion: video.processVersionLabel || '',
        subtitleLanguage: video.subtitleLanguageLabel || '',
        fileSize: video.processedFileSizeLabel || '',
        publishedPlatforms: publishedPlatforms(video),
        publishedRecords: (video.publishedRecords || []).map(record => ({
          platform: record.platform || platformNameByKey[Number(record.platformType)] || '',
          platformType: Number(record.platformType || 0),
          accountName: record.accountName || '',
          status: record.status || 'success',
          publishedAt: record.publishedAt || record.updatedAt || ''
        }))
      }
    }
  }))
}

const loadPublishedVideos = async () => {
  publishedLoading.value = true
  try {
    if (publishedRecordScope.value === 'archived') {
      const response = await materialApi.getPublishedMaterials({ limit: 200, recordScope: 'archived' })
      archivedPublishedRecords.value = response?.data || []
      return
    }
    const [videoResponse, publishedResponse] = await Promise.all([
      youtubeApi.list({ page: 1, pageSize: 100, status: 'published', sort: 'publishedFirst' }),
      materialApi.getPublishedMaterials({ limit: 200, recordScope: 'active' })
    ])
    const sourceItems = videoResponse?.data?.items || []
    const sourceVideoIds = sourceItems.map(item => item.id).filter(Boolean)
    const materialResponse = sourceVideoIds.length
      ? await materialApi.getAllMaterials({
        sourceType: 'youtube_processed',
        videoIds: sourceVideoIds.join(','),
        page: 1,
        pageSize: Math.min(sourceVideoIds.length, 100)
      })
      : null
    if (materialResponse?.code === 200) {
      appStore.setMaterials(materialResponse.data?.items || [])
    }
    const publishedRecords = publishedResponse?.data || []
    const publishedByVideoId = new Map()
    publishedRecords.forEach(record => {
      if (!record.videoId) return
      if (!publishedByVideoId.has(record.videoId)) {
        publishedByVideoId.set(record.videoId, [])
      }
      publishedByVideoId.get(record.videoId).push(record)
    })
    publishedVideos.value = sourceItems
      .filter(item => item.publishStatus === 1)
      .map(item => {
        const material = materialByVideoId.value.get(item.id)
        const records = sortPublishedRecords(publishedByVideoId.get(item.id) || [])
        return {
          ...item,
          publishedRecords: records,
          publishedPlatformTypes: Array.from(new Set(records.map(record => Number(record.platformType)).filter(Boolean))),
          processVersionLabel: material ? processVersionLabel(material.processVersion) : processVersionLabel(item.processVersion),
          subtitleLanguageLabel: material?.subtitleLanguageLabel || item.subtitleLanguageLabel || '字幕语言未知',
          processedFilePath: material?.file_path || item.processedFilePath || '',
          processedPreviewUrl: material?.file_path ? materialApi.getMaterialPreviewUrl(material.file_path.split('/').pop()) : '',
          processedFileSizeLabel: material ? formatMaterialSizeMb(material.filesize) : '',
          publishedLabel: item.updatedAt ? `状态更新时间 ${item.updatedAt}` : '已提交发布'
        }
      })
  } catch (error) {
    console.error('加载已发布视频失败:', error)
    ElMessage.error('加载已发布视频失败')
  } finally {
    publishedLoading.value = false
  }
}

const loadPublishRetryTasks = async () => {
  try {
    const response = await materialApi.getPublishTasks({ limit: 50 })
    retryablePublishTasks.value = (response.data || []).filter(task => task.canRetry)
  } catch (error) {
    console.error('加载可重发发布任务失败:', error)
  }
}

const openRetryDialog = (task) => {
  retryTask.value = task
  retryDialogVisible.value = true
}

const refreshPublishRetryTasks = async () => {
  await Promise.all([loadPublishRetryTasks(), loadPublishedVideos()])
  appStore.invalidatePublishRecords()
}

// 取消发布
const cancelPublish = (tab) => {
  ElMessage.info('已取消发布')
}

const buildPublishData = (tab, targets = publishTargets(tab)) => ({
  title: tab.title,
  description: tab.description,
  tags: tab.selectedTopics,
  fileList: tab.fileList.map(file => file.path),
  targets: targets.map(target => ({
    platformType: target.platformType,
    accountFile: target.accountFile,
    accountId: target.accountId,
    accountName: target.accountName,
    tags: topicsForTarget(tab, target),
    bilibiliTid: Number(target.platformType) === 5 ? Number(tab.bilibiliTid || defaultBilibiliTid.value) : undefined,
    productLink: Number(target.platformType) === 3 ? tab.productLink.trim() : undefined,
    productTitle: Number(target.platformType) === 3 ? tab.productTitle.trim() : undefined
  })),
  scheduledAt: tab.scheduleEnabled ? tab.scheduledAt : '',
  category: tab.isOriginal ? 1 : 0,
  bilibiliTid: Number(tab.bilibiliTid || defaultBilibiliTid.value),
  productLink: tab.productLink.trim() || '',
  productTitle: tab.productTitle.trim() || '',
  isDraft: tab.isDraft,
  riskOverride: {
    sourceContentConfirmed: Boolean(tab.sourceContentConfirmed)
  }
})

const disabledScheduleDate = (date) => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const lastDay = new Date(today)
  lastDay.setDate(lastDay.getDate() + 9)
  return date < today || date > lastDay
}

const deletePublishedRecord = async (record) => {
  try {
    await ElMessageBox.confirm(
      `确认删除「${record.platform}」的本地发布记录？不会删除平台上的视频，删除后可重新发布。`,
      '删除本地发布记录',
      { confirmButtonText: '删除记录', cancelButtonText: '取消', type: 'warning' }
    )
    const response = await materialApi.deletePublishTargetRecord(record.id)
    publishedVideos.value = publishedVideos.value
      .map(video => video.id === record.videoId
        ? { ...video, publishedRecords: video.publishedRecords.filter(item => item.id !== record.id) }
        : video)
      .filter(video => video.publishedRecords.length > 0)
    appStore.invalidatePublishRecords(response.data?.videoId || record.videoId)
    ElMessage.success(response.msg || '已删除本地发布记录')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  }
}

const scheduleComparingDate = (tab, comparingDate) => {
  if (comparingDate?.toDate) return comparingDate.toDate()
  if (comparingDate) return comparingDate
  const scheduledAt = String(tab?.scheduledAt || '').trim()
  return scheduledAt ? new Date(scheduledAt.replace(' ', 'T')) : new Date()
}

const isScheduleToday = (tab, comparingDate) => {
  const date = scheduleComparingDate(tab, comparingDate)
  const value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return value === today
}

const disabledScheduleHours = (tab, comparingDate) => {
  if (!isScheduleToday(tab, comparingDate)) return []
  return Array.from({ length: new Date().getHours() }, (_, hour) => hour)
}

const disabledScheduleMinutes = (tab, hour, comparingDate) => {
  const now = new Date()
  if (!isScheduleToday(tab, comparingDate) || Number(hour) !== now.getHours()) return []
  return Array.from({ length: now.getMinutes() + 1 }, (_, minute) => minute)
}

const extractAgentErrorData = (error) => error?.response?.data?.data || {}

const normalizeAgentGuardInput = (summary = {}) => ({
  title: String(summary.title || '').trim(),
  description: String(summary.description || '').trim(),
  tags: normalizeAnalysisTags(summary.tags),
  fileList: (Array.isArray(summary.fileList) ? summary.fileList : []).map(item => String(item || '').trim()),
  targets: (Array.isArray(summary.targets) ? summary.targets : [])
    .map(target => ({
      platformType: Number(target?.platformType || 0),
      accountId: String(target?.accountId || ''),
      accountName: String(target?.accountName || ''),
      tags: normalizeAnalysisTags(target?.tags)
    }))
    .sort((left, right) => left.platformType - right.platformType || left.accountId.localeCompare(right.accountId))
})

const currentAgentGuardInput = (tab) => normalizeAgentGuardInput(buildPublishData(tab, publishTargets(tab)))

const agentGuardInputSignature = (summary) => JSON.stringify(normalizeAgentGuardInput(summary))

const isAgentGuardStale = (tab) => {
  const previous = tab?.agentGuardResult?.inputSummary
  if (previous && Object.keys(previous).length > 0) {
    return agentGuardInputSignature(previous) !== agentGuardInputSignature(currentAgentGuardInput(tab))
  }
  return Boolean(tab?.agentGuardResult?.contentChanged)
}

const formatAgentGuardTime = (value) => {
  const text = String(value || '').trim().replace('T', ' ')
  return text ? text.replace(/\..*$/, '').slice(0, 19) : '-'
}

const agentGuardIssues = (tab) => {
  const issues = tab?.agentGuardResult?.issues
  return Array.isArray(issues) ? issues : []
}

const agentGuardLabel = (tab) => {
  if (tab?.agentChecking) return '质检中'
  if (tab?.agentGuardStatus === 'allow') return '已通过'
  if (tab?.agentGuardStatus === 'warn') return '需确认'
  if (tab?.agentGuardStatus === 'block') return '已拦截'
  if (tab?.agentGuardStatus === 'failed') return '质检失败'
  return '未质检'
}

const agentGuardTagType = (tab) => {
  if (tab?.agentGuardStatus === 'allow') return 'success'
  if (tab?.agentGuardStatus === 'warn') return 'warning'
  if (tab?.agentGuardStatus === 'block' || tab?.agentGuardStatus === 'failed') return 'danger'
  return 'info'
}

const agentGuardSummary = (tab) => {
  const result = tab?.agentGuardResult || {}
  if (tab?.agentGuardStatus === 'allow') return '没有发现阻断风险，可以发布。'
  if (tab?.agentGuardStatus === 'warn') return '发现中低风险，填写人工确认原因后可继续。'
  if (tab?.agentGuardStatus === 'block') return '发现高风险或关键帧审核未完成，已阻断发布。'
  if (tab?.agentGuardStatus === 'failed') return result.message || '质检失败，请检查后端配置。'
  return ''
}

const ensureAgentGuardPublishConfirmation = async (tab) => {
  if (!['warn', 'block', 'failed'].includes(tab.agentGuardStatus)) return
  const message = tab.agentGuardStatus === 'failed'
    ? '本次 Agent 质检未完成。普通发布不受此影响，确认后仍会提交到已选平台。'
    : '本次 Agent 质检发现风险。普通发布不受此影响，确认后仍会提交到已选平台。'
  try {
    await ElMessageBox.confirm(message, '确认继续发布', {
      confirmButtonText: '仍然发布',
      cancelButtonText: '返回检查',
      type: 'warning'
    })
  } catch {
    throw new Error('已取消发布')
  }
}

const applyAgentGuardResult = (tab, guard, expectedMaterialId = '') => {
  const currentMaterialId = selectedMaterialId(tab)
  const resultMaterialId = String(guard?.materialId || expectedMaterialId || '')
  if (!currentMaterialId || (expectedMaterialId && currentMaterialId !== String(expectedMaterialId)) || (resultMaterialId && currentMaterialId !== resultMaterialId)) {
    return false
  }
  const decision = guard?.decision || 'failed'
  tab.agentGuardResult = guard || {}
  tab.agentGuardRunId = guard?.runId || ''
  tab.agentGuardStatus = ['allow', 'warn', 'block'].includes(decision) ? decision : 'failed'
  if (decision !== 'warn') {
    tab.agentGuardConfirmReason = ''
  }
  return true
}

const loadLatestAgentGuard = async (tab) => {
  resetAgentGuard(tab)
  const materialId = selectedMaterialId(tab)
  if (!materialId) return
  const requestId = tab.agentGuardRequestId
  tab.agentGuardLoading = true
  try {
    const publishData = buildPublishData(tab, publishTargets(tab))
    const res = await agentApi.latestPrepublishCheck({ publishData })
    if (tab.agentGuardRequestId !== requestId || selectedMaterialId(tab) !== materialId) return
    if (res?.data) applyAgentGuardResult(tab, res.data, materialId)
  } catch (error) {
    if (tab.agentGuardRequestId === requestId && selectedMaterialId(tab) === materialId) {
      console.warn('读取视频最新质检结果失败:', error)
    }
  } finally {
    if (tab.agentGuardRequestId === requestId && selectedMaterialId(tab) === materialId) {
      tab.agentGuardLoading = false
    }
  }
}

const runAgentPrepublishCheck = async (tab) => {
  const materialId = selectedMaterialId(tab)
  if (!materialId) {
    ElMessage.warning('请先选择需要质检的视频')
    return null
  }
  const targets = publishTargets(tab)
  const publishData = buildPublishData(tab, targets)
  const requestId = Number(tab.agentGuardRequestId || 0) + 1
  tab.agentGuardRequestId = requestId
  tab.agentChecking = true
  try {
    const res = await agentApi.prepublishCheck({ publishData })
    if (tab.agentGuardRequestId !== requestId || selectedMaterialId(tab) !== materialId) return null
    if (!applyAgentGuardResult(tab, res?.data || {}, materialId)) return null
    if (tab.agentGuardStatus === 'allow') ElMessage.success('发布前质检通过')
    if (tab.agentGuardStatus === 'warn') ElMessage.warning('发布前质检发现风险，请确认后再发布')
    if (tab.agentGuardStatus === 'block') ElMessage.error('发布前质检已拦截')
    return tab.agentGuardResult
  } catch (error) {
    if (tab.agentGuardRequestId !== requestId || selectedMaterialId(tab) !== materialId) return null
    const data = extractAgentErrorData(error)
    const guard = data.guard || null
    if (guard) {
      applyAgentGuardResult(tab, guard, materialId)
    } else {
      tab.agentGuardStatus = 'failed'
      tab.agentGuardResult = {
        materialId,
        checkedAt: new Date().toISOString(),
        inputSummary: currentAgentGuardInput(tab),
        message: error?.response?.data?.msg || error.message || '质检失败'
      }
    }
    ElMessage.error(tab.agentGuardResult?.message || error?.response?.data?.msg || error.message || '质检失败')
    throw error
  } finally {
    if (tab.agentGuardRequestId === requestId && selectedMaterialId(tab) === materialId) {
      tab.agentChecking = false
    }
  }
}

// 确认发布
const confirmPublish = async (tab) => {
  // 防止重复点击
  if (tab.publishing) {
    throw new Error('正在发布中，请稍候...')
  }

  tab.publishing = true // 设置发布状态为进行中

  // 数据验证
  if (tab.fileList.length === 0) {
    ElMessage.error('请先选择处理后视频')
    tab.publishing = false
    throw new Error('请先选择处理后视频')
  }
  if (tab.fileList.length > 1) {
    ElMessage.error('每个发布批次只能选择一个视频，请删除多余视频后再发布')
    tab.publishing = false
    throw new Error('每个发布批次只能选择一个视频')
  }
  const invalidFiles = tab.fileList.filter(file => file.sourceType !== 'youtube_processed')
  if (invalidFiles.length > 0) {
    ElMessage.error('发布中心只支持处理后视频，请重新选择素材')
    tab.publishing = false
    throw new Error('发布中心只支持处理后视频')
  }
  if (!tab.title.trim()) {
    ElMessage.error('发布标题为空，请回到视频采集与处理页保存发布稿')
    tab.publishing = false
    throw new Error('发布标题为空')
  }
  const targets = publishTargets(tab)
  if (targets.length === 0) {
    ElMessage.error('请至少选择一个平台账号')
    tab.publishing = false
    throw new Error('请至少选择一个平台账号')
  }
  if (tab.scheduleEnabled && !tab.scheduledAt) {
    ElMessage.error('请选择计划发布时间')
    tab.publishing = false
    throw new Error('请选择计划发布时间')
  }
  const duplicatedTarget = targets.find(target => isPlatformPublishedForTab(tab, target.platformType))
  if (duplicatedTarget) {
    ElMessage.error(`该视频已发布到${duplicatedTarget.platformName}，不能重复发布`)
    tab.publishing = false
    throw new Error(`该视频已发布到${duplicatedTarget.platformName}`)
  }
  const douyinTarget = targets.find(target => isDouyinTopicTruncated(tab, target))
  if (douyinTarget) {
    ElMessage.warning('抖音最多支持一次选择 5 条话题，本次发布将只使用前 5 条。')
  }
  tab.publishTargetStatuses = targets.map((target, index) => ({
    platformType: target.platformType,
    platformName: target.platformName,
    accountName: target.accountName,
    status: 'running',
    message: tab.scheduleEnabled ? '等待定时发布' : '发布中'
  }))
  tab.lastPublishResults = []
  tab.lastPublishTaskId = ''

  const updateTargetStatus = (target, patch) => {
    tab.publishTargetStatuses = tab.publishTargetStatuses.map(item => (
      Number(item.platformType) === Number(target.platformType)
        ? { ...item, ...patch }
        : item
    ))
  }

  // 一次提交所有平台，后端按平台隔离并发执行，同时返回每个平台结果。
  try {
    await ensureLatestPublishDraftConfirmation(tab)
    await ensureAgentGuardPublishConfirmation(tab)
    await ensureSourceContentRiskConfirmation(tab)
    const publishData = buildPublishData(tab, targets)
    const endpoint = tab.scheduleEnabled ? '/publish/scheduled-tasks' : '/postVideo'
    const data = await http.post(endpoint, publishData, { silentError: true })
    await loadAccounts()
    await loadPublishedVideos()
    if (tab.scheduleEnabled) {
      tab.publishStatus = { message: `定时任务已创建，将于 ${tab.scheduledAt.slice(0, 16)} 执行`, type: 'success' }
      ElMessage.success('定时发布任务已创建')
      tab.fileList = []
      tab.displayFileList = []
      tab.title = ''
      tab.description = ''
      tab.selectedTopics = []
      tab.contentLocked = false
      tab.selectedAccounts = []
      tab.platformAccounts = {}
      tab.publishTargetStatuses = []
      tab.scheduleEnabled = false
      tab.scheduledAt = ''
      resetAgentGuard(tab)
      return
    }
    const results = Array.isArray(data?.data?.results) ? data.data.results : []
    tab.lastPublishResults = results
    tab.lastPublishTaskId = String(data?.data?.publishTaskId || '')
    results.forEach(result => {
      const target = targets.find(item => Number(item.platformType) === Number(result.platformType))
      if (!target) return
      updateTargetStatus(target, {
        platformType: target.platformType,
        platformName: target.platformName,
        accountName: target.accountName,
        status: result?.status || 'success',
        message: result?.message || '发布成功'
      })
    })
    const resultCount = results.length || targets.length
    const failedCount = tab.publishTargetStatuses.filter(item => item.status === 'failed' || item.status === 'timeout').length
    const unknownCount = tab.publishTargetStatuses.filter(item => item.status === 'unknown').length
    const successCount = resultCount - failedCount - unknownCount
    tab.publishStatus = {
      message: unknownCount
        ? `发布完成：${successCount} 个成功，${failedCount} 个失败，${unknownCount} 个待核验`
        : (failedCount ? `发布完成：${successCount} 个成功，${failedCount} 个失败` : `发布成功，已提交 ${resultCount} 个平台`),
      type: (failedCount + unknownCount) === resultCount ? 'error' : ((failedCount + unknownCount) ? 'warning' : 'success')
    }
    if (failedCount || unknownCount) {
      notificationStore.addDirectPublishFailureMessage({
        publishTaskId: tab.lastPublishTaskId,
        tabName: tab.name,
        title: tab.title,
        failedPlatforms: tab.publishTargetStatuses
          .filter(item => item.status === 'failed' || item.status === 'timeout' || item.status === 'unknown')
          .map(item => item.platformName),
        reason: tab.publishStatus.message,
        createdAt: Date.now()
      })
      return
    }
    // 清空当前tab的数据
    tab.fileList = []
    tab.displayFileList = []
    tab.title = ''
    tab.description = ''
    tab.selectedTopics = []
    tab.contentLocked = false
    resetAgentGuard(tab)
    tab.sourceContentConfirmed = false
    tab.selectedAccounts = []
    tab.platformAccounts = {}
    tab.scheduleEnabled = false
  } catch (error) {
    console.error('发布错误:', error)
    const agentData = extractAgentErrorData(error)
    if (agentData.guard) {
      applyAgentGuardResult(tab, agentData.guard)
    }
    const errorMessage = error?.response?.data?.msg || error.message || '请检查网络连接'
    await loadAccounts()
    await loadPublishedVideos()
    tab.publishTargetStatuses = targets.map(target => {
      const previous = (tab.publishTargetStatuses || []).find(item => Number(item.platformType) === Number(target.platformType))
      return {
        platformType: target.platformType,
        platformName: target.platformName,
        accountName: target.accountName,
        status: previous?.status === 'success' ? 'success' : 'failed',
        message: previous?.status === 'success' ? previous.message : errorMessage
      }
    })
    tab.publishStatus = {
      message: `发布失败：${errorMessage}`,
      type: 'error'
    }
    notificationStore.addDirectPublishFailureMessage({
      publishTaskId: tab.lastPublishTaskId,
      tabName: tab.name,
      title: tab.title,
      failedPlatforms: targets.map(target => target.platformName),
      reason: errorMessage,
      createdAt: Date.now()
    })
    throw error
  } finally {
    tab.publishing = false
  }
}

// 选择素材库
const selectMaterialLibrary = async (tab) => {
  if (tab.fileList.length > 0) {
    ElMessage.warning('当前批次已有视频，请先删除后再选择')
    return
  }
  currentUploadTab.value = tab
  selectedMaterial.value = null
  materialLibraryPagination.page = 1
  materialLibraryGroupId.value = ''
  materialLibraryVisible.value = true
  await loadPublishableMaterials()
}

// 确认素材选择
const confirmMaterialSelection = () => {
  if (selectedMaterial.value === null) {
    ElMessage.warning('请选择一个素材')
    return
  }
  
  if (currentUploadTab.value) {
    if (currentUploadTab.value.fileList.length > 0) {
      ElMessage.warning('当前批次已有视频，请先删除后再选择')
      return
    }
    const material = publishableMaterials.value.find(m => String(m.id) === String(selectedMaterial.value))
    if (!material) {
      ElMessage.error('选中的素材不存在，请刷新后重试')
      return
    }
    clearVideoDerivedContent(currentUploadTab.value)
    const selectedPublishDrafts = [normalizePublishDraft(material)]
    const fileInfo = {
      name: material.displayTitle || material.filename,
      displayTitle: material.displayTitle || material.filename,
      channel: material.displayChannel || '',
      processType: material.processType || '处理后视频',
      processVersion: material.processVersion || '',
      processVersionLabel: processVersionLabel(material.processVersion),
      subtitleLanguage: material.subtitleLanguage || '',
      subtitleLanguageLabel: material.subtitleLanguageLabel || '',
      sourceType: material.source_type,
      analysisResult: material.analysisResult || {},
      publishDraft: material.publishDraft || {},
      videoId: material.source_video_id || material.metadata?.videoId || '',
      materialId: material.id,
      url: materialApi.getMaterialPreviewUrl(material.file_path.split('/').pop()),
      path: material.file_path,
      size: material.filesize * 1024 * 1024, // 转换为字节
      type: 'video/mp4'
    }
    const targetTab = currentUploadTab.value
    targetTab.fileList = [fileInfo]
    targetTab.sourceContentConfirmed = false

    applyPublishDraftToPublishTab(targetTab, selectedPublishDrafts)
    
    // 更新显示列表
    targetTab.displayFileList = [...targetTab.fileList.map(item => ({
      name: item.name,
      url: item.url
    }))]
    void loadLatestAgentGuard(targetTab)
  }
  
  materialLibraryVisible.value = false
  selectedMaterial.value = null
  currentUploadTab.value = null
  ElMessage.success('已添加 1 个处理后视频')
}

// 批量发布对话框状态
const batchPublishDialogVisible = ref(false)
const currentPublishingTab = ref(null)
const publishProgress = ref(0)
const publishResults = ref([])
const isCancelled = ref(false)

// 取消批量发布
const cancelBatchPublish = () => {
  isCancelled.value = true
  ElMessage.info('正在取消发布...')
}

// 批量发布方法
const batchPublish = async () => {
  if (batchPublishing.value) return
  
  batchPublishing.value = true
  currentPublishingTab.value = null
  publishProgress.value = 0
  publishResults.value = []
  isCancelled.value = false
  batchPublishDialogVisible.value = true
  
  try {
    for (let i = 0; i < tabs.length; i++) {
      if (isCancelled.value) {
        publishResults.value.push({
          label: tabs[i].label,
          status: 'cancelled',
          message: '已取消'
        })
        continue
      }

      const tab = tabs[i]
      currentPublishingTab.value = tab
      publishProgress.value = Math.floor((i / tabs.length) * 100)
      
      try {
        await confirmPublish(tab)
        publishResults.value.push({
          label: tab.label,
          status: 'success',
          message: '发布成功'
        })
      } catch (error) {
        publishResults.value.push({
          label: tab.label,
          status: 'error',
          message: error.message
        })
        // 不立即返回，继续显示发布结果
      }
    }
    
    publishProgress.value = 100
    
    // 统计发布结果
    const successCount = publishResults.value.filter(r => r.status === 'success').length
    const failCount = publishResults.value.filter(r => r.status === 'error').length
    const cancelCount = publishResults.value.filter(r => r.status === 'cancelled').length
    
    if (isCancelled.value) {
      ElMessage.warning(`发布已取消：${successCount}个成功，${failCount}个失败，${cancelCount}个未执行`)
    } else if (failCount > 0) {
      ElMessage.error(`发布完成：${successCount}个成功，${failCount}个失败`)
    } else {
      ElMessage.success('所有Tab发布成功')
      setTimeout(() => {
        batchPublishDialogVisible.value = false
      }, 1000)
    }
    
  } catch (error) {
    console.error('批量发布出错:', error)
    ElMessage.error('批量发布出错，请重试')
  } finally {
    batchPublishing.value = false
    isCancelled.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadBilibiliCategories(), loadAccounts(), loadPublishedVideos(), loadPublishRetryTasks()])
  tabs.filter(tab => tab.fileList.length > 0).forEach(tab => {
    void loadLatestAgentGuard(tab)
  })
})

watch(publishedRecordScope, loadPublishedVideos)
watch(() => appStore.publishRecordsRevision, () => {
  void loadPublishedVideos()
  void loadPublishRetryTasks()
})

onBeforeUnmount(() => {
  window.clearTimeout(materialLibrarySearchTimer)
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: var(--vf-border);
$panel-shadow: var(--vf-shadow-md);
$accent-blue: var(--vf-primary);
$ink-strong: var(--vf-text-primary);

.publish-center {
  display: grid;
  gap: 16px;
}

.page-hero,
.batch-panel,
.compose-panel {
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: var(--vf-surface);
  box-shadow: $panel-shadow;
}

.page-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  background: var(--vf-surface);

  h1 { margin: 4px 0 8px; color: $ink-strong; font-size: 25px; line-height: 1.25; font-weight: 700; }
  p { margin: 0; color: var(--vf-text-regular); font-size: 14px; line-height: 1.7; }
}

.eyebrow,
.panel-kicker { color: $accent-blue; font-size: 12px; font-weight: 700; letter-spacing: 0; }

.hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }

.publish-workbench { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: start; }

.published-panel {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background: var(--vf-surface);
  box-shadow: $panel-shadow;
}

.panel-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  h2 { margin: 2px 0 6px; color: $ink-strong; font-size: 18px; }
  p { margin: 0; color: $text-secondary; font-size: 13px; line-height: 1.6; }
}

.published-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.published-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.summary-tile {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface-hover);

  span { color: $text-secondary; font-size: 12px; }
  strong { color: $ink-strong; font-size: 22px; line-height: 1.1; }
}

.published-list {
  display: grid;
  gap: 10px;
}

.retry-task-list { display: grid; gap: 8px; margin-top: 16px; }
.retry-task-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid $panel-border; padding: 10px 12px; }
.retry-task-row > div { display: grid; gap: 4px; min-width: 0; }
.retry-task-row span { color: $text-secondary; font-size: 12px; overflow-wrap: anywhere; }

.published-card {
  display: grid;
  grid-template-columns: 138px minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface);
}

.published-cover {
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 9;
  min-height: 78px;
  overflow: hidden;
  border-radius: 8px;
  background: #eef4fb;
  color: $accent-blue;
  font-size: 12px;
  font-weight: 700;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.published-body {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.published-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;

  h3 {
    margin: 0;
    color: $ink-strong;
    font-size: 15px;
    line-height: 1.45;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
}

.published-meta,
.published-tags,
.published-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: $text-secondary;
  font-size: 12px;
}

.published-actions {
  justify-content: space-between;
}

.published-record-list,
.archived-record-list {
  display: grid;
  border-top: 1px solid $border-lighter;
}

.published-record-row,
.archived-record-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid $border-lighter;
  color: $text-secondary;
  font-size: 12px;

  > div { display: flex; align-items: center; gap: 8px; min-width: 0; }
}

.archived-record-row {
  grid-template-columns: minmax(240px, 1fr) auto auto auto;
  padding: 12px 4px;

  > div { display: grid; align-items: initial; gap: 4px; }
  strong { color: $ink-strong; font-size: 13px; }
}

.batch-panel { padding: 14px; position: sticky; top: 12px; }
.panel-title h2 { margin: 2px 0 12px; color: $ink-strong; font-size: 18px; }
.batch-list { display: grid; gap: 8px; }
.batch-item { position: relative; display: grid; gap: 4px; width: 100%; padding: 12px 34px 12px 12px; border: 1px solid $border-lighter; border-radius: 8px; background: var(--vf-surface-hover); text-align: left; cursor: pointer; }
.batch-item.active { border-color: rgba(37, 99, 235, 0.42); background: rgba(37, 99, 235, 0.08); }
.batch-item span { color: $ink-strong; font-weight: 650; }
.batch-item small { color: $text-secondary; }
.close-icon { position: absolute; right: 10px; top: 12px; }

.compose-panel { padding: 16px; }
.compose-content { display: grid; gap: 14px; }
.form-section { display: grid; gap: 12px; padding: 14px; border: 1px solid $border-lighter; border-radius: 8px; background: var(--vf-surface); }
.publish-receipt {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid #b9d7c4;
  border-left: 4px solid #18a058;
  border-radius: 8px;
  background: #f7fcf8;
}
.publish-receipt-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.publish-receipt-heading h2 { margin: 2px 0 0; color: $ink-strong; font-size: 16px; }
.publish-receipt-heading > span { color: $text-secondary; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.publish-receipt-list { display: grid; gap: 8px; }
.publish-receipt-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 5px 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #d8eadc;
  border-radius: 6px;
  background: var(--vf-surface);
}
.publish-receipt-item > div { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.publish-receipt-item strong { color: $ink-strong; font-size: 13px; }
.publish-receipt-item span,
.publish-receipt-item p { color: $text-secondary; font-size: 12px; }
.publish-receipt-duration { white-space: nowrap; }
.publish-receipt-item p { grid-column: 1 / -1; margin: 0; line-height: 1.5; overflow-wrap: anywhere; }
.split-section { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.sub-panel { display: grid; gap: 12px; min-width: 0; }
.section-heading { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
.section-heading.compact { justify-content: flex-start; }
.section-heading h3 { margin: 0; color: $ink-strong; font-size: 16px; }
.section-heading p { margin: 3px 0 0; color: $text-secondary; font-size: 12px; }
.step-index { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; color: $accent-blue; background: rgba(37, 99, 235, 0.1); font-weight: 700; flex: 0 0 auto; }
.selection-note { color: $text-secondary; font-size: 12px; line-height: 1.6; }

.file-list,
.material-list,
.account-list { display: grid; gap: 8px; max-height: 360px; overflow: auto; }
.file-item,
.material-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid $border-lighter; border-radius: 8px; background: var(--vf-surface-hover); }
.selected-video-main { display: grid; gap: 5px; min-width: 0; margin-right: auto; }
.selected-video-main .el-link { justify-content: flex-start; max-width: 640px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-video-meta,
.material-details,
.material-badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: $text-secondary; font-size: 12px; }

.material-publish-draft,
.material-topic-list {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  color: #435168;
  font-size: 12px;
}

.material-publish-draft strong {
  min-width: 0;
  color: $ink-strong;
  font-size: 13px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-label {
  flex: 0 0 auto;
  color: $accent-blue;
  font-weight: 650;
}

.material-topic-list {
  flex-wrap: wrap;
}

.empty-topic {
  color: $text-secondary;
}

.tag-cloud { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 32px; }
.topic-cloud { margin-top: 4px; }
.platform-radios { display: flex; flex-wrap: wrap; gap: 8px; }
.target-carousel {
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: #f8fbff;
}
.target-carousel :deep(.el-carousel__container) {
  overflow: hidden;
}
.target-slide {
  display: grid;
  gap: 12px;
  align-content: start;
  height: 100%;
  padding: 14px 42px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.target-slide > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.target-slide strong { color: $ink-strong; font-size: 16px; }
.target-slide span { color: $text-secondary; font-size: 13px; }
.target-preview-grid {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 8px 10px;
  color: $text-secondary;
  font-size: 12px;
}
.target-preview-grid p {
  margin: 0;
  min-width: 0;
  color: $ink-strong;
  line-height: 1.55;
  overflow-wrap: anywhere;
  white-space: normal;
}
.platform-specific-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: var(--vf-surface);
}
.platform-specific-title {
  color: $text-secondary;
  font-size: 12px;
  font-weight: 650;
}
.platform-specific-panel .el-select {
  width: min(360px, 100%);
}
.target-status-panel {
  display: grid;
  gap: 8px;
}
.target-status-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface);
}
.target-status-item > div {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.target-status-item strong {
  color: $ink-strong;
  font-size: 13px;
}
.target-status-item span,
.target-status-item p {
  color: $text-secondary;
  font-size: 12px;
}
.target-status-item p {
  grid-column: 1 / -1;
  margin: 0;
  line-height: 1.5;
}
.publish-readonly-card {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface);
}
.publish-readonly-card > div {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 10px;
  align-items: flex-start;
}
.publish-readonly-card span {
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.7;
}
.publish-readonly-card strong,
.publish-readonly-card p {
  margin: 0;
  min-width: 0;
  color: $ink-strong;
  font-size: 13px;
  line-height: 1.7;
}
.agent-guard-card {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: var(--vf-surface);
}
.agent-guard-card.is-allow { border-color: #b7eb8f; background: #f6ffed; }
.agent-guard-card.is-warn { border-color: #ffe58f; background: #fffbe6; }
.agent-guard-card.is-block,
.agent-guard-card.is-failed { border-color: #ffccc7; background: #fff2f0; }
.agent-guard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  color: $text-regular;
  font-size: 13px;
}
.agent-guard-summary,
.agent-guard-time { display: flex; align-items: center; gap: 8px; }
.agent-guard-summary { flex-wrap: wrap; min-width: 0; }
.agent-guard-time { color: $text-secondary; font-size: 12px; white-space: nowrap; }
.agent-guard-issues { display: grid; gap: 8px; }
.agent-guard-issue {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.72);
}
.agent-guard-issue strong {
  color: $text-primary;
  font-size: 13px;
}
.agent-guard-issue p,
.agent-guard-issue small {
  margin: 0;
  color: $text-secondary;
  line-height: 1.5;
}
.two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.inline-options { display: flex; gap: 16px; flex-wrap: wrap; }
.schedule-controls { display: grid; gap: 12px; }
.schedule-settings { display: grid; gap: 12px; padding: 12px; border-radius: 8px; background: var(--vf-surface-hover); }
.schedule-item { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: center; }
.schedule-item > span { color: $text-secondary; font-size: 13px; }
.time-list { display: flex; gap: 8px; flex-wrap: wrap; }
.submit-bar { display: flex; justify-content: flex-end; gap: 10px; padding-top: 2px; }
.option-grid { display: grid; gap: 12px; }
.option-btn { width: 100%; height: 46px; }
.account-platform-list { display: grid; gap: 12px; max-height: 62vh; overflow: auto; padding-right: 4px; }
.account-platform-card { display: grid; gap: 10px; padding: 12px; border: 1px solid $border-lighter; border-radius: 8px; background: var(--vf-surface-hover); }
.account-platform-card.disabled { opacity: 0.62; background: #fafafa; }
.account-platform-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.account-platform-heading > div { display: grid; gap: 3px; }
.account-platform-heading strong { color: $ink-strong; font-size: 14px; }
.account-platform-heading span { color: $text-secondary; font-size: 12px; }
.platform-account-radios { display: grid; gap: 8px; }
.account-item { padding: 8px 10px; border: 1px solid $border-lighter; border-radius: 8px; background: var(--vf-surface); }
.custom-topic-input { display: flex; gap: 10px; margin-bottom: 18px; }
.topic-grid { display: flex; flex-wrap: wrap; gap: 10px; }
:global(.material-library-dialog) {
  width: min(960px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
}
:global(.material-library-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.material-library-dialog :deep(.el-alert) { margin-bottom: 12px; }
.material-library-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.publish-group-filter {
  width: 200px;
  flex: 0 0 200px;
}
.material-library-tools .el-input {
  max-width: 420px;
}
.material-library-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.publishable-list {
  max-height: min(62vh, 620px);
  padding-right: 4px;
}
.material-radio-group { width: 100%; }
.publishable-item { align-items: flex-start; min-height: 92px; }
.publishable-item :deep(.el-radio) { width: 100%; align-items: flex-start; height: auto; margin-right: 0; }
.publishable-item :deep(.el-radio__input) { margin-top: 3px; }
.publishable-item :deep(.el-radio__label) {
  min-width: 0;
  flex: 1;
  line-height: 1.45;
  white-space: normal;
}
.material-info { display: grid; gap: 7px; min-width: 0; width: 100%; }
.material-name {
  color: $ink-strong;
  font-weight: 650;
  line-height: 1.45;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.publish-progress { display: grid; gap: 14px; padding: 12px; }
.result-item { display: flex; gap: 10px; padding: 8px 0; color: $text-secondary; }
.result-item.success { color: $success-color; }
.result-item.error { color: $danger-color; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 10px; }
.video-upload { width: 100%; }
.video-upload :deep(.el-upload-dragger) { width: 100%; }

@media (max-width: 1100px) {
  .publish-workbench { grid-template-columns: 1fr; }
  .published-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .batch-panel { position: static; }
  .split-section { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .material-library-tools {
    align-items: stretch;
    flex-direction: column;
  }
  .publish-group-filter,
  .material-library-tools .el-input {
    width: 100%;
    max-width: none;
    flex-basis: auto;
  }
  .page-hero { align-items: flex-start; flex-direction: column; }
  .panel-heading-row { align-items: flex-start; flex-direction: column; }
  .published-summary,
  .published-card { grid-template-columns: 1fr; }
  .published-record-row,
  .archived-record-row { grid-template-columns: 1fr; gap: 6px; }
  .section-heading { align-items: flex-start; flex-direction: column; }
  .two-col,
  .schedule-item { grid-template-columns: 1fr; }
}
</style>
