<template>
  <div class="about">
    <section class="page-hero">
      <div>
        <span class="eyebrow">ABOUT VIDFERRY</span>
        <h1>Vidferry 自媒体自动化运营系统</h1>
        <p>围绕 YouTube 线索采集、视频处理、素材管理和国内平台发布构建的一体化工作台。</p>
      </div>
      <div class="version-card">
        <span>当前版本</span>
        <strong>v{{ APP_VERSION }}</strong>
      </div>
    </section>

    <section class="info-grid">
      <el-card class="info-panel" shadow="never">
        <template #header>
          <div class="panel-header">
            <span class="panel-kicker">CAPABILITY</span>
            <h2>核心能力</h2>
          </div>
        </template>
        <div class="feature-list">
          <div v-for="feature in features" :key="feature.title" class="feature-item">
            <span class="feature-dot"></span>
            <div>
              <strong>{{ feature.title }}</strong>
              <p>{{ feature.desc }}</p>
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="info-panel" shadow="never">
        <template #header>
          <div class="panel-header">
            <span class="panel-kicker">CHANNELS</span>
            <h2>支持平台</h2>
          </div>
        </template>
        <div class="platform-grid">
          <el-tag type="danger">抖音</el-tag>
          <el-tag type="success">快手</el-tag>
          <el-tag type="warning">视频号</el-tag>
          <el-tag type="info">小红书</el-tag>
        </div>
      </el-card>

      <el-card class="info-panel tech-panel" shadow="never">
        <template #header>
          <div class="panel-header">
            <span class="panel-kicker">STACK</span>
            <h2>技术栈</h2>
          </div>
        </template>
        <div class="tech-tags">
          <el-tag v-for="tech in techStack" :key="tech" effect="plain">{{ tech }}</el-tag>
        </div>
      </el-card>

      <el-card class="info-panel thanks-panel" shadow="never">
        <template #header>
          <div class="panel-header">
            <span class="panel-kicker">ACKNOWLEDGEMENTS</span>
            <h2>开源项目致谢</h2>
          </div>
        </template>
        <p class="thanks-copy">
          感谢 {{ acknowledgementNames }}，我们使用了他们的项目帮助 Vidferry 的实现。
        </p>
        <div class="ack-grid">
          <div v-for="item in acknowledgements" :key="item.name" class="ack-item">
            <strong>{{ item.name }}</strong>
            <span>{{ item.license }} / {{ item.version }}</span>
          </div>
        </div>
      </el-card>
    </section>
  </div>
</template>

<script setup>
import { APP_VERSION } from '@/version'

const features = [
  { title: '视频线索采集', desc: '支持 YouTube 查询、单条导入、下载和工作流状态跟踪。' },
  { title: '字幕翻译与烧录', desc: '基于本地转写和 FFmpeg 处理，输出国内平台兼容 MP4。' },
  { title: '素材统一管理', desc: '下载原视频和处理后视频统一进入素材模型。' },
  { title: '多平台发布', desc: '维护账号 Cookie，支持批量发布、定时发布和草稿策略。' },
  { title: '处理统计', desc: '记录阶段耗时、视频大小，并预留云端模型 token 与延迟统计。' }
]

const techStack = ['Vue 3', 'Element Plus', 'Pinia', 'Flask', 'SQLite', 'yt-dlp', 'FFmpeg', 'faster-whisper', 'CTranslate2']

const acknowledgements = [
  { name: 'yt-dlp', license: 'Unlicense', version: '2026.3.17' },
  { name: 'social-auto-upload', license: '开源项目', version: APP_VERSION },
  { name: 'FFmpeg', license: 'LGPL/GPL', version: '7.1 essentials build' },
  { name: 'faster-whisper / CTranslate2', license: 'MIT', version: '1.2.1 / 4.7.2' },
  { name: 'deep-translator', license: 'MIT', version: '1.11.4' }
]

const acknowledgementNames = acknowledgements.map(item => item.name).join('、')
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

$panel-border: #dce6f2;
$panel-shadow: 0 12px 28px rgba(28, 55, 90, 0.08);
$accent-blue: #2563eb;
$ink-strong: #172033;

.about {
  display: grid;
  gap: 16px;

  :deep(.el-card) {
    border: 1px solid $panel-border;
    border-radius: 8px;
    box-shadow: $panel-shadow;
  }

  :deep(.el-card__header) {
    padding: 14px 16px;
  }
}

.page-hero {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid $panel-border;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(15, 159, 143, 0.08) 42%, rgba(255, 255, 255, 0.94)),
    #fff;
  box-shadow: $panel-shadow;

  h1 {
    margin: 4px 0 8px;
    color: $ink-strong;
    font-size: 25px;
    line-height: 1.25;
    font-weight: 700;
  }

  p {
    max-width: 760px;
    margin: 0;
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

.version-card {
  display: grid;
  align-content: center;
  gap: 6px;
  min-width: 220px;
  padding: 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.82);

  span {
    color: $text-secondary;
    font-size: 13px;
  }

  strong {
    color: $ink-strong;
    font-size: 18px;
  }
}

.info-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: 16px;
}

.tech-panel,
.thanks-panel {
  grid-column: 1 / -1;
}

.panel-header {
  h2 {
    margin: 2px 0 0;
    color: $ink-strong;
    font-size: 18px;
    line-height: 1.3;
  }
}

.feature-list {
  display: grid;
  gap: 12px;
}

.feature-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  strong {
    color: $ink-strong;
    font-size: 14px;
  }

  p {
    margin: 4px 0 0;
    color: $text-secondary;
    font-size: 13px;
    line-height: 1.6;
  }
}

.feature-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.1);
  flex: 0 0 auto;
}

.platform-grid,
.tech-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.thanks-copy {
  margin: 0;
  color: $text-secondary;
  font-size: 13px;
  line-height: 1.7;
}

.ack-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0;
}

.ack-item {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid $border-lighter;
  border-radius: 8px;
  background: #f8fbff;

  strong,
  span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: $ink-strong;
    font-size: 13px;
  }

  span {
    color: $text-secondary;
    font-size: 12px;
  }
}

@media (max-width: 860px) {
  .page-hero {
    flex-direction: column;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .ack-grid {
    grid-template-columns: 1fr;
  }
}
</style>
