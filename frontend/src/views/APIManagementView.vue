<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { Api, Key } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import type { Agent, AgentPublication, PublicationStatus } from '@/types/api'

const message = useMessage()
const agents = ref<Agent[]>([])
const publications = ref<AgentPublication[]>([])
const loading = ref(false)
const secret = ref<string | null>(null)

async function load() {
  loading.value = true
  try { [agents.value, publications.value] = await Promise.all([platformApi.listAgents(), platformApi.listPublications()]) }
  catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { loading.value = false }
}

function publicationFor(agentId: string) { return publications.value.find((item) => item.agent_id === agentId) }

async function setStatus(agentId: string, status: PublicationStatus) {
  try { await platformApi.updatePublication(agentId, status); await load(); message.success('API 状态已更新') }
  catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

async function rotate(agentId: string) {
  try { const value = await platformApi.rotatePublicationKey(agentId); secret.value = value.api_key; await load() }
  catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="API 管理" description="管理 Agent 的独立发布生命周期、API Key 和外部调用统计。API Key 明文仅在生成或轮换时显示一次。" />
    <NAlert v-if="secret" type="warning" :bordered="false" style="margin-bottom: 16px" closable @close="secret = null">
      请立即保存 API Key，关闭后无法再次查看：<span class="mono secret-value">{{ secret }}</span>
    </NAlert>
    <section class="surface resource-list">
      <div v-if="loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="agents.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="Api" size="24" /></div><h3>暂无 Agent</h3><p>先创建 Agent，再配置发布 API。</p></div></div>
      <article v-for="agent in agents" v-else :key="agent.id" class="api-row">
        <span class="resource-icon"><NIcon :component="Api" size="19" /></span>
        <div class="resource-main"><strong>{{ agent.name }}</strong><span class="mono">{{ agent.id }}</span><span class="mono endpoint-line">/api/public/agents/{{ agent.id }}/run</span></div>
        <div class="api-metrics"><span>状态 <NTag size="small" :bordered="false">{{ publicationFor(agent.id)?.status || '未配置' }}</NTag></span><span>Key {{ publicationFor(agent.id)?.api_key_prefix ? `${publicationFor(agent.id)?.api_key_prefix}…` : '未生成' }}</span><span>调用 {{ publicationFor(agent.id)?.call_count || 0 }}</span><span>最近 {{ formatDate(publicationFor(agent.id)?.last_called_at) }}</span></div>
        <div class="api-actions"><NButton size="small" secondary @click="rotate(agent.id)"><template #icon><NIcon :component="Key" /></template>{{ publicationFor(agent.id)?.api_key_prefix ? '轮换 Key' : '生成 Key' }}</NButton><NSelect :value="publicationFor(agent.id)?.status || 'draft'" size="small" style="width: 122px" :options="[{label:'Draft',value:'draft'},{label:'Testing',value:'testing'},{label:'Published',value:'published'},{label:'Disabled',value:'disabled'}]" @update:value="setStatus(agent.id, $event as PublicationStatus)" /></div>
      </article>
    </section>
  </div>
</template>
