<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NIcon, useDialog, useMessage } from 'naive-ui'
import { ArrowLeft, Hierarchy, Book2, Edit, PlugConnected, TestPipe, Api, GitBranch, Heartbeat, History } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import BindingDialog from '@/components/BindingDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'
import {
  agentConfigurationLockMessage,
  confirmAgentRollback,
  isAgentConfigurationLocked,
} from '@/utils/productionRuntime'
import type {
  AgentHealth,
  AgentLifecycleStatus,
  AgentRuntime,
  AgentSession,
  AgentTask,
  AgentVersion,
  AgentWorkspace,
  Artifact,
  ExecutionSummary,
  ModelAdapterName,
  RuntimeType,
} from '@/types/api'
import { platformApi } from '@/api/platform'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const agentId = computed(() => String(route.params.id))
const dialogType = ref<'skills' | 'mcps' | 'knowledge' | null>(null)
const saving = ref(false)
const schemaSaving = ref(false)
const inputSchemaText = ref('{}')
const outputSchemaText = ref('{}')
const configurationSaving = ref(false)
const systemPromptText = ref('')
const promptTemplateText = ref('{{input}}')
const modelText = ref('hermes-agent')
const modelAdapter = ref<ModelAdapterName>('hermes')
const runtimeType = ref<RuntimeType>('hermes')
const runtimeConfigText = ref('{}')
const runtimes = ref<AgentRuntime[]>([])
const runtimeChecking = ref(false)
const modelConfigText = ref('{}')
const phase3Loading = ref(false)
const sessions = ref<AgentSession[]>([])
const tasks = ref<AgentTask[]>([])
const artifacts = ref<Artifact[]>([])
const executions = ref<ExecutionSummary[]>([])
const workspace = ref<AgentWorkspace | null>(null)
const phase4Loading = ref(false)
const lifecycleSaving = ref(false)
const versionSaving = ref(false)
const health = ref<AgentHealth | null>(null)
const versions = ref<AgentVersion[]>([])
const editingVersion = ref<AgentVersion | null>(null)
const versionSnapshotText = ref('{}')
const versionNotes = ref('')
const versionTestInput = ref('')
const versionTestOutput = ref('')
const versionTesting = ref(false)
const comparingVersion = ref<AgentVersion | null>(null)
const activeTab = ref<'overview' | 'configuration' | 'versions' | 'execution' | 'api' | 'artifacts' | 'logs'>('overview')
const detailTabs = [
  { key: 'overview', label: '概览' },
  { key: 'configuration', label: '配置' },
  { key: 'versions', label: '版本' },
  { key: 'execution', label: '执行记录' },
  { key: 'api', label: '接口' },
  { key: 'artifacts', label: '产物' },
  { key: 'logs', label: '日志' },
] as const

const currentVersion = computed(() => versions.value.find((item) => item.status === 'published') || null)
const lastExecution = computed(() => executions.value[0] || null)
const selectedRuntime = computed(() => {
  const runtimeId = agentStore.currentAgent?.runtime_config?.runtime_id
  return runtimes.value.find((item) => item.id === runtimeId) || null
})
const successRate = computed(() => {
  if (!executions.value.length) return '--'
  const completed = executions.value.filter((item) => ['succeeded', 'failed'].includes(item.status))
  if (!completed.length) return '--'
  return `${(completed.filter((item) => item.status === 'succeeded').length / completed.length * 100).toFixed(1)}%`
})

const lifecycleLabels: Array<{ label: string; value: AgentLifecycleStatus }> = [
  { label: 'Active', value: 'active' },
  { label: 'Inactive', value: 'inactive' },
  { label: '已归档', value: 'archived' },
]
const selectedLifecycle = computed<AgentLifecycleStatus>(() => {
  const status = agentStore.currentAgent?.status
  if (['draft', 'testing', 'published'].includes(status || '')) return 'active'
  if (['disabled', 'suspended'].includes(status || '')) return 'inactive'
  return (status as AgentLifecycleStatus) || 'active'
})
const configurationLocked = computed(() => isAgentConfigurationLocked(
  agentStore.currentAgent?.status,
  agentStore.currentAgent?.current_version_id,
))
const configurationLockReason = computed(() => agentConfigurationLockMessage(agentStore.currentAgent?.status))
const lifecycleOptions = computed(() => {
  const allowed: Record<AgentLifecycleStatus, AgentLifecycleStatus[]> = {
    active: ['inactive', 'archived'],
    inactive: ['active', 'archived'],
    archived: [],
  }
  return lifecycleLabels.map((item) => ({
    ...item,
    disabled: item.value !== selectedLifecycle.value && !allowed[selectedLifecycle.value].includes(item.value),
  }))
})

