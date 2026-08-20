<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NIcon, NModal, useDialog, useMessage } from 'naive-ui'
import { Hierarchy, Search, Upload } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'
import type { ConsoleAgentSummary } from '@/types/api'

const resourceStore = useResourceStore()
const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const query = ref('')
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedId = ref<string | null>(null)
const detailTab = ref<'skill' | 'schema' | 'dependencies' | 'usage' | 'history'>('skill')
const consoleAgents = ref<ConsoleAgentSummary[]>([])
const usedAgents = ref<ConsoleAgentSummary[]>([])
const usageCounts = ref<Record<string, number | null>>({})
const usageLoading = ref(false)
const selected = computed(() => resourceStore.skills.find((item) => item.id === selectedId.value) || null)
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.skills.filter((item) => [item.id, item.name, item.description || '', item.path, item.version].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.skills
})
const manifestTools = computed(() => {
  const value = selected.value?.manifest.tools
  return Array.isArray(value) ? value.map(String) : []
})
const dependencies = computed(() => {
  const value = selected.value?.manifest.dependencies
  return Array.isArray(value) ? value.map(String) : []
})

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    const skill = await platformApi.uploadSkill(file)
    await resourceStore.fetchSkills()
    selectedId.value = skill.id
    message.success(`Skill ${skill.id} 已注册`)
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function remove() {
  if (!selected.value) return
  const skill = selected.value
  dialog.warning({
    title: '删除 Skill',
    content: `确认删除 ${skill.name}（${skill.id}）？已绑定时后端会拒绝删除。`,
    positiveText: '删除',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await platformApi.deleteSkill(skill.id)
        selectedId.value = null
        await resourceStore.fetchSkills()
        message.success('Skill 已删除')
      } catch (error) {
        message.error(getApiErrorMessage(error), { duration: 7000 })
      }
    },
  })
}

async function openSkill(skillId: string) {
  selectedId.value = skillId
  detailTab.value = 'skill'
  await router.replace({ name: 'skill-detail', params: { id: skillId } })
  usageLoading.value = true
  try {
    usedAgents.value = consoleAgents.value.filter((agent) => agent.skills.some((item) => item.id === skillId))
  } finally { usageLoading.value = false }
}

function loadUsageCounts() {
  const counts: Record<string, number> = Object.fromEntries(resourceStore.skills.map((item) => [item.id, 0]))
  consoleAgents.value.forEach((agent) => {
    agent.skills.forEach((skill) => { counts[skill.id] = (counts[skill.id] || 0) + 1 })
  })
  usageCounts.value = counts
}

function closeDetail(show: boolean) {
  if (show) return
  selectedId.value = null
  usedAgents.value = []
  router.replace({ name: 'skills' })
}

onMounted(async () => {
  const [, agentValues] = await Promise.all([
    resourceStore.fetchAll().catch(() => undefined),
    platformApi.listConsoleAgents().catch(() => []),
  ])
  consoleAgents.value = agentValues
  loadUsageCounts()
  if (route.params.id) await openSkill(String(route.params.id))
})
watch(() => route.params.id, (id) => {
  if (id && String(id) !== selectedId.value) openSkill(String(id))
})
</script>

