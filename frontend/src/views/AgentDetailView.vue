<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NFormItem, NIcon, NInputNumber, NModal, useDialog, useMessage } from 'naive-ui'
import { ArrowLeft, Hierarchy, Book2, Edit, PlugConnected, TestPipe, Api, GitBranch, Heartbeat, History } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import BindingDialog from '@/components/BindingDialog.vue'
import AgentConversationPanel from '@/components/agent/AgentConversationPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { apiClient, getApiErrorMessage } from '@/api/client'
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
  RegisteredModel,
  RuntimeType,
  AgentEditorModel,
  CapabilityBindingWrite,
  CapabilityCatalogItem,
  ResourceScopeRecord,
} from '@/types/api'
import { platformApi } from '@/api/platform'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const editorModel = ref<AgentEditorModel | null>(null)
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
const runtimeId = ref<string | null>(null)
const runtimeConfigText = ref('{}')
const capabilityProfileText = ref('{}')
const runtimes = ref<AgentRuntime[]>([])
const models = ref<RegisteredModel[]>([])
const runtimeChecking = ref(false)
const modelConfigText = ref('{}')
const phase3Loading = ref(false)
const sessions = ref<AgentSession[]>([])
const tasks = ref<AgentTask[]>([])
const artifacts = ref<Artifact[]>([])
const executions = ref<ExecutionSummary[]>([])
const executionHistoryLoading = ref(false)
const executionHistoryError = ref<string | null>(null)
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
const capabilityBindingOpen = ref(false)
const capabilityBindingLoading = ref(false)
const capabilityBindingSaving = ref(false)
const availableCapabilityCatalog = ref<CapabilityCatalogItem[]>([])
const capabilityScopeRecords = ref<ResourceScopeRecord[]>([])
const selectedCapabilityVersionIds = ref<string[]>([])

interface EditableCapabilityBinding extends Omit<CapabilityBindingWrite, 'quota_policy'> {
  key: string
  label: string
  version: string
  quota_policy: { calls_per_execution: number; calls_per_minute: number; max_concurrency: number; [key: string]: unknown }
}

const editableCapabilityBindings = ref<EditableCapabilityBinding[]>([])
const activeTab = ref<'overview' | 'configuration' | 'execution' | 'versions'>('overview')
let hydratingConfiguration = false
const detailTabs = [
  { key: 'overview', label: '概览' },
  { key: 'configuration', label: '构建' },
  { key: 'execution', label: '运行' },
  { key: 'versions', label: '版本' },
] as const

const currentVersion = computed(() => versions.value.find((item) => item.status === 'published') || null)
const displayedVersion = computed(() => editorModel.value?.agent.version || currentVersion.value?.version || null)
const displayedVersionState = computed(() => {
  if (editorModel.value?.agent.version_source === 'published') return '已发布版本（只读）'
  if (editorModel.value?.agent.version_source === 'draft') return '草稿版本'
  return '未发布'
})
const lastExecution = computed(() => executions.value[0] || null)
const selectedRuntime = computed(() => {
  const configured = runtimes.value.find((item) => item.id === runtimeId.value)
  if (configured) return configured
  const matching = runtimes.value.filter((item) => item.type === runtimeType.value)
  return matching.length === 1 ? matching[0] : null
})
const runtimeOptions = computed(() => runtimes.value
  .filter((runtime) => runtime.type === runtimeType.value && runtime.status !== 'disabled')
  .map((runtime) => ({ label: `${runtime.name} · ${runtime.version} · ${runtime.status}`, value: runtime.id })))
