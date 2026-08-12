<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Database, Files, PlugConnected, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'

const resourceStore = useResourceStore()
const query = ref('')
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.mcpServers.filter((item) => [item.id, item.name, item.endpoint, item.config.kind].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.mcpServers
})

onMounted(() => resourceStore.fetchAll().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="MCP 管理" description="展示平台注册的 MCP Gateway 能力。第一阶段仅接受只读 filesystem 和 database。" />
    <NAlert type="info" :bordered="false" style="margin-bottom: 16px">所有注册项必须指向后端配置的 `MCP_GATEWAY_ENDPOINT`，Agent 不能绕过平台调用其他端点。</NAlert>
    <div v-if="resourceStore.error" class="error-panel" style="margin-bottom: 16px">{{ resourceStore.error }}</div>
    <div class="toolbar">
      <NInput v-model:value="query" class="search" clearable placeholder="搜索 MCP"><template #prefix><NIcon :component="Search" /></template></NInput>
      <div class="toolbar-spacer" /><span class="muted" style="font-size: 11px">{{ filtered.length }} 项</span>
    </div>
    <section class="surface resource-list">
      <div v-if="resourceStore.loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="PlugConnected" size="24" /></div><h3>暂无 MCP</h3><p>请先通过后端注册受控、只读的 MCP Gateway 能力。</p></div></div>
      <article v-for="server in filtered" v-else :key="server.id" class="resource-row">
        <span class="resource-icon"><NIcon :component="server.config.kind === 'database' ? Database : Files" size="19" /></span>
        <div class="resource-main"><strong>{{ server.name }}</strong><span class="mono">{{ server.id }}</span></div>
        <div class="resource-description truncate"><span class="mono">{{ server.endpoint }}</span></div>
        <div class="resource-meta"><NTag size="small" type="success" :bordered="false">{{ server.config.kind }} / read-only</NTag><br />{{ formatDate(server.created_at) }}</div>
      </article>
    </section>
  </div>
</template>
