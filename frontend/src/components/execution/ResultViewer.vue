<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Download } from '@vicons/tabler'

import ExecutionTimeline from './ExecutionTimeline.vue'
import { platformApi } from '@/api/platform'
import { formatJson, parseSafeMarkdown } from '@/utils/executionStudio'
import type { Artifact, ExecutionStep } from '@/types/api'

const props = defineProps<{
  output?: string | null
  outputJson?: unknown
  artifacts: Artifact[]
  steps: ExecutionStep[]
  details?: Record<string, unknown>
  active?: boolean
  initialTab?: 'markdown' | 'json' | 'raw' | 'artifacts' | 'trace'
}>()

const tab = ref<'markdown' | 'json' | 'raw' | 'artifacts' | 'trace'>(props.initialTab || 'markdown')
const markdown = computed(() => parseSafeMarkdown(props.output || ''))
</script>

<template>
  <div class="result-viewer">
    <div class="result-tabs" role="tablist" aria-label="执行结果视图">
      <button :class="{ active: tab === 'markdown' }" role="tab" @click="tab = 'markdown'">Markdown</button>
      <button :class="{ active: tab === 'json' }" role="tab" @click="tab = 'json'">JSON</button>
      <button :class="{ active: tab === 'raw' }" role="tab" @click="tab = 'raw'">Raw</button>
      <button :class="{ active: tab === 'artifacts' }" role="tab" @click="tab = 'artifacts'">Artifact {{ artifacts.length }}</button>
      <button :class="{ active: tab === 'trace' }" role="tab" @click="tab = 'trace'">Trace {{ steps.length }}</button>
    </div>

    <div v-if="tab === 'markdown'" class="result-panel">
      <div v-if="output" class="safe-markdown">
        <template v-for="(block, index) in markdown" :key="index">
          <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
          <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
          <div v-else-if="block.kind === 'list'" class="markdown-list-item">{{ block.text }}</div>
          <pre v-else>{{ block.text }}</pre>
        </template>
      </div>
      <div v-else class="empty-state empty-state-compact"><div><h3>{{ active ? '正在等待输出' : '没有文本输出' }}</h3><p>可切换到 JSON、Artifact 或 Trace 查看结构化结果。</p></div></div>
    </div>
    <div v-else-if="tab === 'json'" class="result-panel">
      <pre class="json-viewer">{{ formatJson(outputJson ?? { output, details }) }}</pre>
    </div>
    <div v-else-if="tab === 'raw'" class="result-panel"><pre class="json-viewer result-raw">{{ output || '' }}</pre></div>
    <div v-else-if="tab === 'artifacts'" class="result-panel">
      <div v-if="artifacts.length" class="artifact-list">
        <a v-for="artifact in artifacts" :key="artifact.id" class="artifact-row" :href="platformApi.artifactDownloadUrl(artifact.id)">
          <NIcon :component="Download" size="18" />
          <div><strong>{{ artifact.filename }}</strong><span class="mono">{{ artifact.storage_path }}</span><span>{{ artifact.size_bytes }} bytes · SHA-256 {{ artifact.sha256 }}</span></div>
        </a>
      </div>
      <div v-else class="empty-state empty-state-compact"><div><h3>没有 Artifact</h3><p>本次执行没有关联可下载产物。</p></div></div>
    </div>
    <div v-else class="result-panel"><ExecutionTimeline :steps="steps" :active="active" /></div>
  </div>
</template>