const skillOptions = computed(() => resourceStore.skills.map((item) => ({
  label: `${item.name} (${item.id}) · ${item.runtime_support.join('/')}`,
  value: item.id,
  disabled: !item.runtime_support.includes(agentStore.currentAgent?.runtime_type || 'hermes'),
})))
const mcpOptions = computed(() => resourceStore.mcpServers.map((item) => ({ label: `${item.name} (${item.config.kind})`, value: item.id })))
const knowledgeOptions = computed(() => resourceStore.knowledgeSources.map((item) => ({ label: `${item.name} (${item.status})`, value: item.id })))

const dialogConfig = computed(() => {
  if (dialogType.value === 'skills') return { title: '编辑 Skill 绑定', description: 'Skill 由后端校验并在 Agent 执行时加载。', options: skillOptions.value, selected: agentStore.currentSkills.map((item) => item.id) }
  if (dialogType.value === 'mcps') return { title: '编辑 MCP 绑定', description: '第一阶段只允许平台 MCP Gateway 下的只读 filesystem/database 能力。', options: mcpOptions.value, selected: agentStore.currentMCPServers.map((item) => item.id) }
  return { title: '编辑知识源绑定', description: '绑定后，运行时会先检索活跃知识源，再将召回内容写入执行上下文。', options: knowledgeOptions.value, selected: agentStore.currentKnowledgeSources.map((item) => item.id) }
})

async function load() {
  await Promise.all([
    agentStore.fetchAgentDetail(agentId.value),
    resourceStore.fetchAll(),
    platformApi.listRuntimes().then((value) => { runtimes.value = value }),
  ]).catch(() => undefined)
  if (agentStore.currentAgent) {
    inputSchemaText.value = JSON.stringify(agentStore.currentAgent.input_schema || {}, null, 2)
    outputSchemaText.value = JSON.stringify(agentStore.currentAgent.output_schema || {}, null, 2)
    systemPromptText.value = agentStore.currentAgent.system_prompt
    promptTemplateText.value = agentStore.currentAgent.prompt_template
    modelText.value = agentStore.currentAgent.model
    modelAdapter.value = agentStore.currentAgent.model_adapter
    runtimeType.value = agentStore.currentAgent.runtime_type
    runtimeConfigText.value = JSON.stringify(agentStore.currentAgent.runtime_config || {}, null, 2)
    modelConfigText.value = JSON.stringify(agentStore.currentAgent.model_config || {}, null, 2)
  }
  phase3Loading.value = true
  await Promise.all([
    platformApi.listSessions(agentId.value).then((value) => { sessions.value = value }),
    platformApi.listTasks(agentId.value).then((value) => { tasks.value = value }),
    platformApi.listArtifacts(agentId.value).then((value) => { artifacts.value = value }),
    platformApi.getWorkspace(agentId.value).then((value) => { workspace.value = value }),
    platformApi.listExecutions({ agent_id: agentId.value, limit: 50 }).then((value) => { executions.value = value.items }),
  ]).catch(() => undefined).finally(() => { phase3Loading.value = false })
  await loadProductionRuntime()
}

async function loadProductionRuntime() {
  phase4Loading.value = true
  const [healthResult, versionsResult] = await Promise.allSettled([
    platformApi.getAgentHealth(agentId.value),
    platformApi.listAgentVersions(agentId.value),
  ])
  health.value = healthResult.status === 'fulfilled' ? healthResult.value : null
  versions.value = versionsResult.status === 'fulfilled' ? versionsResult.value : []
  phase4Loading.value = false
}

async function setLifecycle(status: AgentLifecycleStatus) {
  if (status === agentStore.currentAgent?.status) return
  lifecycleSaving.value = true
  try {
    await platformApi.updateAgentLifecycle(agentId.value, status)
    await agentStore.fetchAgentDetail(agentId.value)
    await loadProductionRuntime()
    message.success('Agent 生命周期已更新')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    lifecycleSaving.value = false
  }
}

