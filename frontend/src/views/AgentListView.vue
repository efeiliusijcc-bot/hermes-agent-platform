<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { NIcon } from 'naive-ui'
import { Plus, Robot, Search, TestPipe } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { useAgentStore } from '@/stores/agents'
import { formatDate } from '@/utils/format'

const router = useRouter()
const dialog = useDialog()
const message = useMessage()
const agentStore = useAgentStore()
const query = ref('')

const filteredAgents = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return agentStore.agents
  return agentStore.agents.filter((agent) =>
    [agent.id, agent.name, agent.role, agent.description || ''].some((value) => value.toLowerCase().includes(keyword)),
  )
})

function confirmDelete(agentId: string, agentName: string) {
  dialog.warning({
    title: '删除 Agent',
    content: `确认删除“${agentName}”？后端会同时清理该 Agent 的执行记录和会话记忆。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await agentStore.removeAgent(agentId)
        message.success('Agent 已删除')
      } catch (error) {
        message.error(getApiErrorMessage(error))
      }
    },
  })
}

onMounted(() => agentStore.fetchAgents().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="Agent 管理" description="Agent 是平台中的长期数字工作单元。配置角色后，通过独立接口绑定受控能力。">
      <template #actions>
        <NButton type="primary" @click="router.push({ name: 'agent-create' })">
          <template #icon><NIcon :component="Plus" /></template>创建 Agent
        </NButton>
      </template>
    </PageHeader>

    <div v-if="agentStore.error" class="error-panel" style="margin-bottom: 16px">{{ agentStore.error }}</div>
    <div class="toolbar">
      <NInput v-model:value="query" class="search" clearable placeholder="搜索名称、ID 或角色">
        <template #prefix><NIcon :component="Search" /></template>
      </NInput>
      <div class="toolbar-spacer" />
      <span class="muted" style="font-size: 11px">{{ filteredAgents.length }} 个 Agent</span>
    </div>

    <div v-if="agentStore.loading" class="agent-grid">
      <div v-for="index in 4" :key="index" class="surface" style="padding: 20px"><div class="skeleton-line" style="height: 165px" /></div>
    </div>
    <div v-else-if="filteredAgents.length === 0" class="surface empty-state">
      <div>
        <div class="empty-state-icon"><NIcon :component="Robot" size="24" /></div>
        <h3>{{ query ? '没有匹配的 Agent' : '尚未创建 Agent' }}</h3>
        <p>{{ query ? '修改搜索条件后重试。' : '创建第一个 Agent，绑定 Skill 与 MCP，然后进入执行台验证完整闭环。' }}</p>
        <NButton v-if="!query" type="primary" @click="router.push({ name: 'agent-create' })">创建 Agent</NButton>
      </div>
    </div>
    <section v-else class="agent-grid">
      <article v-for="agent in filteredAgents" :key="agent.id" class="agent-card surface">
        <div class="agent-card-top">
          <div>
            <h2>{{ agent.name }}</h2>
            <div class="agent-card-id mono">{{ agent.id }}</div>
          </div>
          <StatusTag :status="agent.status" />
        </div>
        <p class="agent-card-description">{{ agent.description || agent.role }}</p>
        <div class="agent-card-meta">
          <span>角色：{{ agent.role }}</span>
          <span>创建：{{ formatDate(agent.created_at) }}</span>
          <div class="agent-card-actions">
            <NButton text size="small" @click="router.push({ name: 'agent-detail', params: { id: agent.id } })">详情</NButton>
            <NButton text size="small" type="primary" :disabled="agent.status !== 'active'" @click="router.push({ name: 'agent-playground', params: { id: agent.id } })">
              <template #icon><NIcon :component="TestPipe" /></template>测试
            </NButton>
            <NButton text size="small" type="error" @click="confirmDelete(agent.id, agent.name)">删除</NButton>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