<template>
  <div>
    <PageHeader title="Skill 管理" description="上传受控 ZIP 包，后端校验 skill.yaml、SKILL.md、安全路径和解压边界后才注册。">
      <template #actions><NButton type="primary" :loading="uploading" @click="fileInput?.click()"><template #icon><NIcon :component="Upload" /></template>上传 Skill</NButton></template>
    </PageHeader>
    <input ref="fileInput" type="file" accept=".zip,application/zip" hidden @change="upload" />
    <div v-if="resourceStore.error" class="error-panel" style="margin-bottom: 16px">{{ resourceStore.error }}</div>
    <div class="toolbar">
      <NInput v-model:value="query" class="search" clearable placeholder="搜索 Skill"><template #prefix><NIcon :component="Search" /></template></NInput>
      <div class="toolbar-spacer" /><span class="muted" style="font-size: 11px">{{ filtered.length }} 项</span>
    </div>
    <section class="surface resource-list">
      <div v-if="resourceStore.loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="Hierarchy" size="24" /></div><h3>暂无 Skill</h3><p>上传包含 skill.yaml 与 SKILL.md 的 ZIP 包。</p></div></div>
      <article v-for="skill in filtered" v-else :key="skill.id" class="resource-row resource-row-clickable" @click="openSkill(skill.id)">
        <span class="resource-icon"><NIcon :component="Hierarchy" size="19" /></span>
        <div class="resource-main"><strong>{{ skill.name }}</strong><span class="mono">{{ skill.id }}</span></div>
        <div class="resource-description">{{ skill.description || '未填写描述' }}<br /><span class="muted">Tools {{ Array.isArray(skill.manifest.tools) ? skill.manifest.tools.length : 0 }} · Used Agents {{ usageCounts[skill.id] ?? '--' }}</span></div>
        <div class="resource-meta"><NTag size="small" type="success" :bordered="false">已注册</NTag><br />v{{ skill.version }} · {{ formatDate(skill.updated_at) }}</div>
      </article>
    </section>

    <NModal :show="selected !== null" preset="card" style="width: min(860px, 94vw)" title="Skill 详情" @update:show="closeDetail">
      <template v-if="selected">
        <nav class="detail-tabs modal-tabs">
          <button v-for="tab in [{key:'skill',label:'SKILL.md'},{key:'schema',label:'Schema'},{key:'dependencies',label:'Dependencies'},{key:'usage',label:'Usage'},{key:'history',label:'History'}]" :key="tab.key" type="button" :class="{ active: detailTab === tab.key }" @click="detailTab = tab.key as typeof detailTab">{{ tab.label }}</button>
        </nav>
        <template v-if="detailTab === 'skill'">
          <NAlert type="info" :bordered="false" style="margin-bottom: 14px">现有 Skill API 返回注册元数据与 manifest，不返回 SKILL.md 正文。为避免伪造，正文明确标记为不可用。</NAlert>
          <dl class="definition-list"><div class="definition-item"><dt>ID</dt><dd class="mono">{{ selected.id }}</dd></div><div class="definition-item"><dt>版本</dt><dd>{{ selected.version }}</dd></div><div class="definition-item"><dt>运行目录</dt><dd class="mono">{{ selected.path }}</dd></div><div class="definition-item"><dt>包 SHA-256</dt><dd class="mono">{{ selected.package_sha256 || '目录注册项' }}</dd></div></dl>
          <div class="unavailable-panel"><strong>SKILL.md 正文不可用</strong><span>需要后端新增受控读取接口后才能展示。</span></div>
        </template>
        <pre v-else-if="detailTab === 'schema'" class="prompt-block">{{ JSON.stringify(selected.manifest, null, 2) }}</pre>
        <div v-else-if="detailTab === 'dependencies'" class="selection-list"><div v-if="dependencies.length === 0"><strong>无已声明依赖</strong><span>manifest.dependencies 未提供</span></div><div v-for="item in dependencies" :key="item"><strong class="mono">{{ item }}</strong></div></div>
        <div v-else-if="detailTab === 'usage'">
          <div v-if="usageLoading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
          <div v-else-if="usedAgents.length" class="selection-list"><div v-for="agent in usedAgents" :key="agent.id"><strong>{{ agent.name }}</strong><span class="mono">{{ agent.id }}</span></div></div>
          <div v-else class="unavailable-panel"><strong>没有 Agent 使用此 Skill</strong><span>按当前 Agent 绑定接口逐项核对。</span></div>
        </div>
        <dl v-else class="execution-definition-list"><div><dt>创建时间</dt><dd>{{ formatDate(selected.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(selected.updated_at) }}</dd></div><div><dt>注册状态</dt><dd>已注册</dd></div><div><dt>Tools</dt><dd>{{ manifestTools.length ? manifestTools.join(', ') : 'manifest 未声明' }}</dd></div></dl>
        <div style="display: flex; justify-content: flex-end; margin-top: 18px"><NButton type="error" secondary :disabled="!selected.package_sha256" @click="remove">删除上传包</NButton></div>
      </template>
    </NModal>
  </div>
</template>
