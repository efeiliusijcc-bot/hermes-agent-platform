<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NForm, NFormItem, NIcon, NModal, useDialog, useMessage } from 'naive-ui'
import { Database, Files, Plus, PlugConnected, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'
import type { MCPServer } from '@/types/api'
import type { ConsoleAgentSummary, ExecutionSummary } from '@/types/api'
import { useRoute, useRouter } from 'vue-router'

const resourceStore = useResourceStore()
const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const query = ref('')
const showCreate = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const editingId = ref<string | null>(null)
const selectedId = ref<string | null>(null)
const detailTab = ref<'endpoint' | 'tools' | 'agents' | 'logs'>('endpoint')
const consoleAgents = ref<ConsoleAgentSummary[]>([])
const boundAgents = ref<ConsoleAgentSummary[]>([])
const relatedExecutions = ref<ExecutionSummary[]>([])
const detailLoading = ref(false)
const relatedExecutionsFor = ref<string | null>(null)
const executionRequests = new Map<string, Promise<ExecutionSummary[]>>()
const selected = computed(() => resourceStore.mcpServers.find((item) => item.id === selectedId.value) || null)
const form = reactive({ id: '', name: '', kind: 'filesystem' as 'filesystem' | 'database', endpoint: 'http://mcp-gateway:8090/mcp' })
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.mcpServers.filter((item) => [item.id, item.name, item.endpoint, item.config.kind, item.status].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.mcpServers
})