const runtimeTypeOptions = computed(() => [
  { label: 'Hermes Runtime', value: 'hermes' },
  { label: 'Pi Runtime', value: 'pi' },
  {
    label: runtimes.value.some((runtime) => runtime.type === 'deepseek') ? 'DeepSeek Harness' : 'DeepSeek Harness · 未注册',
    value: 'deepseek',
    disabled: !runtimes.value.some((runtime) => runtime.type === 'deepseek' && runtime.status !== 'disabled'),
  },
])
const selectedModel = computed(() => models.value.find((item) => item.id === modelText.value) || null)
const modelOptions = computed(() => models.value.map((item) => ({
  label: `${item.display_name} · ${item.provider}${item.is_default ? ' · 默认' : ''}${item.is_enabled ? '' : ' · 已停用'}`,
  value: item.id,
  disabled: !item.is_enabled,
})))
const successRate = computed(() => {
  if (!executions.value.length) return '--'
  const completed = executions.value.filter((item) => ['succeeded', 'failed'].includes(item.status))
  if (!completed.length) return '--'
  return `${(completed.filter((item) => item.status === 'succeeded').length / completed.length * 100).toFixed(1)}%`
})

async function loadExecutionHistory() {
  executionHistoryLoading.value = true
  executionHistoryError.value = null
  try {
    const value = await platformApi.listExecutions({ agent_id: agentId.value, limit: 50 })
    executions.value = value.items
  } catch (error) {
    executions.value = []
    executionHistoryError.value = getApiErrorMessage(error)
  } finally {
    executionHistoryLoading.value = false
  }
}

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
const capabilityBindingEditable = computed(() => editorModel.value?.agent.version_source === 'draft' && Boolean(editorModel.value.agent.draft_version_id))
const capabilityCatalogOptions = computed(() => availableCapabilityCatalog.value
  .filter((item) => !item.key.startsWith('database.'))
  .map((item) => ({ label: `${item.label} · ${item.key}@${item.version}`, value: item.id })))
const capabilityScopeOptions = computed(() => capabilityScopeRecords.value
  .filter((item) => item.current_revision_id)
  .map((item) => ({ label: `${item.name} · ${item.resource_type}`, value: item.current_revision_id as string })))
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
    platformApi.listModels().then((value) => { models.value = value }),
    platformApi.getAgentEditor(agentId.value).then((value) => { editorModel.value = value }),
  ]).catch(() => undefined)
  if (agentStore.currentAgent) {
    hydratingConfiguration = true
    inputSchemaText.value = JSON.stringify(agentStore.currentAgent.input_schema || {}, null, 2)
    outputSchemaText.value = JSON.stringify(agentStore.currentAgent.output_schema || {}, null, 2)
    systemPromptText.value = agentStore.currentAgent.system_prompt
    promptTemplateText.value = agentStore.currentAgent.prompt_template
    modelText.value = agentStore.currentAgent.model
    modelAdapter.value = agentStore.currentAgent.model_adapter
    runtimeType.value = agentStore.currentAgent.runtime_type
    runtimeId.value = agentStore.currentAgent.runtime_id
    runtimeConfigText.value = JSON.stringify(agentStore.currentAgent.runtime_config || {}, null, 2)
    capabilityProfileText.value = JSON.stringify(agentStore.currentAgent.capability_profile || {}, null, 2)
    modelConfigText.value = JSON.stringify(agentStore.currentAgent.model_config || {}, null, 2)
    hydratingConfiguration = false
  }
  phase3Loading.value = true
  await Promise.all([
    platformApi.listSessions(agentId.value).then((value) => { sessions.value = value }),
    platformApi.listTasks(agentId.value).then((value) => { tasks.value = value }),
    platformApi.listArtifacts(agentId.value).then((value) => { artifacts.value = value }),
    platformApi.getWorkspace(agentId.value).then((value) => { workspace.value = value }),
    loadExecutionHistory(),
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
    editorModel.value = await platformApi.getAgentEditor(agentId.value)
    message.success('Development Version 已创建')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    versionSaving.value = false
  }
}

function defaultToolAlias(key: string): string {
  const base = key.replaceAll('.', '_').replaceAll('-', '_').replace(/[^a-z0-9_.-]/g, '').slice(0, 120) || 'capability'
  let candidate = base
  let suffix = 2
  const used = new Set(editableCapabilityBindings.value.map((item) => item.tool_alias))
  while (used.has(candidate)) candidate = `${base}_${suffix++}`
  return candidate
}

