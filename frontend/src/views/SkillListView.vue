<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NIcon, useDialog, useMessage } from 'naive-ui'
import { Hierarchy, Search, Upload } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'

const resourceStore = useResourceStore()
const message = useMessage()
const dialog = useDialog()
const query = ref('')
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedId = ref<string | null>(null)
const selected = computed(() => resourceStore.skills.find((item) => item.id === selectedId.value) || null)
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.skills.filter((item) => [item.id, item.name, item.description || '', item.path, item.version].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.skills
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

onMounted(() => resourceStore.fetchAll().catch(() => undefined))
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
      <article v-for="skill in filtered" v-else :key="skill.id" class="resource-row resource-row-clickable" @click="selectedId = skill.id">
        <span class="resource-icon"><NIcon :component="Hierarchy" size="19" /></span>
        <div class="resource-main"><strong>{{ skill.name }}</strong><span class="mono">{{ skill.id }}</span></div>
        <div class="resource-description">{{ skill.description || '未填写描述' }}</div>
        <div class="resource-meta"><NTag size="small" :bordered="false">v{{ skill.version }}</NTag><br />{{ formatDate(skill.updated_at) }}</div>
      </article>
    </section>

    <NModal :show="selected !== null" preset="card" style="width: min(680px, 92vw)" title="Skill 详情" @update:show="selectedId = $event ? selectedId : null">
      <template v-if="selected">
        <dl class="definition-list">
          <div class="definition-item"><dt>ID</dt><dd class="mono">{{ selected.id }}</dd></div>
          <div class="definition-item"><dt>版本</dt><dd>{{ selected.version }}</dd></div>
          <div class="definition-item"><dt>运行目录</dt><dd class="mono">{{ selected.path }}</dd></div>
          <div class="definition-item"><dt>包 SHA-256</dt><dd class="mono">{{ selected.package_sha256 || '目录注册项' }}</dd></div>
        </dl>
        <pre class="prompt-block" style="margin-top: 18px">{{ JSON.stringify(selected.manifest, null, 2) }}</pre>
        <div style="display: flex; justify-content: flex-end; margin-top: 18px"><NButton type="error" secondary :disabled="!selected.package_sha256" @click="remove">删除上传包</NButton></div>
      </template>
    </NModal>
  </div>
</template>
