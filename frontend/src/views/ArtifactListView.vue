<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Archive, Download, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { Agent, Artifact } from '@/types/api'
import { formatDate } from '@/utils/format'

const artifacts = ref<Artifact[]>([])
const agents = ref<Agent[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const query = ref('')
const selectedAgent = ref<string | null>(null)

const agentNames = computed(() => new Map(agents.value.map((agent) => [agent.id, agent.name])))
const agentOptions = computed(() => agents.value.map((agent) => ({ label: agent.name, value: agent.id })))
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return artifacts.value.filter((artifact) => {
    if (selectedAgent.value && artifact.agent_id !== selectedAgent.value) return false
    if (!keyword) return true
    return [artifact.filename, artifact.agent_id, artifact.session_id, artifact.content_type, artifact.sha256]
      .some((value) => value.toLowerCase().includes(keyword))
  })
})
const totalBytes = computed(() => filtered.value.reduce((sum, artifact) => sum + artifact.size_bytes, 0))

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [artifactList, agentList] = await Promise.all([
      platformApi.listArtifacts(),
      platformApi.listAgents(),
    ])
    artifacts.value = artifactList
    agents.value = agentList
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="Artifact 产物" description="统一查看所有 Agent 会话生成的文件，并从受控存储接口下载。">
      <template #actions><NButton secondary :loading="loading" @click="load">刷新</NButton></template>
    </PageHeader>

    <div v-if="error" class="error-panel" style="margin-bottom: 16px">{{ error }}</div>
    <section class="execution-summary-strip" aria-label="产物统计">
      <div><span>产物数量</span><strong>{{ loading ? '--' : filtered.length }}</strong></div>
      <div><span>占用空间</span><strong>{{ loading ? '--' : formatBytes(totalBytes) }}</strong></div>
      <div><span>关联 Agent</span><strong>{{ new Set(filtered.map((item) => item.agent_id)).size }}</strong></div>
    </section>

    <div class="toolbar">
      <NInput v-model:value="query" class="search" clearable placeholder="搜索文件名、Session 或 SHA-256">
        <template #prefix><NIcon :component="Search" /></template>
      </NInput>
      <NSelect v-model:value="selectedAgent" clearable class="filter-select" placeholder="全部 Agent" :options="agentOptions" />
      <div class="toolbar-spacer" />
      <span class="muted" style="font-size: 11px">只展示后端已登记产物</span>
    </div>

    <section class="surface artifact-registry">
      <div class="artifact-table-head">
        <span>文件</span><span>Agent / Session</span><span>类型</span><span>大小</span><span>创建时间</span><span />
      </div>
      <div v-if="loading" class="loading-stack" style="padding: 16px"><div v-for="index in 5" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state">
        <div><div class="empty-state-icon"><NIcon :component="Archive" size="24" /></div><h3>没有可展示的 Artifact</h3><p>执行产生文件后，后端会在这里登记文件名、校验值和下载地址。</p></div>
      </div>
      <article v-for="artifact in filtered" v-else :key="artifact.id" class="artifact-registry-row">
        <div class="artifact-file"><NIcon :component="Archive" size="18" /><div><strong>{{ artifact.filename }}</strong><span class="mono">{{ artifact.sha256 }}</span></div></div>
        <div><strong>{{ agentNames.get(artifact.agent_id) || artifact.agent_id }}</strong><span class="mono">{{ artifact.session_id }}</span></div>
        <span class="mono">{{ artifact.content_type }}</span>
        <span class="mono">{{ formatBytes(artifact.size_bytes) }}</span>
        <span>{{ formatDate(artifact.created_at) }}</span>
        <a class="artifact-download" :href="platformApi.artifactDownloadUrl(artifact.id)" :aria-label="`下载 ${artifact.filename}`"><NIcon :component="Download" size="18" /></a>
      </article>
    </section>
  </div>
</template>