function syncCapabilitySelection(values: string[]) {
  const selected = new Set(values)
  editableCapabilityBindings.value = editableCapabilityBindings.value.filter((item) => selected.has(item.capability_version_id))
  for (const versionId of values) {
    if (editableCapabilityBindings.value.some((item) => item.capability_version_id === versionId)) continue
    const capability = availableCapabilityCatalog.value.find((item) => item.id === versionId)
    if (!capability) continue
    editableCapabilityBindings.value.push({
      key: capability.key,
      label: capability.label,
      version: capability.version,
      tool_alias: defaultToolAlias(capability.key),
      capability_version_id: capability.id,
      implementation_mode: 'DEFAULT_PRIORITY',
      implementation_id: null,
      resource_scope_revision_id: null,
      parameter_policy: {},
      quota_policy: { calls_per_execution: 20, calls_per_minute: 60, max_concurrency: 2 },
      approval_policy: {},
      enabled: true,
      source_type: 'direct',
      source_ref_id: null,
    })
  }
  selectedCapabilityVersionIds.value = values
}

async function openCapabilityBindingEditor() {
  if (!capabilityBindingEditable.value) {
    message.warning('请先创建 Development Version，再修改能力绑定')
    return
  }
  capabilityBindingOpen.value = true
  capabilityBindingLoading.value = true
  try {
    const [available, scopes, bindingResponse] = await Promise.all([
      platformApi.getAvailableComponents(agentId.value),
      platformApi.listResourceScopes(),
      apiClient.get<CapabilityBindingWrite[]>(`/api/agents/${encodeURIComponent(agentId.value)}/draft/capability-bindings`),
    ])
    const catalog = [...available.capabilities]
    const displayRows = new Map((editorModel.value?.sections.capabilities || []).map((item) => [item.binding_id, item]))
    const directBindings = bindingResponse.data.filter((item) => item.source_type === 'direct').filter((item) => {
      const display = displayRows.get(String((item as CapabilityBindingWrite & { id?: string }).id || ''))
      return !display?.key.startsWith('database.')
    })
    for (const binding of directBindings) {
      if (catalog.some((item) => item.id === binding.capability_version_id)) continue
      const bindingId = String((binding as CapabilityBindingWrite & { id?: string }).id || '')
      const display = displayRows.get(bindingId)
      if (display && !display.key.startsWith('database.')) {
        catalog.push({ id: binding.capability_version_id, key: display.key, label: display.label, description: display.description, version: display.version || '历史版本', input_schema: {}, ui_schema: {} })
      }
    }
    availableCapabilityCatalog.value = catalog
    capabilityScopeRecords.value = scopes
    editableCapabilityBindings.value = directBindings.map((binding) => {
      const capability = catalog.find((item) => item.id === binding.capability_version_id)
      return {
        ...binding,
        key: capability?.key || 'unknown',
        label: capability?.label || '历史 Capability',
        version: capability?.version || 'unknown',
        quota_policy: {
          ...(binding.quota_policy || {}),
          calls_per_execution: Number(binding.quota_policy?.calls_per_execution || 20),
          calls_per_minute: Number(binding.quota_policy?.calls_per_minute || 60),
          max_concurrency: Number(binding.quota_policy?.max_concurrency || 2),
        },
      }
    })
    selectedCapabilityVersionIds.value = editableCapabilityBindings.value.map((item) => item.capability_version_id)
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    capabilityBindingLoading.value = false
  }
}

