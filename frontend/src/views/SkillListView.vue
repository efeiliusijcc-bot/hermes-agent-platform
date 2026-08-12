<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Hierarchy, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'

const resourceStore = useResourceStore()
const query = ref('')
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.skills.filter((item) => [item.id, item.name, item.description || '', item.path].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.skills
})

onMounted(() => resourceStore.fetchAll().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="Skill 管理" description="展示已通过后端目录边界、SKILL.md 和 config.yaml 校验的能力定义。" />
    <div v-if="resourceStore.error" class="error-panel" style="margin-bottom: 16px">{{ resourceStore.error }}</div>
    <div class="toolbar">
      <NInput v-model:value="query" class="search" clearable placeholder="搜索 Skill"><template #prefix><NIcon :component="Search" /></template></NInput>
      <div class="toolbar-spacer" /><span class="muted" style="font-size: 11px">{{ filtered.length }} 项</span>
    </div>
    <section class="surface resource-list">
      <div v-if="resourceStore.loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="Hierarchy" size="24" /></div><h3>暂无 Skill</h3><p>Skill 注册需要磁盘中已经存在且校验通过的定义，当前 MVP 不伪造在线编辑能力。</p></div></div>
      <article v-for="skill in filtered" v-else :key="skill.id" class="resource-row">
        <span class="resource-icon"><NIcon :component="Hierarchy" size="19" /></span>
        <div class="resource-main"><strong>{{ skill.name }}</strong><span class="mono">{{ skill.id }}</span></div>
        <div class="resource-description">{{ skill.description || '未填写描述' }}</div>
        <div class="resource-meta"><span class="mono">{{ skill.path }}</span><br />{{ formatDate(skill.created_at) }}</div>
      </article>
    </section>
  </div>
</template>