async function createVersion() {
  versionSaving.value = true
  try {
    await platformApi.createAgentVersion(agentId.value, { notes: '控制台创建开发版本', created_by: 'control-center' })
    await loadProductionRuntime()
    message.success('Development Version 已创建')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

async function publish(version: string) {
  versionSaving.value = true
  try {
    await platformApi.publishAgent(agentId.value, { version, notes: '通过控制台发布' })
    await agentStore.fetchAgentDetail(agentId.value)
    await loadProductionRuntime()
    message.success(`${version} 已发布`)
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

async function advanceVersion(version: AgentVersion, status: 'development' | 'testing' | 'release_candidate') {
  versionSaving.value = true
  try {
    await platformApi.updateAgentVersionStatus(agentId.value, version.version, status)
    await loadProductionRuntime()
    message.success(`${version.version} 已进入 ${status}`)
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

function nextVersionStatus(version: AgentVersion): 'testing' | 'release_candidate' | null {
  if (version.status === 'development') return 'testing'
  if (version.status === 'testing') return 'release_candidate'
  return null
}

async function rollback(version: string) {
  versionSaving.value = true
  try {
    await platformApi.rollbackAgent(agentId.value, version)
    await agentStore.fetchAgentDetail(agentId.value)
    await loadProductionRuntime()
    message.success(`已回滚到 ${version}`)
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

function requestRollback(version: string) {
  confirmAgentRollback(dialog, version, () => rollback(version))
}

function rejectLockedEdit(): boolean {
  if (!configurationLocked.value) return false
  message.warning(configurationLockReason.value, { duration: 6000 })
  return true
}

function openBindingEditor(type: 'skills' | 'mcps' | 'knowledge') {
  if (rejectLockedEdit()) return
  dialogType.value = type
}

function snapshotSummary(version: AgentVersion): string {
  const snapshot = version.snapshot
  const skills = snapshot.skill_ids?.length || 0
  const mcps = snapshot.mcp_ids?.length || 0
  return `${snapshot.model?.name || '未记录模型'} · ${skills} Skill · ${mcps} MCP`
}

function openVersionEditor(version: AgentVersion) {
  editingVersion.value = version
  versionSnapshotText.value = JSON.stringify(version.snapshot, null, 2)
  versionNotes.value = version.description || ''
  versionTestInput.value = ''
  versionTestOutput.value = ''
}

async function saveVersion() {
  if (!editingVersion.value) return
  versionSaving.value = true
  try {
    await platformApi.updateAgentVersion(agentId.value, editingVersion.value.version, {
      snapshot: JSON.parse(versionSnapshotText.value) as AgentVersion['snapshot'],
      notes: versionNotes.value.trim() || null,
    })
    await loadProductionRuntime()
    editingVersion.value = versions.value.find((item) => item.version === editingVersion.value?.version) || null
    message.success('Version 快照已保存')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

async function testVersion() {
  if (!editingVersion.value || !versionTestInput.value.trim()) return
  versionTesting.value = true
  versionTestOutput.value = ''
  try {
    const result = await platformApi.runAgentVersion(agentId.value, editingVersion.value.version, {
      input: versionTestInput.value.trim(),
      session_id: `version-${editingVersion.value.version}`,
    })
    versionTestOutput.value = result.output
    message.success('版本测试完成，生产配置未被修改')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionTesting.value = false
  }
}

async function saveConfiguration() {
  if (rejectLockedEdit()) return
  configurationSaving.value = true
  try {
    await agentStore.updateConfiguration(agentId.value, {
      system_prompt: systemPromptText.value,
      model: modelText.value,
      prompt_template: promptTemplateText.value,
      model_adapter: modelAdapter.value,
      runtime_type: runtimeType.value,
      runtime_config: JSON.parse(runtimeConfigText.value) as Record<string, unknown>,
      model_config: JSON.parse(modelConfigText.value) as Record<string, unknown>,
    })
    message.success('Prompt 与模型配置已保存')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { configurationSaving.value = false }
}

async function checkSelectedRuntime() {
  if (!selectedRuntime.value) return
  runtimeChecking.value = true
  try {
    const healthResult = await platformApi.checkRuntime(selectedRuntime.value.id)
    runtimes.value = await platformApi.listRuntimes()
    if (healthResult.status === 'online') message.success(`Runtime 在线，延迟 ${healthResult.latency_ms}ms`)
    else message.error(healthResult.detail, { duration: 7000 })
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    runtimeChecking.value = false
  }
}

async function saveSchema() {
  if (rejectLockedEdit()) return
  schemaSaving.value = true
  try {
    const inputSchema = JSON.parse(inputSchemaText.value) as Record<string, unknown>
    const outputSchema = JSON.parse(outputSchemaText.value) as Record<string, unknown>
    await agentStore.updateSchema(agentId.value, inputSchema, outputSchema)
    message.success('输入输出 Schema 已保存并通过后端校验')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { schemaSaving.value = false }
}

async function saveBindings(selected: string[]) {
  if (rejectLockedEdit()) {
    dialogType.value = null
    return
  }
  saving.value = true
  try {
    if (dialogType.value === 'skills') await agentStore.syncSkills(agentId.value, selected)
    if (dialogType.value === 'mcps') await agentStore.syncMCPServers(agentId.value, selected)
    if (dialogType.value === 'knowledge') await agentStore.syncKnowledgeSources(agentId.value, selected)
    message.success('绑定已更新')
    dialogType.value = null
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 6000 })
    await agentStore.fetchAgentDetail(agentId.value).catch(() => undefined)
  } finally {
    saving.value = false
  }
}

watch(agentId, load)
onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="agentStore.currentAgent?.name || 'Agent 详情'" :description="agentStore.currentAgent?.description || '查看平台中保存的 Agent 配置和绑定关系。'">
      <template #actions>
        <NButton @click="router.push({ name: 'agents' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回列表</NButton>
        <NButton :disabled="!agentStore.currentAgent" @click="activeTab = 'configuration'"><template #icon><NIcon :component="Edit" /></template>编辑</NButton>
        <NButton :disabled="versions.every((item) => item.status !== 'deprecated')" @click="activeTab = 'versions'"><template #icon><NIcon :component="History" /></template>回滚</NButton>
        <NButton type="primary" :disabled="agentStore.currentAgent?.status !== 'active'" @click="router.push({ name: 'agent-playground', params: { id: agentId } })">
          <template #icon><NIcon :component="TestPipe" /></template>打开执行台
        </NButton>
      </template>
    </PageHeader>

    <section v-if="agentStore.currentAgent" class="agent-detail-commandbar surface">
      <div><span>Agent ID</span><strong class="mono">{{ agentStore.currentAgent.id }}</strong></div>
      <div><span>Status</span><StatusTag :status="agentStore.currentAgent.status" /></div>
      <div><span>Version</span><strong class="mono">{{ currentVersion?.version || '未发布' }}</strong></div>
      <div><span>Model</span><strong class="mono">{{ agentStore.currentAgent.model }}</strong></div>
    </section>

    <nav class="detail-tabs" aria-label="Agent 详情导航">
      <button
        v-for="tab in detailTabs"
        :key="tab.key"
        type="button"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >{{ tab.label }}</button>
    </nav>

    <div v-if="agentStore.error" class="error-panel" style="margin-bottom: 16px">{{ agentStore.error }}</div>
    <div v-if="agentStore.detailLoading" class="detail-grid">
      <div class="loading-stack"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div class="skeleton-line" style="height: 300px" />
    </div>
    <div
      v-else-if="agentStore.currentAgent"
      class="detail-grid"
      :class="{
        'detail-tab-main': activeTab === 'versions',
        'detail-tab-aside': ['execution', 'api', 'artifacts', 'logs'].includes(activeTab),
      }"
    >
      <div class="detail-stack">
        <section v-show="activeTab === 'overview'" class="surface panel">
          <div class="section-heading">
            <div><h2>生产生命周期</h2><p>状态迁移由后端校验；归档后不可再调用</p></div>
            <StatusTag :status="agentStore.currentAgent.status" />
          </div>
          <div class="lifecycle-controls">
            <NSelect
              :value="selectedLifecycle"
              :options="lifecycleOptions"
              :loading="lifecycleSaving"
              :disabled="selectedLifecycle === 'archived'"
              @update:value="setLifecycle($event as AgentLifecycleStatus)"
            />
            <NButton secondary :loading="versionSaving" :disabled="selectedLifecycle === 'archived'" @click="createVersion"><template #icon><NIcon :component="GitBranch" /></template>创建 Version</NButton>
          </div>
          <NAlert v-if="configurationLocked" type="warning" :bordered="false" style="margin-top: 14px">
            {{ configurationLockReason }}
          </NAlert>
        </section>

        <section v-show="activeTab === 'overview'" class="surface panel">
          <div class="section-heading"><div><h2>基础配置</h2><p>来自 `GET /api/agents/{id}`</p></div><StatusTag :status="agentStore.currentAgent.status" /></div>
          <dl class="definition-list" style="margin: 20px 0 0">
            <div class="definition-item"><dt>Agent ID</dt><dd class="mono">{{ agentStore.currentAgent.id }}</dd></div>
            <div class="definition-item"><dt>角色</dt><dd>{{ agentStore.currentAgent.role }}</dd></div>
            <div class="definition-item"><dt>Agent 类型</dt><dd>{{ agentStore.currentAgent.agent_type === 'manager' ? 'Manager' : 'Worker' }}</dd></div>
            <div class="definition-item"><dt>Runtime</dt><dd class="mono">{{ agentStore.currentAgent.runtime_type }}</dd></div>
            <div class="definition-item"><dt>Runtime Version</dt><dd class="mono">{{ selectedRuntime?.version || '--' }}</dd></div>
            <div class="definition-item"><dt>Runtime Status</dt><dd><StatusTag :status="selectedRuntime?.status || 'unknown'" /></dd></div>
            <div class="definition-item"><dt>上级 Agent</dt><dd class="mono">{{ agentStore.currentAgent.parent_agent_id || '--' }}</dd></div>
            <div class="definition-item"><dt>模型</dt><dd class="mono">{{ agentStore.currentAgent.model }}</dd></div>
            <div class="definition-item"><dt>Adapter</dt><dd class="mono">{{ agentStore.currentAgent.model_adapter }}</dd></div>
            <div class="definition-item"><dt>Current Version</dt><dd class="mono">{{ currentVersion?.version || '未发布' }}</dd></div>
            <div class="definition-item"><dt>创建时间</dt><dd>{{ formatDate(agentStore.currentAgent.created_at) }}</dd></div>
            <div class="definition-item"><dt>更新时间</dt><dd>{{ formatDate(agentStore.currentAgent.updated_at) }}</dd></div>
            <div class="definition-item"><dt>最近执行</dt><dd>{{ lastExecution ? formatDate(lastExecution.started_at) : '暂无执行' }}</dd></div>
            <div class="definition-item"><dt>成功率</dt><dd>{{ successRate }}</dd></div>
          </dl>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading"><div><h2>输入 / 输出 Schema</h2><p>保存时校验 JSON Schema；公共调用还会校验实际请求和输出。</p></div><NButton type="primary" secondary :loading="schemaSaving" :disabled="configurationLocked" @click="saveSchema">保存 Schema</NButton></div>
          <div class="schema-grid"><NFormItem label="Input Schema"><NInput v-model:value="inputSchemaText" type="textarea" :rows="11" class="mono" :disabled="configurationLocked" /></NFormItem><NFormItem label="Output Schema"><NInput v-model:value="outputSchemaText" type="textarea" :rows="11" class="mono" :disabled="configurationLocked" /></NFormItem></div>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading"><div><h2>Memory</h2><p>Session 生命周期内的 Agent 隔离记忆边界</p></div><NIcon :component="Book2" size="20" /></div>
          <dl class="execution-definition-list">
            <div><dt>Namespace</dt><dd class="mono">agent:{agent_id}:session:{session_id}</dd></div>
            <div><dt>Sessions</dt><dd>{{ phase3Loading ? '--' : sessions.length }}</dd></div>
            <div><dt>配置方式</dt><dd>当前后端按 Session 自动隔离，不提供浏览器侧 Memory 配置接口</dd></div>
          </dl>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading"><div><h2>Prompt Builder / Model Adapter</h2><p>模板变量在后端解析，配置写入 Agent Schema</p></div><NButton type="primary" secondary :loading="configurationSaving" :disabled="configurationLocked" @click="saveConfiguration">保存配置</NButton></div>
          <div class="form-grid">
            <NFormItem label="模型"><NInput v-model:value="modelText" :disabled="configurationLocked" /></NFormItem>
            <NFormItem label="Model Adapter"><NSelect v-model:value="modelAdapter" :disabled="configurationLocked" :options="[{label:'Hermes',value:'hermes'},{label:'Qwen',value:'qwen'},{label:'DeepSeek',value:'deepseek'},{label:'GPT / OpenAI',value:'gpt'},{label:'Claude',value:'claude'}]" /></NFormItem>
            <NFormItem label="Agent Runtime"><NSelect v-model:value="runtimeType" :disabled="configurationLocked" :options="[{label:'Hermes Runtime',value:'hermes'},{label:'Pi Runtime',value:'pi'}]" /></NFormItem>
            <NFormItem class="span-2" label="Model Config JSON"><NInput v-model:value="modelConfigText" type="textarea" :rows="4" class="mono" :disabled="configurationLocked" /></NFormItem>
            <NFormItem class="span-2" label="Runtime Config JSON"><NInput v-model:value="runtimeConfigText" type="textarea" :rows="4" class="mono" :disabled="configurationLocked" placeholder='{"runtime_id":"..."}' /></NFormItem>
          </div>
          <div class="lifecycle-controls" style="margin-bottom: 14px">
            <span>{{ selectedRuntime ? `${selectedRuntime.name} · ${selectedRuntime.endpoint}` : '未绑定注册表实例，将使用环境变量默认端点' }}</span>
            <NButton secondary :loading="runtimeChecking" :disabled="!selectedRuntime" @click="checkSelectedRuntime">检查 Runtime</NButton>
          </div>
          <NFormItem label="System Prompt"><NInput v-model:value="systemPromptText" type="textarea" :rows="7" :disabled="configurationLocked" /></NFormItem>
          <NFormItem label="Prompt Template"><NInput v-model:value="promptTemplateText" type="textarea" :rows="7" class="mono" :disabled="configurationLocked" /></NFormItem>
        </section>

        <section v-show="activeTab === 'versions'" class="surface panel">
          <div class="section-heading">
            <div><h2>Agent Version 工作区</h2><p>Development → Testing → Release Candidate → Published</p></div>
            <NIcon :component="GitBranch" size="20" />
          </div>
          <div v-if="phase4Loading" class="loading-stack"><div v-for="index in 2" :key="index" class="skeleton-line" /></div>
          <div v-else-if="versions.length" class="binding-list">
            <div v-for="version in versions" :key="version.id" class="version-row">
              <div><strong>{{ version.version }}{{ version.status === 'published' ? ' · 当前' : '' }}</strong><span>{{ snapshotSummary(version) }} · {{ formatDate(version.created_at) }}</span></div>
              <StatusTag :status="version.status" />
              <div class="version-actions">
                <span class="muted">{{ version.description || '无发布说明' }}</span>
                <NButton text size="tiny" @click="comparingVersion = version">Compare</NButton>
                <NButton v-if="['development', 'testing', 'release_candidate'].includes(version.status)" text size="tiny" @click="openVersionEditor(version)">编辑 / 测试</NButton>
                <NButton v-if="nextVersionStatus(version)" text size="tiny" :loading="versionSaving" @click="advanceVersion(version, nextVersionStatus(version)!)">进入 {{ nextVersionStatus(version) }}</NButton>
                <NButton v-if="version.status === 'release_candidate'" text size="tiny" type="primary" :loading="versionSaving" @click="publish(version.version)">发布</NButton>
                <NButton v-if="version.status === 'deprecated' && selectedLifecycle === 'active'" text size="tiny" type="primary" :loading="versionSaving" @click="requestRollback(version.version)">回滚到此版本</NButton>
              </div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">尚未创建生产版本快照。</p>
        </section>
      </div>

      <aside class="detail-stack">
        <section v-show="activeTab === 'overview'" class="surface panel">
          <div class="section-heading">
            <div><h2>运行健康</h2><p>模型、Skill 和 MCP 实时检查</p></div>
            <NIcon :component="Heartbeat" size="20" />
          </div>
          <div v-if="phase4Loading" class="skeleton-line" />
          <template v-else-if="health">
            <StatusTag :status="health.status" />
            <div class="binding-list" style="margin-top: 14px">
              <div v-for="item in (['model', 'skills', 'mcp'] as const)" :key="item" class="binding-row">
                <div><strong>{{ { model: 'Model', skills: 'Skill', mcp: 'MCP' }[item] }}</strong><span>{{ health.checks[item]?.detail || '未返回检查结果' }}</span></div>
                <StatusTag :status="health.checks[item]?.status || 'unknown'" style="margin-left: auto" />
              </div>
            </div>
            <p class="muted" style="margin: 12px 0 0; font-size: 10px">检查时间 {{ formatDate(health.checked_at) }}</p>
          </template>
          <p v-else class="muted" style="font-size: 12px">健康检查暂不可用。</p>
          <NButton block secondary style="margin-top: 14px" :loading="phase4Loading" @click="loadProductionRuntime">重新检查</NButton>
        </section>
        <section v-show="activeTab === 'execution'" class="surface panel">
          <div class="section-heading"><div><h2>隔离运行空间</h2><p>Phase 3 Session / Task / Artifact</p></div><NButton text type="primary" @click="router.push({ name: 'executions' })">执行中心</NButton></div>
          <dl class="definition-list" style="grid-template-columns:1fr;gap:10px">
            <div class="definition-item"><dt>Workspace</dt><dd class="mono">{{ workspace?.root || `${agentId}/sessions` }}</dd></div>
            <div class="definition-item"><dt>Sessions</dt><dd>{{ phase3Loading ? '-' : workspace?.session_count || sessions.length }}</dd></div>
            <div class="definition-item"><dt>Running Tasks</dt><dd>{{ tasks.filter((item) => item.status === 'running').length }}</dd></div>
            <div class="definition-item"><dt>Artifacts</dt><dd>{{ phase3Loading ? '-' : workspace?.artifact_count || artifacts.length }}</dd></div>
          </dl>
        </section>
        <section v-show="activeTab === 'api'" class="surface panel">
          <div class="section-heading"><div><h2>生产 API</h2><p>发布状态与授权均由 Phase 4 生产运行时管理</p></div><NIcon :component="Api" size="20" /></div>
          <dl class="definition-list" style="grid-template-columns: 1fr; gap: 10px"><div class="definition-item"><dt>Agent 状态</dt><dd>{{ agentStore.currentAgent.status }}</dd></div><div class="definition-item"><dt>API 开关</dt><dd>{{ agentStore.currentAgent.api_enabled ? '已开启' : '已关闭' }}</dd></div><div class="definition-item"><dt>默认响应</dt><dd>{{ agentStore.currentAgent.response_mode === 'stream' ? 'SSE Stream' : 'Sync JSON' }}</dd></div><div class="definition-item"><dt>Sync Endpoint</dt><dd class="mono">/api/public/agents/{{ agentId }}/run</dd></div><div class="definition-item"><dt>Stream Endpoint</dt><dd class="mono">/api/public/agents/{{ agentId }}/stream</dd></div><div class="definition-item"><dt>认证</dt><dd>API Client Key + Agent 授权绑定</dd></div></dl>
          <NButton style="margin-top: 14px" block @click="router.push({ name: 'apis' })">打开 API 管理</NButton>
        </section>
        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading">
            <div><h2>Skill</h2><p>{{ agentStore.currentSkills.length }} 个已绑定</p></div>
            <NButton text type="primary" :disabled="configurationLocked" @click="openBindingEditor('skills')"><template #icon><NIcon :component="Edit" /></template>{{ configurationLocked ? '已锁定' : '编辑' }}</NButton>
          </div>
          <div v-if="agentStore.currentSkills.length" class="binding-list">
            <div v-for="skill in agentStore.currentSkills" :key="skill.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="Hierarchy" /></span><div><strong>{{ skill.name }}</strong><span>{{ skill.id }}</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定 Skill</p>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading">
            <div><h2>MCP</h2><p>{{ agentStore.currentMCPServers.length }} 个只读能力</p></div>
            <NButton text type="primary" :disabled="configurationLocked" @click="openBindingEditor('mcps')"><template #icon><NIcon :component="Edit" /></template>{{ configurationLocked ? '已锁定' : '编辑' }}</NButton>
          </div>
          <div v-if="agentStore.currentMCPServers.length" class="binding-list">
            <div v-for="server in agentStore.currentMCPServers" :key="server.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="PlugConnected" /></span><div><strong>{{ server.name }}</strong><span>{{ server.config.kind }} / read-only</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定 MCP</p>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading">
            <div><h2>Knowledge</h2><p>{{ agentStore.currentKnowledgeSources.length }} 个知识源</p></div>
            <NButton text type="primary" :disabled="configurationLocked" @click="openBindingEditor('knowledge')"><template #icon><NIcon :component="Edit" /></template>{{ configurationLocked ? '已锁定' : '编辑' }}</NButton>
          </div>
          <div v-if="agentStore.currentKnowledgeSources.length" class="binding-list">
            <div v-for="source in agentStore.currentKnowledgeSources" :key="source.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="Book2" /></span><div><strong>{{ source.name }}</strong><span>{{ source.status }}</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定知识源</p>
        </section>
        <section v-show="activeTab === 'artifacts'" class="surface panel">
          <div class="section-heading"><div><h2>Agent Artifacts</h2><p>{{ artifacts.length }} 个已登记产物</p></div><NButton text type="primary" @click="router.push({ name: 'artifacts' })">打开产物中心</NButton></div>
          <div v-if="phase3Loading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
          <div v-else-if="artifacts.length" class="artifact-list">
            <a v-for="artifact in artifacts" :key="artifact.id" class="artifact-row" :href="platformApi.artifactDownloadUrl(artifact.id)">
              <NIcon :component="Api" size="18" />
              <div><strong>{{ artifact.filename }}</strong><span class="mono">{{ artifact.content_type }} · {{ artifact.size_bytes }} bytes</span><span class="mono">SHA-256 {{ artifact.sha256 }}</span></div>
            </a>
          </div>
          <div v-else class="empty-state empty-state-compact"><div><h3>尚无 Artifact</h3><p>Agent 产生文件后，会显示在这里并支持受控下载。</p></div></div>
        </section>
        <section v-show="activeTab === 'logs'" class="surface panel">
          <div class="section-heading"><div><h2>Agent Logs</h2><p>来自 Execution History 的持久化运行记录</p></div><NButton text type="primary" @click="router.push({ name: 'executions' })">全部历史</NButton></div>
          <NAlert type="info" :bordered="false" style="margin-bottom: 14px">当前后端没有独立容器日志接口；此处只展示可审计的 Execution 状态、错误和时间。</NAlert>
          <div v-if="phase3Loading" class="loading-stack"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
          <div v-else-if="executions.length" class="agent-log-list">
            <button v-for="item in executions.slice(0, 20)" :key="item.id" type="button" @click="router.push({ name: 'trace-detail', params: { id: item.id } })">
              <StatusTag :status="item.status" /><span class="mono">{{ item.id }}</span><span>{{ item.task }}</span><time>{{ formatDate(item.started_at) }}</time>
            </button>
          </div>
          <div v-else class="empty-state empty-state-compact"><div><h3>暂无执行日志</h3><p>运行 Agent 后，可审计记录会显示在这里。</p></div></div>
        </section>
      </aside>
    </div>

    <BindingDialog
      :show="dialogType !== null"
      :title="dialogConfig.title"
      :description="dialogConfig.description"
      :options="dialogConfig.options"
      :selected="dialogConfig.selected"
      :loading="saving"
      @update:show="dialogType = $event ? dialogType : null"
      @save="saveBindings"
    />

    <NModal
      :show="editingVersion !== null"
      preset="card"
      style="width: min(980px, 94vw)"
      :title="`${editingVersion?.version || ''} · Version 工作区`"
      :mask-closable="!versionSaving && !versionTesting"
      @update:show="editingVersion = $event ? editingVersion : null"
    >
      <NAlert type="info" :bordered="false" style="margin-bottom: 16px">
        此处修改独立 Version 快照，不会覆盖当前 Published 版本。Testing / Release Candidate 可直接执行验证。
      </NAlert>
      <div class="schema-grid">
        <div>
          <NFormItem label="完整 Snapshot JSON">
            <NInput v-model:value="versionSnapshotText" type="textarea" :rows="24" class="mono" />
          </NFormItem>
          <NFormItem label="版本说明">
            <NInput v-model:value="versionNotes" type="textarea" :rows="3" />
          </NFormItem>
          <NButton type="primary" :loading="versionSaving" @click="saveVersion">保存 Version</NButton>
        </div>
        <div>
          <NFormItem label="测试输入">
            <NInput v-model:value="versionTestInput" type="textarea" :rows="8" placeholder="输入本次版本验证任务" />
          </NFormItem>
          <NButton
            type="primary"
            secondary
            :disabled="!editingVersion || !['testing', 'release_candidate'].includes(editingVersion.status) || !versionTestInput.trim()"
            :loading="versionTesting"
            @click="testVersion"
          >执行此 Version</NButton>
          <NFormItem label="测试输出" style="margin-top: 16px">
            <NInput :value="versionTestOutput" type="textarea" :rows="12" readonly placeholder="运行结果会显示在这里，并写入 Execution History" />
          </NFormItem>
        </div>
      </div>
    </NModal>

    <NModal :show="comparingVersion !== null" preset="card" style="width: min(1040px, 94vw)" :title="`${comparingVersion?.version || ''} · Compare`" @update:show="comparingVersion = $event ? comparingVersion : null">
      <NAlert type="info" :bordered="false" style="margin-bottom: 16px">左侧为当前 Published 快照，右侧为所选版本；只读比较，不修改生产配置。</NAlert>
      <div class="version-grid">
        <section><div class="section-heading"><div><h2>{{ currentVersion?.version || '当前未发布' }}</h2><p>Current Published</p></div></div><pre class="json-viewer">{{ JSON.stringify(currentVersion?.snapshot || {}, null, 2) }}</pre></section>
        <section><div class="section-heading"><div><h2>{{ comparingVersion?.version }}</h2><p>{{ comparingVersion?.status }}</p></div></div><pre class="json-viewer">{{ JSON.stringify(comparingVersion?.snapshot || {}, null, 2) }}</pre></section>
      </div>
    </NModal>
  </div>
</template>