async function saveAgentCapabilityBindings() {
  const aliases = editableCapabilityBindings.value.map((item) => item.tool_alias.trim())
  if (aliases.some((item) => !/^[a-z][a-z0-9_.-]{0,127}$/.test(item))) return message.warning('Tool Alias 必须以小写字母开头，只能包含小写字母、数字、点、横线和下划线')
  if (new Set(aliases).size !== aliases.length) return message.warning('Tool Alias 不能重复')
  capabilityBindingSaving.value = true
  try {
    await platformApi.updateCapabilityBindings(agentId.value, editableCapabilityBindings.value.map((item) => ({
      tool_alias: item.tool_alias.trim(), capability_version_id: item.capability_version_id,
      implementation_mode: item.implementation_mode, implementation_id: item.implementation_id || null,
      resource_scope_revision_id: item.resource_scope_revision_id || null,
      parameter_policy: item.parameter_policy || {}, quota_policy: item.quota_policy || {},
      approval_policy: item.approval_policy || {}, enabled: item.enabled !== false,
      source_type: 'direct', source_ref_id: item.source_ref_id || null,
    })))
    editorModel.value = await platformApi.getAgentEditor(agentId.value)
    const preflight = await platformApi.preflightAgent(agentId.value)
    editorModel.value.preflight = preflight
    capabilityBindingOpen.value = false
    message.success(preflight.state === 'READY' ? '能力绑定已保存，Preflight 通过' : '能力绑定已保存，请按 Preflight 提示补齐配置')
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    capabilityBindingSaving.value = false
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
  if (runtimeType.value === 'deepseek' && (!runtimeId.value || selectedRuntime.value?.status !== 'online')) {
    message.warning('DeepSeek Harness 必须绑定已注册且在线的 Runtime 实例')
    return
  }
  configurationSaving.value = true
  try {
    await agentStore.updateConfiguration(agentId.value, {
      system_prompt: systemPromptText.value,
      model: modelText.value,
      prompt_template: promptTemplateText.value,
      model_adapter: modelAdapter.value,
      runtime_type: runtimeType.value,
      runtime_id: runtimeId.value,
      runtime_config: JSON.parse(runtimeConfigText.value) as Record<string, unknown>,
      capability_profile: JSON.parse(capabilityProfileText.value) as {
        workspace_type: 'document' | 'repository'
        required_tools: string[]
        artifact_types: string[]
      },
      model_config: JSON.parse(modelConfigText.value) as Record<string, unknown>,
    })
    message.success('Prompt 与模型配置已保存')
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { configurationSaving.value = false }
}

watch(modelText, () => {
  if (selectedModel.value) modelAdapter.value = selectedModel.value.adapter
})

watch(runtimeType, (runtimeTypeValue, previous) => {
  if (hydratingConfiguration) return
  if (selectedRuntime.value?.type !== runtimeTypeValue) runtimeId.value = null
  const candidate = runtimes.value.find((runtime) => runtime.type === runtimeTypeValue && runtime.status === 'online')
  if (candidate) runtimeId.value = candidate.id
  if (runtimeTypeValue === 'deepseek') {
    capabilityProfileText.value = JSON.stringify({
      workspace_type: 'repository',
      required_tools: [],
      artifact_types: ['code_patch', 'git_diff', 'test_report'],
    }, null, 2)
  } else if (previous === 'deepseek') {
    capabilityProfileText.value = JSON.stringify({
      workspace_type: 'document',
      required_tools: [],
      artifact_types: ['text', 'json', 'markdown', 'pdf', 'xlsx'],
    }, null, 2)
  }
}, { flush: 'sync' })

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
  <div class="agent-detail-page">
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
      <div><span>Version</span><strong class="mono">{{ displayedVersion || '未发布' }} · {{ displayedVersionState }}</strong></div>
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
        'detail-tab-main': ['versions', 'execution'].includes(activeTab),
      }"
    >
      <div class="detail-stack">
        <AgentConversationPanel
          v-if="activeTab === 'execution'"
          :executions="executions"
          :loading="executionHistoryLoading"
          :history-error="executionHistoryError"
          :agent-name="agentStore.currentAgent.name"
          @refresh="loadExecutionHistory"
          @open-trace="router.push({ name: 'trace-detail', params: { id: $event } })"
        />
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
            <div class="definition-item"><dt>Current Version</dt><dd class="mono">{{ displayedVersion || '未发布' }} · {{ displayedVersionState }}</dd></div>
            <div class="definition-item"><dt>创建时间</dt><dd>{{ formatDate(agentStore.currentAgent.created_at) }}</dd></div>
            <div class="definition-item"><dt>更新时间</dt><dd>{{ formatDate(agentStore.currentAgent.updated_at) }}</dd></div>
            <div class="definition-item"><dt>最近执行</dt><dd>{{ lastExecution ? formatDate(lastExecution.started_at) : '暂无执行' }}</dd></div>
            <div class="definition-item"><dt>成功率</dt><dd>{{ successRate }}</dd></div>
          </dl>
        </section>

        <section v-show="activeTab === 'configuration'" class="surface panel">
          <div class="section-heading">
            <div><h2>能力与资源</h2><p>为 Development Version 选择 Capability、工具别名、Scope 和调用配额</p></div>
            <div class="resource-actions">
              <StatusTag :status="editorModel?.preflight.state || 'NEEDS_CONFIGURATION'" />
              <NButton v-if="capabilityBindingEditable" size="small" type="primary" secondary @click="openCapabilityBindingEditor"><template #icon><NIcon :component="Edit" /></template>编辑能力绑定</NButton>
              <NButton v-else size="small" secondary :loading="versionSaving" :disabled="agentStore.currentAgent?.status === 'archived'" @click="createVersion">创建 Development Version</NButton>
            </div>
          </div>
          <NAlert v-if="!capabilityBindingEditable" type="info" :bordered="false" style="margin-bottom:14px">已发布 Agent 的能力绑定不可原地修改。创建 Development Version 后选择能力，测试并重新发布才会影响新执行。</NAlert>
          <div v-if="editorModel?.sections.capabilities.length" class="binding-list" style="margin-top:14px">
            <div v-for="item in editorModel.sections.capabilities" :key="item.binding_id" class="binding-row">
              <div>
                <strong class="mono">{{ item.tool_alias }}</strong>
                <span>{{ item.label }} · {{ item.key }}@{{ item.version }} · {{ item.source_label }}</span>
                <span>{{ item.connection_name || '通用连接' }} · {{ item.database || '无固定数据库' }} · {{ item.scope_name || item.scope_summary }}</span>
              </div>
              <StatusTag :status="item.state" style="margin-left:auto" />
            </div>
          </div>
          <div v-else class="version-empty">当前 Agent 没有 Capability Binding。不需要外部接口的 Agent 可以保持为空。</div>
          <div v-if="editorModel?.preflight.issues.length" class="binding-list" style="margin-top:14px">
            <div v-for="issue in editorModel.preflight.issues" :key="`${issue.code}-${issue.path}`" class="binding-row"><div><strong>{{ issue.message }}</strong><span class="mono">{{ issue.code }} / {{ issue.path }}</span></div></div>
          </div>
          <NButton style="margin-top:14px" secondary @click="router.push({ name: 'platform-connections' })">打开连接与能力管理</NButton>
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
            <NFormItem label="模型"><NSelect v-model:value="modelText" filterable :disabled="configurationLocked" :options="modelOptions" placeholder="从模型管理选择" /></NFormItem>
            <NFormItem label="Provider / Adapter"><NInput :value="selectedModel ? `${selectedModel.provider} / ${selectedModel.adapter}` : modelAdapter" disabled /></NFormItem>
            <NFormItem label="Agent Runtime"><NSelect v-model:value="runtimeType" :disabled="configurationLocked" :options="runtimeTypeOptions" /></NFormItem>
            <NFormItem label="Runtime 实例"><NSelect v-model:value="runtimeId" clearable :disabled="configurationLocked" :options="runtimeOptions" :placeholder="runtimeType === 'deepseek' ? 'DeepSeek 必须选择在线实例' : '可使用类型默认端点'" /></NFormItem>
            <NFormItem class="span-2" label="Model Config JSON"><NInput v-model:value="modelConfigText" type="textarea" :rows="4" class="mono" :disabled="configurationLocked" /></NFormItem>
            <NFormItem class="span-2" label="Runtime Config JSON"><NInput v-model:value="runtimeConfigText" type="textarea" :rows="4" class="mono" :disabled="configurationLocked" placeholder='{"timeout_seconds":900}' /></NFormItem>
            <NFormItem class="span-2" label="Capability Profile JSON"><NInput v-model:value="capabilityProfileText" type="textarea" :rows="6" class="mono" :disabled="configurationLocked" /></NFormItem>
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
        <section v-show="activeTab === 'execution'" class="surface panel">
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
        <section v-show="activeTab === 'execution'" class="surface panel">
          <div class="section-heading"><div><h2>Agent Artifacts</h2><p>{{ artifacts.length }} 个已登记产物</p></div><NButton text type="primary" @click="router.push({ name: 'artifacts' })">打开产物中心</NButton></div>
          <div v-if="phase3Loading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
          <div v-else-if="artifacts.length" class="artifact-list">
            <a v-for="artifact in artifacts" :key="artifact.id" class="artifact-row" :href="platformApi.artifactDownloadUrl(artifact.id)">
              <NIcon :component="Api" size="18" />
              <div><strong>{{ artifact.filename }}</strong><span class="mono">{{ artifact.artifact_type }} · {{ artifact.runtime_source }} · {{ artifact.content_type }} · {{ artifact.size_bytes }} bytes</span><span class="mono">SHA-256 {{ artifact.sha256 }}</span></div>
            </a>
          </div>
          <div v-else class="empty-state empty-state-compact"><div><h3>尚无 Artifact</h3><p>Agent 产生文件后，会显示在这里并支持受控下载。</p></div></div>
        </section>
        <section v-show="activeTab === 'execution'" class="surface panel">
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
      v-model:show="capabilityBindingOpen"
      preset="card"
      title="编辑 Agent 能力绑定"
      style="width: min(1080px, calc(100vw - 32px))"
      :mask-closable="!capabilityBindingSaving"
    >
      <div v-if="capabilityBindingLoading" class="loading-stack"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
      <template v-else>
        <NAlert type="info" :bordered="false">这里只修改当前 Development Version。Skill / Workflow 自动绑定和数据库专用绑定会保留，不会被本次保存删除。</NAlert>
        <NFormItem label="选择已发布 Capability" style="margin-top:16px">
          <NSelect :value="selectedCapabilityVersionIds" multiple filterable clearable :options="capabilityCatalogOptions" placeholder="选择 Agent 可调用的能力" @update:value="syncCapabilitySelection" />
        </NFormItem>
        <div v-if="editableCapabilityBindings.length" class="capability-binding-editor-list">
          <article v-for="binding in editableCapabilityBindings" :key="binding.capability_version_id" class="surface">
            <header><div><strong>{{ binding.label }}</strong><span class="mono">{{ binding.key }}@{{ binding.version }}</span></div><StatusTag status="READY" /></header>
            <div class="form-grid">
              <NFormItem label="Tool Alias" required><NInput v-model:value="binding.tool_alias" /></NFormItem>
              <NFormItem label="Resource Scope"><NSelect v-model:value="binding.resource_scope_revision_id" clearable filterable :options="capabilityScopeOptions" placeholder="无资源隔离时可留空" /></NFormItem>
              <NFormItem label="每次执行最多调用"><NInputNumber v-model:value="binding.quota_policy.calls_per_execution" :min="1" :max="10000" /></NFormItem>
              <NFormItem label="每分钟最多调用"><NInputNumber v-model:value="binding.quota_policy.calls_per_minute" :min="1" :max="10000" /></NFormItem>
              <NFormItem label="最大并发"><NInputNumber v-model:value="binding.quota_policy.max_concurrency" :min="1" :max="100" /></NFormItem>
            </div>
          </article>
        </div>
        <div v-else class="empty-state empty-state-compact"><div><h3>当前不绑定通用 Capability</h3><p>无外部能力的 Agent 可以保持为空。数据库能力使用独立数据库 Scope 绑定。</p></div></div>
      </template>
      <template #footer><div class="dialog-actions"><NButton @click="capabilityBindingOpen = false">取消</NButton><NButton type="primary" :loading="capabilityBindingSaving" :disabled="capabilityBindingLoading" @click="saveAgentCapabilityBindings">保存并执行 Preflight</NButton></div></template>
    </NModal>

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
