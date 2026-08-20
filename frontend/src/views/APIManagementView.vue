<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NDatePicker, NForm, NFormItem, NIcon, NInputNumber, NModal, useMessage } from 'naive-ui'
import { Api, GitBranch, Key, Plus, Trash, Users, Link, Ban } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import { isValidClientRateLimit } from '@/utils/productionRuntime'
import type {
  Agent,
  AgentAPIVersion,
  AgentSchemaVersion,
  AgentAPIClientBinding,
  APIClient,
  APIKey,
  LifecycleStatus,
  MetricsSummary,
} from '@/types/api'

const message = useMessage()
const agents = ref<Agent[]>([])
const loading = ref(false)
const secret = ref<string | null>(null)
const selectedAgent = ref<Agent | null>(null)
const schemaVersions = ref<AgentSchemaVersion[]>([])
const apiVersions = ref<AgentAPIVersion[]>([])
const versionsLoading = ref(false)
const showSchemaEditor = ref(false)
const editingSchema = ref<AgentSchemaVersion | null>(null)
const showApiEditor = ref(false)
const editingApi = ref<AgentAPIVersion | null>(null)
const submitting = ref(false)
const schemaForm = reactive({ version: '', input: '{}', output: '{}' })
const apiForm = reactive({ apiVersion: '', schemaVersion: '' })
const clients = ref<APIClient[]>([])
const clientsLoading = ref(false)
const showClientEditor = ref(false)
const editingClient = ref<APIClient | null>(null)
const clientSubmitting = ref(false)
const clientForm = reactive({ name: '', owner: '', rateLimitPerMinute: 60 })
const selectedClient = ref<APIClient | null>(null)
const clientKeys = ref<APIKey[]>([])
const clientBindings = ref<AgentAPIClientBinding[]>([])
const clientDetailLoading = ref(false)
const showKeyEditor = ref(false)
const keyForm = reactive({ name: '', expiresAt: null as number | null })
const selectedBindingAgentIds = ref<string[]>([])
const bindingSaving = ref(false)
const apiExampleAgent = ref<Agent | null>(null)
const origin = window.location.origin
const metrics = ref<MetricsSummary | null>(null)
const publishedVersions = ref<Record<string, string | null>>({})

const bindingOptions = computed(() => agents.value.map((agent) => ({
  label: `${agent.name} (${agent.id})`,
  value: agent.id,
})))

const schemaOptions = computed(() => schemaVersions.value.map((item) => ({
  label: `${item.version} · ${lifecycleLabel(item.status)}`,
  value: item.version,
})))

async function load() {
  loading.value = true
  clientsLoading.value = true
  try {
    const [agentResult, clientResult] = await Promise.allSettled([
      platformApi.listAgents(),
      platformApi.listAPIClients(),
    ])
    if (agentResult.status === 'rejected') throw agentResult.reason
    agents.value = agentResult.value
    clients.value = clientResult.status === 'fulfilled' ? clientResult.value : []
    const [metricsResult, ...versionResults] = await Promise.allSettled([
      platformApi.getMetricsSummary(),
      ...agents.value.map((agent) => platformApi.listAgentVersions(agent.id)),
    ])
    metrics.value = metricsResult.status === 'fulfilled' ? metricsResult.value : null
    publishedVersions.value = Object.fromEntries(agents.value.map((agent, index) => {
      const result = versionResults[index]
      return [agent.id, result?.status === 'fulfilled' ? (result.value.find((item) => item.status === 'published')?.version || null) : null]
    }))
  }
  catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { loading.value = false }
  clientsLoading.value = false
}

function openClientEditor() {
  editingClient.value = null
  clientForm.name = ''
  clientForm.owner = ''
  clientForm.rateLimitPerMinute = 60
  showClientEditor.value = true
}

function openClientSettings(client: APIClient) {
  editingClient.value = client
  clientForm.name = client.name
  clientForm.owner = client.owner
  clientForm.rateLimitPerMinute = client.rate_limit_per_minute
  showClientEditor.value = true
}