async function create() {
  saving.value = true
  try {
    const payload = { name: form.name, endpoint: form.endpoint, permission: 'read_only' as const, config: { kind: form.kind, read_only: true as const } }
    if (editingId.value) await platformApi.updateMCPServer(editingId.value, payload)
    else await platformApi.createMCPServer({ id: form.id, ...payload })
    await resourceStore.fetchMCPServers()
    showCreate.value = false
    message.success(editingId.value ? 'MCP 已更新，状态已重置' : 'MCP 已注册')
    editingId.value = null
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { saving.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { id: '', name: '', kind: 'filesystem', endpoint: 'http://mcp-gateway:8090/mcp' })
  showCreate.value = true
}

function edit(server: MCPServer) {
  editingId.value = server.id
  Object.assign(form, { id: server.id, name: server.name, kind: server.config.kind, endpoint: server.endpoint })
  showCreate.value = true
}

async function test(server: MCPServer) {
  testingId.value = server.id
  try {
    const result = await platformApi.testMCPServer(server.id)
    await resourceStore.fetchMCPServers()
    message[result.status === 'online' ? 'success' : 'error'](`${result.detail}，${result.latency_ms} ms`)
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { testingId.value = null }
}

function remove(server: MCPServer) {
  dialog.warning({ title: '删除 MCP', content: `确认删除 ${server.name}（${server.id}）？已绑定时后端会拒绝删除。`, positiveText: '删除', negativeText: '取消', async onPositiveClick() {
    try { await platformApi.deleteMCPServer(server.id); await resourceStore.fetchMCPServers(); message.success('MCP 已删除') }
    catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  } })
}

async function openDetail(server: MCPServer) {
  selectedId.value = server.id
  detailTab.value = 'endpoint'
  await router.replace({ name: 'mcp-detail', params: { id: server.id } })
  boundAgents.value = consoleAgents.value.filter((agent) => agent.mcps.some((item) => item.id === server.id))
  relatedExecutions.value = []
  relatedExecutionsFor.value = null
}

function agentExecutions(agentId: string): Promise<ExecutionSummary[]> {
  const existing = executionRequests.get(agentId)
  if (existing) return existing
  const request = platformApi.listExecutions({ agent_id: agentId, limit: 20 })
    .then((value) => value.items)
    .catch((cause) => {
      executionRequests.delete(agentId)
      throw cause
    })
  executionRequests.set(agentId, request)
  return request
}

async function loadRelatedExecutions() {
  const serverId = selectedId.value
  if (!serverId || relatedExecutionsFor.value === serverId) return
  detailLoading.value = true
  try {
    const executionResults = await Promise.allSettled(boundAgents.value.map((agent) => agentExecutions(agent.id)))
    if (selectedId.value !== serverId) return
    relatedExecutions.value = executionResults.flatMap((result) => result.status === 'fulfilled'
      ? result.value.filter((item) => item.mcp_call_count > 0) : [])
      .sort((left, right) => new Date(right.started_at).valueOf() - new Date(left.started_at).valueOf())
    relatedExecutionsFor.value = serverId
  } finally {
    if (selectedId.value === serverId) detailLoading.value = false
  }
}

function closeDetail(show: boolean) {
  if (show) return
  selectedId.value = null
  boundAgents.value = []
  relatedExecutions.value = []
  relatedExecutionsFor.value = null
  router.replace({ name: 'mcps' })
}

onMounted(async () => {
  const [, agentValues] = await Promise.all([
    resourceStore.fetchAll().catch(() => undefined),
    platformApi.listConsoleAgents().catch(() => []),
  ])
  consoleAgents.value = agentValues
  const id = String(route.params.id || '')
  const server = resourceStore.mcpServers.find((item) => item.id === id)
  if (server) await openDetail(server)
})
watch(() => route.params.id, (id) => {
  const server = resourceStore.mcpServers.find((item) => item.id === String(id || ''))
  if (server && server.id !== selectedId.value) openDetail(server)
})
watch(detailTab, (value) => {
  if (value === 'logs') void loadRelatedExecutions()
})
</script>

<template>
  <div>
    <PageHeader title="MCP 管理" description="动态注册平台 MCP Gateway 下的只读 filesystem/database 能力，并执行真实连接测试。">
      <template #actions><NButton type="primary" @click="openCreate"><template #icon><NIcon :component="Plus" /></template>创建 MCP</NButton></template>
    </PageHeader>
    <NAlert type="info" :bordered="false" style="margin-bottom: 16px">所有注册项必须指向后端配置的 MCP_GATEWAY_ENDPOINT，Agent 不能绕过平台网关。</NAlert>
    <div class="toolbar"><NInput v-model:value="query" class="search" clearable placeholder="搜索 MCP"><template #prefix><NIcon :component="Search" /></template></NInput><div class="toolbar-spacer" /><span class="muted" style="font-size: 11px">{{ filtered.length }} 项</span></div>
    <section class="surface resource-list">
      <div v-if="resourceStore.loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="PlugConnected" size="24" /></div><h3>暂无 MCP</h3><p>创建平台网关下的只读能力。</p></div></div>
      <article v-for="server in filtered" v-else :key="server.id" class="resource-row resource-row-clickable" @click="openDetail(server)">
        <span class="resource-icon"><NIcon :component="server.config.kind === 'database' ? Database : Files" size="19" /></span>
        <div class="resource-main"><strong>{{ server.name }}</strong><span class="mono">{{ server.id }}</span></div>
        <div class="resource-description truncate"><span class="mono">{{ server.endpoint }}</span><br /><span class="muted">Type {{ server.config.kind }} · Tools 未暴露 · {{ formatDate(server.updated_at) }}</span></div>
        <div class="resource-meta resource-actions"><NTag size="small" :type="server.status === 'online' ? 'success' : server.status === 'offline' ? 'error' : 'default'" :bordered="false">{{ server.status }}</NTag><NTag size="small" :bordered="false">{{ server.permission }}</NTag><NButton size="tiny" @click.stop="edit(server)">编辑</NButton><NButton size="tiny" :loading="testingId === server.id" @click.stop="test(server)">测试</NButton><NButton size="tiny" type="error" text @click.stop="remove(server)">删除</NButton></div>
      </article>
    </section>

    <NModal :show="selected !== null" preset="card" style="width: min(860px, 94vw)" title="MCP 详情" @update:show="closeDetail">
      <template v-if="selected">
        <nav class="detail-tabs modal-tabs"><button v-for="tab in [{key:'endpoint',label:'Endpoint'},{key:'tools',label:'Tools'},{key:'agents',label:'Agents'},{key:'logs',label:'Logs'}]" :key="tab.key" type="button" :class="{ active: detailTab === tab.key }" @click="detailTab = tab.key as typeof detailTab">{{ tab.label }}</button></nav>
        <dl v-if="detailTab === 'endpoint'" class="execution-definition-list"><div><dt>ID</dt><dd class="mono">{{ selected.id }}</dd></div><div><dt>Endpoint</dt><dd class="mono">{{ selected.endpoint }}</dd></div><div><dt>Type</dt><dd>{{ selected.config.kind }}</dd></div><div><dt>Permission</dt><dd>{{ selected.permission }}</dd></div><div><dt>Status</dt><dd>{{ selected.status }}</dd></div><div><dt>Updated</dt><dd>{{ formatDate(selected.updated_at) }}</dd></div></dl>
        <template v-else-if="detailTab === 'tools'"><NAlert type="info" :bordered="false" style="margin-bottom:14px">现有 MCP Registry API 返回能力类型，不返回远端 tools/list 结果。</NAlert><div class="unavailable-panel"><strong>{{ selected.config.kind }}</strong><span>工具清单需要后端新增受控发现接口后展示；当前权限固定为 read_only。</span></div></template>
        <div v-else-if="detailTab === 'agents'"><div v-if="detailLoading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div><div v-else-if="boundAgents.length" class="selection-list"><div v-for="agent in boundAgents" :key="agent.id"><strong>{{ agent.name }}</strong><span class="mono">{{ agent.id }}</span></div></div><div v-else class="unavailable-panel"><strong>没有 Agent 绑定此 MCP</strong><span>当前结果来自控制台聚合数据。</span></div></div>
        <div v-else><NAlert type="info" :bordered="false" style="margin-bottom:14px">当前只能按 Execution 关联 MCP 调用；选择记录后进入 Trace Center 查看调用节点。</NAlert><div v-if="detailLoading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div><div v-else-if="relatedExecutions.length" class="agent-log-list"><button v-for="item in relatedExecutions.slice(0,20)" :key="item.id" type="button" @click="router.push({name:'trace-detail',params:{id:item.id}})"><span class="mono">{{ item.id }}</span><span>{{ item.agent_name }}</span><span>{{ item.mcp_call_count }} MCP</span><time>{{ formatDate(item.started_at) }}</time></button></div><div v-else class="unavailable-panel"><strong>没有可关联的 MCP 调用记录</strong><span>Execution 只记录调用数量，当前不能精确反查到某个 MCP ID。</span></div></div>
      </template>
    </NModal>

    <NModal v-model:show="showCreate" preset="card" style="width: min(560px, 92vw)" :title="editingId ? '编辑 MCP' : '创建 MCP'">
      <NForm label-placement="top" @submit.prevent="create">
        <div class="form-grid"><NFormItem label="MCP ID"><NInput v-model:value="form.id" :disabled="Boolean(editingId)" placeholder="filesystem-mcp" /></NFormItem><NFormItem label="名称"><NInput v-model:value="form.name" placeholder="只读文件能力" /></NFormItem></div>
        <NFormItem label="能力类型"><NSelect v-model:value="form.kind" :options="[{ label: 'filesystem', value: 'filesystem' }, { label: 'database', value: 'database' }]" /></NFormItem>
        <NFormItem label="Gateway Endpoint"><NInput v-model:value="form.endpoint" /></NFormItem>
        <NAlert type="warning" :bordered="false">权限固定为 read_only，后端还会校验 Endpoint 必须等于平台网关。</NAlert>
        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px"><NButton @click="showCreate = false">取消</NButton><NButton attr-type="submit" type="primary" :loading="saving">{{ editingId ? '保存' : '创建' }}</NButton></div>
      </NForm>
    </NModal>
  </div>
</template>