async function saveClient() {
  if (!clientForm.name.trim() || !clientForm.owner.trim()) {
    message.warning('请填写 Client 名称和负责人')
    return
  }
  if (!isValidClientRateLimit(clientForm.rateLimitPerMinute)) {
    message.warning('每分钟限流必须是 1 到 100000 的整数')
    return
  }
  clientSubmitting.value = true
  try {
    const payload = {
      name: clientForm.name.trim(),
      owner: clientForm.owner.trim(),
      rate_limit_per_minute: clientForm.rateLimitPerMinute,
    }
    if (editingClient.value) await platformApi.updateAPIClient(editingClient.value.id, payload)
    else await platformApi.createAPIClient(payload)
    showClientEditor.value = false
    await load()
    message.success(editingClient.value ? 'API Client 设置已更新' : 'API Client 已创建')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { clientSubmitting.value = false }
}

async function openClient(client: APIClient) {
  selectedClient.value = client
  clientDetailLoading.value = true
  try {
    [clientKeys.value, clientBindings.value] = await Promise.all([
      platformApi.listAPIKeys(client.id),
      platformApi.listAPIClientBindings(client.id),
    ])
    selectedBindingAgentIds.value = clientBindings.value.map((item) => item.agent_id)
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { clientDetailLoading.value = false }
}

function openKeyEditor() {
  keyForm.name = ''
  keyForm.expiresAt = null
  showKeyEditor.value = true
}

async function createClientKey() {
  if (!selectedClient.value || !keyForm.name.trim()) {
    message.warning('请填写 Key 名称')
    return
  }
  clientSubmitting.value = true
  try {
    const result = await platformApi.createAPIKey(selectedClient.value.id, {
      name: keyForm.name.trim(),
      expires_at: keyForm.expiresAt ? new Date(keyForm.expiresAt).toISOString() : null,
    })
    secret.value = result.api_key
    showKeyEditor.value = false
    await openClient(selectedClient.value)
    await load()
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { clientSubmitting.value = false }
}

async function revokeKey(key: APIKey) {
  if (!selectedClient.value) return
  try {
    await platformApi.updateAPIKey(selectedClient.value.id, key.id, { status: 'revoked' })
    await openClient(selectedClient.value)
    message.success('API Key 已撤销')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

async function disableClient(client: APIClient) {
  try {
    await platformApi.updateAPIClient(client.id, { status: client.status === 'active' ? 'suspended' : 'active' })
    await load()
    message.success(client.status === 'active' ? 'Client 已停用' : 'Client 已启用')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

async function saveClientBindings() {
  if (!selectedClient.value) return
  bindingSaving.value = true
  const existing = new Set(clientBindings.value.map((item) => item.agent_id))
  const selected = new Set(selectedBindingAgentIds.value)
  try {
    const changes = [
      ...[...selected].filter((id) => !existing.has(id)).map((id) => platformApi.bindAPIClientAgent(selectedClient.value!.id, id)),
      ...[...existing].filter((id) => !selected.has(id)).map((id) => platformApi.unbindAPIClientAgent(selectedClient.value!.id, id)),
    ]
    const results = await Promise.allSettled(changes)
    const failed = results.filter((result) => result.status === 'rejected')
    if (failed.length) throw new Error(`${failed.length} 个绑定变更失败`)
    await openClient(selectedClient.value)
    await load()
    message.success('Agent 授权绑定已更新')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { bindingSaving.value = false }
}

async function openVersions(agent: Agent) {
  selectedAgent.value = agent
  await loadVersions()
}

async function loadVersions() {
  if (!selectedAgent.value) return
  versionsLoading.value = true
  try {
    [schemaVersions.value, apiVersions.value] = await Promise.all([
      platformApi.listSchemaVersions(selectedAgent.value.id),
      platformApi.listAPIVersions(selectedAgent.value.id),
    ])
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { versionsLoading.value = false }
}

function openSchemaEditor(item?: AgentSchemaVersion) {
  editingSchema.value = item || null
  schemaForm.version = item?.version || nextVersion(schemaVersions.value.map((value) => value.version))
  schemaForm.input = JSON.stringify(item?.input_schema || selectedAgent.value?.input_schema || {}, null, 2)
  schemaForm.output = JSON.stringify(item?.output_schema || selectedAgent.value?.output_schema || {}, null, 2)
  showSchemaEditor.value = true
}

async function saveSchema() {
  if (!selectedAgent.value) return
  let inputSchema: Record<string, unknown>
  let outputSchema: Record<string, unknown>
  try {
    inputSchema = parseObject(schemaForm.input, 'Input Schema')
    outputSchema = parseObject(schemaForm.output, 'Output Schema')
  } catch (error) { message.error((error as Error).message); return }
  submitting.value = true
  try {
    if (editingSchema.value) {
      await platformApi.updateSchemaVersion(selectedAgent.value.id, editingSchema.value.version, {
        input_schema: inputSchema, output_schema: outputSchema,
      })
    } else {
      await platformApi.createSchemaVersion(selectedAgent.value.id, {
        version: schemaForm.version, input_schema: inputSchema, output_schema: outputSchema,
      })
    }
    showSchemaEditor.value = false
    await loadVersions()
    message.success(editingSchema.value ? 'Schema 版本已保存' : 'Schema 版本已创建')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { submitting.value = false }
}

async function removeSchema(item: AgentSchemaVersion) {
  if (!selectedAgent.value) return
  try {
    await platformApi.deleteSchemaVersion(selectedAgent.value.id, item.version)
    await loadVersions()
    message.success('Schema 版本已删除')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

async function advanceSchema(item: AgentSchemaVersion) {
  if (!selectedAgent.value) return
  const status = nextStatus(item.status)
  if (!status) return
  try {
    await platformApi.updateSchemaVersionStatus(selectedAgent.value.id, item.version, status)
    await loadVersions()
    message.success(`Schema 已进入 ${lifecycleLabel(status)}`)
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

function openApiEditor(item?: AgentAPIVersion) {
  editingApi.value = item || null
  apiForm.apiVersion = item?.api_version || nextVersion(apiVersions.value.map((value) => value.api_version))
  apiForm.schemaVersion = item?.schema_version.version || schemaVersions.value.find((value) => value.status === 'published')?.version || schemaVersions.value[0]?.version || ''
  showApiEditor.value = true
}

async function saveApi() {
  if (!selectedAgent.value) return
  submitting.value = true
  try {
    if (editingApi.value) {
      await platformApi.updateAPIVersionBinding(selectedAgent.value.id, editingApi.value.api_version, apiForm.schemaVersion)
    } else {
      await platformApi.createAPIVersion(selectedAgent.value.id, {
        api_version: apiForm.apiVersion, schema_version: apiForm.schemaVersion,
      })
    }
    showApiEditor.value = false
    await loadVersions()
    message.success(editingApi.value ? 'API 绑定已更新' : 'API 版本已创建')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  finally { submitting.value = false }
}

async function removeApi(item: AgentAPIVersion) {
  if (!selectedAgent.value) return
  try {
    await platformApi.deleteAPIVersion(selectedAgent.value.id, item.api_version)
    await loadVersions()
    message.success('API 版本已删除')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

async function advanceApi(item: AgentAPIVersion) {
  if (!selectedAgent.value) return
  const status = nextStatus(item.status)
  if (!status) return
  try {
    await platformApi.updateAPIVersionStatus(selectedAgent.value.id, item.api_version, status)
    await loadVersions()
    message.success(`API 已进入 ${lifecycleLabel(status)}`)
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
}

function nextStatus(status: LifecycleStatus): LifecycleStatus | null {
  return ({ draft: 'testing', testing: 'published', published: 'deprecated', deprecated: 'disabled', disabled: null } as const)[status]
}

function lifecycleLabel(status: LifecycleStatus) {
  return ({ draft: '草稿', testing: '测试中', published: '已发布', deprecated: '已弃用', disabled: '已禁用' } as const)[status]
}

function nextVersion(versions: string[]) {
  const latest = Math.max(0, ...versions.map((value) => Number(value.slice(1))).filter(Number.isInteger))
  return `v${latest + 1}`
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 必须是 JSON 对象`)
  return parsed as Record<string, unknown>
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="API 管理" description="管理生产 API Client、一次性 Key、Agent 授权，以及 API Version 与不可变 Schema 契约的绑定。" />
    <NAlert v-if="secret" type="warning" :bordered="false" style="margin-bottom: 16px" closable @close="secret = null">
      API Key 明文仅在创建时显示一次。请立即保存，关闭后无法再次查看：<span class="mono secret-value">{{ secret }}</span>
    </NAlert>
    <section class="surface panel" style="margin-bottom: 18px">
      <div class="section-heading">
        <div><h2>API Clients</h2><p>按业务系统分配 Key、Agent 调用权限和调用统计</p></div>
        <NButton type="primary" size="small" @click="openClientEditor"><template #icon><NIcon :component="Plus" /></template>新建 Client</NButton>
      </div>
      <div v-if="clientsLoading" class="loading-stack"><div v-for="index in 2" :key="index" class="skeleton-line" /></div>
      <div v-else-if="clients.length" class="client-grid">
        <article v-for="client in clients" :key="client.id" class="client-card">
          <div class="client-card-head"><span class="binding-icon"><NIcon :component="Users" /></span><div><strong>{{ client.name }}</strong><span>{{ client.owner }} · {{ client.id }}</span></div><NTag size="small" :type="client.status === 'active' ? 'success' : 'error'" :bordered="false">{{ client.status === 'active' ? '已启用' : client.status === 'suspended' ? '已暂停' : '已撤销' }}</NTag></div>
          <div class="client-metrics"><span><strong>{{ client.key_count }}</strong> Key</span><span><strong>{{ client.agent_count }}</strong> Agent</span><span><strong>{{ client.call_count }}</strong> 调用</span><span>限流 {{ client.rate_limit_per_minute }}/分钟</span><span>最近 {{ formatDate(client.last_called_at) }}</span></div>
          <div class="client-actions"><NButton size="tiny" secondary @click="openClient(client)">管理授权</NButton><NButton size="tiny" text @click="openClientSettings(client)">设置</NButton><NButton v-if="client.status !== 'revoked'" size="tiny" text :type="client.status === 'active' ? 'error' : 'primary'" @click="disableClient(client)">{{ client.status === 'active' ? '暂停' : '启用' }}</NButton></div>
        </article>
      </div>
      <div v-else class="version-empty">暂无 API Client；生产调用必须先创建 Client 并绑定 Agent。</div>
    </section>
    <section class="surface resource-list">
      <div v-if="loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="agents.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="Api" size="24" /></div><h3>暂无 Agent</h3><p>先创建 Agent，再配置发布 API。</p></div></div>
      <article v-for="agent in agents" v-else :key="agent.id" class="api-row">
        <span class="resource-icon"><NIcon :component="Api" size="19" /></span>
        <div class="resource-main"><strong>{{ agent.name }}</strong><span class="mono">{{ agent.id }}</span><span class="mono endpoint-line">POST /api/public/agents/{{ agent.id }}/run</span><span class="mono endpoint-line">POST /api/public/agents/{{ agent.id }}/stream</span></div>
        <div class="api-metrics"><span>Version <strong class="mono">{{ publishedVersions[agent.id] || '未发布' }}</strong></span><span>状态 <NTag size="small" :bordered="false">{{ agent.api_enabled ? '已开启' : '已关闭' }}</NTag></span><span>调用 {{ metrics ? `${metrics.call_count} 次平台累计` : '指标不可用' }}</span><span>默认响应 {{ agent.response_mode === 'stream' ? 'SSE Stream' : 'Sync JSON' }}</span></div>
        <div class="api-actions"><NButton size="small" @click="apiExampleAgent = agent">调用示例</NButton><NButton size="small" secondary @click="openVersions(agent)"><template #icon><NIcon :component="GitBranch" /></template>Schema / API 版本</NButton></div>
      </article>
    </section>

    <NModal :show="apiExampleAgent !== null" preset="card" style="width: min(900px, 94vw)" :title="`${apiExampleAgent?.name || ''} · Agent API`" @update:show="apiExampleAgent = $event ? apiExampleAgent : null">
      <template v-if="apiExampleAgent">
        <div class="api-example-grid">
          <section><div class="section-heading"><div><h2>curl Example</h2><p>使用 API Client 创建时保存的 Key</p></div></div><pre class="json-viewer">curl -X POST '{{ origin }}/api/public/agents/{{ apiExampleAgent.id }}/run' \
  -H 'Authorization: Bearer &lt;API_KEY&gt;' \
  -H 'Content-Type: application/json' \
  -d '{"input":"分析任务","session_id":"api-session"}'</pre></section>
          <section><div class="section-heading"><div><h2>Request Schema</h2><p>Agent 当前输入契约</p></div></div><pre class="json-viewer">{{ JSON.stringify(apiExampleAgent.input_schema, null, 2) }}</pre></section>
          <section><div class="section-heading"><div><h2>Response Example</h2><p>字段结构示例，值不伪造真实执行结果</p></div></div><pre class="json-viewer">{{ JSON.stringify({ execution_id: '&lt;execution_id&gt;', agent_id: apiExampleAgent.id, session_id: '&lt;session_id&gt;', status: 'succeeded', output: '&lt;agent_output&gt;', hermes_run_id: '&lt;runtime_id_or_null&gt;' }, null, 2) }}</pre></section>
          <section><div class="section-heading"><div><h2>Stream Endpoint</h2><p>Server-Sent Events</p></div></div><pre class="json-viewer">POST /api/public/agents/{{ apiExampleAgent.id }}/stream
Accept: text/event-stream
Authorization: Bearer &lt;API_KEY&gt;</pre></section>
        </div>
      </template>
    </NModal>

    <NModal v-model:show="showClientEditor" preset="card" style="width: min(500px, 92vw)" :title="editingClient ? '编辑 API Client' : '新建 API Client'">
      <NForm label-placement="top" @submit.prevent="saveClient">
        <NFormItem label="Client 名称"><NInput v-model:value="clientForm.name" maxlength="120" placeholder="数据分析系统" /></NFormItem>
        <NFormItem label="负责人"><NInput v-model:value="clientForm.owner" maxlength="120" placeholder="业务系统负责人或团队" /></NFormItem>
        <NFormItem label="每分钟限流">
          <NInputNumber v-model:value="clientForm.rateLimitPerMinute" :min="1" :max="100000" :step="10" style="width: 100%" />
        </NFormItem>
        <NAlert type="info" :bordered="false">限流按 Client 统计，允许 1-100000 次/分钟，默认 60。</NAlert>
        <div class="modal-actions"><NButton @click="showClientEditor = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="clientSubmitting">{{ editingClient ? '保存' : '创建' }}</NButton></div>
      </NForm>
    </NModal>

    <NModal :show="selectedClient !== null" preset="card" style="width: min(820px, 94vw)" :title="`${selectedClient?.name || ''} · 凭据与授权`" @update:show="selectedClient = $event ? selectedClient : null">
      <div v-if="clientDetailLoading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
      <div v-else class="version-grid">
        <section>
          <div class="section-heading"><div><h2>API Keys</h2><p>数据库只存 Hash 与 Prefix</p></div><NButton size="small" type="primary" @click="openKeyEditor"><template #icon><NIcon :component="Key" /></template>创建 Key</NButton></div>
          <div class="binding-list">
            <div v-for="key in clientKeys" :key="key.id" class="version-row">
              <div><strong>{{ key.name }} · {{ key.prefix }}…</strong><span>{{ key.call_count }} 次调用 · 最近 {{ formatDate(key.last_used_at) }}</span></div>
              <NTag size="small" :type="key.status === 'active' ? 'success' : 'error'" :bordered="false">{{ key.status }}</NTag>
              <div v-if="key.status === 'active'" class="version-actions"><NButton text size="tiny" type="error" @click="revokeKey(key)"><NIcon :component="Ban" />撤销</NButton></div>
            </div>
            <div v-if="clientKeys.length === 0" class="version-empty">暂无 Key</div>
          </div>
        </section>
        <section>
          <div class="section-heading"><div><h2>Agent 绑定</h2><p>仅允许调用显式授权的 Agent</p></div><NIcon :component="Link" size="19" /></div>
          <NSelect v-model:value="selectedBindingAgentIds" multiple filterable :options="bindingOptions" placeholder="选择允许调用的 Agent" />
          <NAlert type="info" :bordered="false" style="margin-top: 12px">权限固定为 invoke；保存时只提交实际新增或删除的绑定。</NAlert>
          <NButton block type="primary" secondary style="margin-top: 14px" :loading="bindingSaving" @click="saveClientBindings">保存 Agent 授权</NButton>
        </section>
      </div>
    </NModal>

    <NModal v-model:show="showKeyEditor" preset="card" style="width: min(500px, 92vw)" title="创建 API Key">
      <NForm label-placement="top" @submit.prevent="createClientKey">
        <NFormItem label="Key 名称"><NInput v-model:value="keyForm.name" maxlength="120" placeholder="生产调用凭据" /></NFormItem>
        <NFormItem label="过期时间（可选）"><NDatePicker v-model:value="keyForm.expiresAt" type="datetime" clearable style="width: 100%" /></NFormItem>
        <NAlert type="warning" :bordered="false">Key 明文只会在创建成功后展示一次。</NAlert>
        <div class="modal-actions"><NButton @click="showKeyEditor = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="clientSubmitting">创建 Key</NButton></div>
      </NForm>
    </NModal>

    <NModal :show="selectedAgent !== null" preset="card" style="width: min(1040px, 94vw)" :title="`${selectedAgent?.name || ''} · 版本管理`" @update:show="selectedAgent = $event ? selectedAgent : null">
      <div v-if="versionsLoading" class="loading-stack"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else class="version-grid">
        <section>
          <div class="section-heading"><div><h2>Schema Versions</h2><p>published 后契约不可修改</p></div><NButton size="small" type="primary" @click="openSchemaEditor()"><template #icon><NIcon :component="Plus" /></template>新建 Schema</NButton></div>
          <div class="binding-list">
            <div v-for="item in schemaVersions" :key="item.id" class="version-row">
              <div><strong>{{ item.version }}</strong><span>发布于 {{ formatDate(item.published_at) }}</span></div>
              <NTag size="small" :bordered="false">{{ lifecycleLabel(item.status) }}</NTag>
              <div class="version-actions"><NButton v-if="['draft','testing'].includes(item.status)" text size="tiny" @click="openSchemaEditor(item)">编辑</NButton><NButton v-if="nextStatus(item.status)" text size="tiny" @click="advanceSchema(item)">进入{{ lifecycleLabel(nextStatus(item.status)!) }}</NButton><NButton v-if="['draft','testing'].includes(item.status)" text size="tiny" type="error" @click="removeSchema(item)"><NIcon :component="Trash" /></NButton></div>
            </div>
            <div v-if="schemaVersions.length === 0" class="version-empty">暂无 Schema 版本</div>
          </div>
        </section>
        <section>
          <div class="section-heading"><div><h2>API Versions</h2><p>每个入口固定绑定一个 Schema</p></div><NButton size="small" type="primary" :disabled="schemaVersions.length === 0" @click="openApiEditor()"><template #icon><NIcon :component="Plus" /></template>新建 API</NButton></div>
          <div class="binding-list">
            <div v-for="item in apiVersions" :key="item.id" class="version-row">
              <div><strong>{{ item.api_version }} → {{ item.schema_version.version }}</strong><span class="mono">{{ item.endpoint }}</span></div>
              <NTag size="small" :bordered="false">{{ lifecycleLabel(item.status) }}</NTag>
              <div class="version-actions"><NButton v-if="['draft','testing'].includes(item.status)" text size="tiny" @click="openApiEditor(item)">改绑</NButton><NButton v-if="nextStatus(item.status)" text size="tiny" @click="advanceApi(item)">进入{{ lifecycleLabel(nextStatus(item.status)!) }}</NButton><NButton v-if="['draft','testing'].includes(item.status)" text size="tiny" type="error" @click="removeApi(item)"><NIcon :component="Trash" /></NButton></div>
            </div>
            <div v-if="apiVersions.length === 0" class="version-empty">暂无 API 版本</div>
          </div>
        </section>
      </div>
    </NModal>

    <NModal v-model:show="showSchemaEditor" preset="card" style="width: min(820px, 94vw)" :title="editingSchema ? `编辑 Schema ${editingSchema.version}` : '新建 Schema 版本'">
      <NForm label-placement="top" @submit.prevent="saveSchema">
        <NFormItem label="Version"><NInput v-model:value="schemaForm.version" :disabled="Boolean(editingSchema)" placeholder="v2" /></NFormItem>
        <div class="schema-grid"><NFormItem label="Input Schema"><NInput v-model:value="schemaForm.input" type="textarea" :rows="14" class="mono" /></NFormItem><NFormItem label="Output Schema"><NInput v-model:value="schemaForm.output" type="textarea" :rows="14" class="mono" /></NFormItem></div>
        <div class="modal-actions"><NButton @click="showSchemaEditor = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="submitting">保存</NButton></div>
      </NForm>
    </NModal>

    <NModal v-model:show="showApiEditor" preset="card" style="width: min(520px, 92vw)" :title="editingApi ? `调整 ${editingApi.api_version} 绑定` : '新建 API 版本'">
      <NForm label-placement="top" @submit.prevent="saveApi">
        <NFormItem label="API Version"><NInput v-model:value="apiForm.apiVersion" :disabled="Boolean(editingApi)" placeholder="v2" /></NFormItem>
        <NFormItem label="Schema Version"><NSelect v-model:value="apiForm.schemaVersion" :options="schemaOptions" /></NFormItem>
        <NAlert type="info" :bordered="false">API 发布后绑定不可修改；deprecated 仍支持历史调用，disabled 会拒绝调用。</NAlert>
        <div class="modal-actions"><NButton @click="showApiEditor = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="submitting" :disabled="!apiForm.schemaVersion">保存</NButton></div>
      </NForm>
    </NModal>
  </div>
</template>
