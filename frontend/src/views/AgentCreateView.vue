<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowLeft, ArrowRight, DeviceFloppy, PlayerPlay, Plus, Rocket, Trash } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useAgentStore } from '@/stores/agents'
import { useManagementStore } from '@/stores/management'
import { useResourceStore } from '@/stores/resources'
import type { AgentCreatePayload, AgentRuntime, AgentType, CapabilityCatalogItem, CapabilityResolution, DatabaseAvailableBinding, DatabaseOperation, ModelAdapterName, RegisteredModel, ResourceScopeRecord, ResponseMode, RuntimeType, WorkspaceType } from '@/types/api'

const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const resources = useResourceStore()
const management = useManagementStore()
const step = ref(0)
const saving = ref(false)
const testing = ref(false)
const publishing = ref(false)
const createdAgentId = ref<string | null>(null)
const runtimes = ref<AgentRuntime[]>([])
const models = ref<RegisteredModel[]>([])
const capabilities = ref<CapabilityCatalogItem[]>([])
const scopes = ref<ResourceScopeRecord[]>([])
const databaseConnections = ref<DatabaseAvailableBinding[]>([])
const preflight = ref<CapabilityResolution | null>(null)
const testResult = ref<string | null>(null)
const testInput = ref('请根据已配置的能力完成一次最小测试。')
interface DatabaseBindingDraft { scope_revision_id: string | null; tool_prefix: string; operations: DatabaseOperation[] }

const steps = [
  { title: '定义 Agent', note: '名称、职责和系统指令' },
  { title: '设置行为', note: 'Runtime、模型、Skill 和执行模式' },
  { title: '能力与资源', note: '选择 Capability 和数据范围' },
  { title: '测试并发布', note: '以后端 Preflight 结果为准' },
]

const form = reactive({
  id: '', name: '', description: '', agent_type: 'worker' as AgentType,
  role: '', system_prompt: '', model: '', model_adapter: 'hermes' as ModelAdapterName,
  runtime_type: 'hermes' as RuntimeType, runtime_id: null as string | null,
  workspace_type: 'document' as WorkspaceType, response_mode: 'sync' as ResponseMode,
  execution_mode: 'autonomous' as 'autonomous' | 'workflow' | 'hybrid',
  skill_ids: [] as string[], capability_version_ids: [] as string[], scope_revision_id: null as string | null,
  database_bindings: [] as DatabaseBindingDraft[],
})

const idPattern = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/
const modelOptions = computed(() => models.value.filter((item) => item.is_enabled).map((item) => ({ label: `${item.display_name} / ${item.provider}`, value: item.id })))
const runtimeOptions = computed(() => runtimes.value.filter((item) => item.type === form.runtime_type && item.status !== 'disabled').map((item) => ({ label: `${item.name} / ${item.version} / ${item.status}`, value: item.id })))
const skillOptions = computed(() => resources.skills.map((item) => ({ label: `${item.name} / v${item.version}`, value: item.id, disabled: !item.runtime_support.includes(form.runtime_type) })))
const capabilityOptions = computed(() => capabilities.value.filter((item) => !item.key.startsWith('database.')).map((item) => ({ label: `${item.label} / ${item.key}@${item.version}`, value: item.id })))
const scopeOptions = computed(() => scopes.value.filter((item) => item.resource_type !== 'postgresql_database').map((item) => ({ label: `${item.name} / ${item.resource_type}`, value: item.current_revision_id, disabled: !item.current_revision_id })))
const databaseScopeOptions = computed(() => databaseConnections.value.map((item) => ({
  label: `${item.connection_name} / ${item.database} / ${item.scope_name}`,
  value: item.scope_revision_id,
  disabled: item.status !== 'READY',
})))
const databaseOperationOptions = [
  { label: '列出 Schema', value: 'list_schemas' }, { label: '列出表与视图', value: 'list_tables' },
  { label: '查看表结构', value: 'describe_table' }, { label: '预览表', value: 'preview_table' },
  { label: '只读查询', value: 'select' }, { label: '查询计划', value: 'explain' },
]

function warn(value: string): false { message.warning(value); return false }

function addDatabaseBinding() {
  form.database_bindings.push({
    scope_revision_id: null,
    tool_prefix: `business_db${form.database_bindings.length ? form.database_bindings.length + 1 : ''}`,
    operations: ['list_schemas', 'list_tables', 'describe_table', 'preview_table', 'select', 'explain'],
  })
}

function removeDatabaseBinding(index: number) { form.database_bindings.splice(index, 1) }

function databaseBindingInfo(scopeRevisionId: string | null): DatabaseAvailableBinding | undefined {
  return databaseConnections.value.find((item) => item.scope_revision_id === scopeRevisionId)
}

function validateCurrent(index = step.value): boolean {
  if (index === 0) {
    if (!idPattern.test(form.id)) return warn('Agent ID 需为 3-64 位小写字母、数字或连字符')
    if (!form.name.trim() || !form.role.trim() || !form.system_prompt.trim()) return warn('名称、职责和系统指令必须填写')
  }
  if (index === 1) {
    if (!form.model || !form.runtime_id) return warn('请选择已启用模型和在线 Runtime')
    if (form.runtime_type === 'deepseek' && form.workspace_type !== 'repository') return warn('DeepSeek Harness 必须使用代码仓库工作区')
  }
  if (index === 2) {
    const scopes = new Set<string>()
    const aliases = new Set<string>()
    for (const binding of form.database_bindings) {
      if (!binding.scope_revision_id) return warn('每个数据库绑定都必须选择数据库 Scope')
      if (scopes.has(binding.scope_revision_id)) return warn('同一个数据库 Scope 不能重复绑定')
      scopes.add(binding.scope_revision_id)
      if (!/^[a-z][a-z0-9_]{0,95}$/.test(binding.tool_prefix)) return warn('数据库工具前缀只能使用小写字母、数字和下划线')
      if (!binding.operations.length) return warn('绑定数据库时至少选择一个数据库工具')
      for (const operation of binding.operations) {
        const alias = `${binding.tool_prefix}_${operation}`
        if (aliases.has(alias) || alias.length > 128) return warn(`数据库工具别名冲突或过长：${alias}`)
        aliases.add(alias)
      }
    }
  }
  return true
}

async function next() {
  if (!validateCurrent()) return
  if (step.value === 1) return initializeDraft()
  if (step.value === 2) return prepareDraft()
  step.value = Math.min(3, step.value + 1)
}

async function createDevelopmentDraft() {
  if (createdAgentId.value) return
  const payload: AgentCreatePayload = {
    id: form.id, name: form.name.trim(), description: form.description.trim() || null,
    agent_type: form.agent_type, role: form.role.trim(), system_prompt: form.system_prompt,
    model_config: {}, model: form.model, model_adapter: form.model_adapter,
    runtime_type: form.runtime_type, runtime_id: form.runtime_id, runtime_config: {},
    capability_profile: {
      workspace_type: form.workspace_type, required_tools: [],
      artifact_types: form.runtime_type === 'deepseek' ? ['code_patch', 'git_diff', 'test_report'] : ['text', 'json', 'markdown', 'pdf', 'xlsx'],
    },
    prompt_template: '{{input}}', status: 'active', response_mode: form.response_mode,
    input_schema: { type: 'object', properties: {}, additionalProperties: true }, output_schema: {},
  }
  const result = await agentStore.createAgentWorkflow({ agent: payload, skillIds: form.skill_ids, mcpIds: [] })
  createdAgentId.value = result.agent.id
  await platformApi.updateAgentEditorSection(createdAgentId.value, 'behavior', {
    runtime_type: form.runtime_type, runtime_id: form.runtime_id, model: form.model,
    model_adapter: form.model_adapter, response_mode: form.response_mode, execution_mode: form.execution_mode,
  }, management.key)
}

async function initializeDraft() {
  if (!management.unlocked) return warn('请先使用页面右上角的管理员解锁功能')
  saving.value = true
  try {
    await createDevelopmentDraft()
    const available = await platformApi.getAvailableComponents(createdAgentId.value as string)
    databaseConnections.value = available.database_connections
    step.value = 2
    message.success('Development Draft 已创建，请配置能力与数据库范围')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally { saving.value = false }
}

async function prepareDraft() {
  if (!management.unlocked) return warn('请先使用页面右上角的管理员解锁功能')
  saving.value = true
  try {
    await createDevelopmentDraft()
    const agentId = createdAgentId.value
    if (!agentId) throw new Error('Development Draft 创建失败')
    const selected = capabilities.value.filter((item) => form.capability_version_ids.includes(item.id))
    await platformApi.updateCapabilityBindings(agentId, selected.map((item) => ({
      tool_alias: item.key.replaceAll('.', '_').replaceAll('-', '_'),
      capability_version_id: item.id, implementation_mode: 'DEFAULT_PRIORITY',
      resource_scope_revision_id: form.scope_revision_id, parameter_policy: {},
      quota_policy: { calls_per_execution: 20, max_concurrency: 2, calls_per_minute: 60 },
      approval_policy: {}, source_type: 'direct',
    })), management.key)
    await platformApi.updateDatabaseBindings(
      agentId,
      form.database_bindings.map((item) => ({
        scope_revision_id: item.scope_revision_id as string,
        tool_prefix: item.tool_prefix,
        operations: item.operations,
      })),
      management.key,
    )
    preflight.value = await platformApi.preflightAgent(agentId)
    step.value = 3
    message.success('Agent Draft 已保存，Preflight 已完成')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally { saving.value = false }
}

async function runTest() {
  if (!createdAgentId.value || preflight.value?.state !== 'READY') return
  testing.value = true
  testResult.value = null
  try {
    const result = await platformApi.testAgentDraft(createdAgentId.value, { input: testInput.value, session_id: `builder-${Date.now()}`, parameters: {} }, management.key)
    testResult.value = result.output
    message.success('测试执行完成')
  } catch (cause) { message.error(getApiErrorMessage(cause), { duration: 8000 }) }
  finally { testing.value = false }
}

async function publish() {
  if (!createdAgentId.value || preflight.value?.state !== 'READY') return
  publishing.value = true
  try {
    const result = await platformApi.publishAgentDraft(createdAgentId.value, management.key)
    message.success(`${result.version} 已发布`)
    await router.push({ name: 'agent-detail', params: { id: createdAgentId.value } })
  } catch (cause) { message.error(getApiErrorMessage(cause), { duration: 8000 }) }
  finally { publishing.value = false }
}

watch(() => form.model, () => {
  const selected = models.value.find((item) => item.id === form.model)
  if (selected) form.model_adapter = selected.adapter
})
watch(() => form.runtime_type, (value) => {
  form.runtime_id = runtimes.value.find((item) => item.type === value && item.status === 'online')?.id || null
  form.workspace_type = value === 'deepseek' ? 'repository' : 'document'
  form.skill_ids = form.skill_ids.filter((id) => resources.skills.find((item) => item.id === id)?.runtime_support.includes(value))
})

onMounted(async () => {
  await resources.fetchAll().catch(() => undefined)
  const [runtimeValues, modelValues, scopeValues, capabilityValues] = await Promise.all([
    platformApi.listRuntimes(), platformApi.listModels(true), platformApi.listResourceScopes(), platformApi.listCapabilityCatalogGlobal(),
  ])
  runtimes.value = runtimeValues; models.value = modelValues; scopes.value = scopeValues
  const selectedModel = modelValues.find((item) => item.is_default) || modelValues[0]
  if (selectedModel) form.model = selectedModel.id
  form.runtime_id = runtimeValues.find((item) => item.type === form.runtime_type && item.status === 'online')?.id || null
  capabilities.value = capabilityValues
})
</script>

<template>
  <div>
    <PageHeader title="创建 Agent" description="四步完成定义、行为、能力配置和发布检查。"><template #actions><NButton @click="router.push({ name: 'agents' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回列表</NButton></template></PageHeader>
    <NAlert v-if="!management.unlocked" type="warning" :bordered="false" style="margin-bottom:16px">当前为只读模式。创建 Agent 前请先在右上角解锁管理员模式。</NAlert>
    <nav class="wizard-steps" aria-label="Agent 创建步骤"><button v-for="(item,index) in steps" :key="item.title" type="button" :class="{active:index===step,complete:index<step}" :disabled="index>step || Boolean(createdAgentId)" @click="index<=step && !createdAgentId && (step=index)"><span>{{ index<step ? '✓' : index+1 }}</span><div><strong>{{ item.title }}</strong><small>{{ item.note }}</small></div></button></nav>
    <section class="surface wizard-panel">
      <div class="wizard-heading"><span>步骤 {{ step+1 }} / 4</span><h2>{{ steps[step].title }}</h2><p>{{ steps[step].note }}</p></div>
      <NForm label-placement="top" @submit.prevent="next">
        <template v-if="step===0"><div class="form-grid"><NFormItem label="Agent ID" required><NInput v-model:value="form.id" :disabled="Boolean(createdAgentId)" placeholder="knowledge-analyst" /></NFormItem><NFormItem label="名称" required><NInput v-model:value="form.name" /></NFormItem><NFormItem label="Agent 类型"><NSelect v-model:value="form.agent_type" :options="[{label:'Manager',value:'manager'},{label:'Worker',value:'worker'}]" /></NFormItem><NFormItem label="职责" required><NInput v-model:value="form.role" /></NFormItem><NFormItem class="span-2" label="描述"><NInput v-model:value="form.description" type="textarea" /></NFormItem></div><NFormItem label="系统指令" required><NInput v-model:value="form.system_prompt" type="textarea" :rows="10" /></NFormItem></template>
        <template v-else-if="step===1"><div class="form-grid"><NFormItem label="Runtime"><NSelect v-model:value="form.runtime_type" :options="[{label:'Hermes',value:'hermes'},{label:'Pi',value:'pi'},{label:'DeepSeek Harness',value:'deepseek'}]" /></NFormItem><NFormItem label="Runtime 实例" required><NSelect v-model:value="form.runtime_id" :options="runtimeOptions" /></NFormItem><NFormItem label="模型" required><NSelect v-model:value="form.model" filterable :options="modelOptions" /></NFormItem><NFormItem label="执行模式"><NSelect v-model:value="form.execution_mode" :options="[{label:'自主',value:'autonomous'},{label:'Workflow',value:'workflow'},{label:'混合',value:'hybrid'}]" /></NFormItem><NFormItem label="工作区"><NSelect v-model:value="form.workspace_type" :options="[{label:'文档',value:'document',disabled:form.runtime_type==='deepseek'},{label:'代码仓库',value:'repository'}]" /></NFormItem><NFormItem label="响应模式"><NSelect v-model:value="form.response_mode" :options="[{label:'同步 JSON',value:'sync'},{label:'流式 SSE',value:'stream'}]" /></NFormItem><NFormItem class="span-2" label="Skill"><NSelect v-model:value="form.skill_ids" multiple filterable :options="skillOptions" placeholder="可选，Skill 会声明所需能力" /></NFormItem></div></template>
        <template v-else-if="step===2"><NFormItem label="Capability"><NSelect v-model:value="form.capability_version_ids" multiple filterable :options="capabilityOptions" placeholder="不需要外部能力时可留空" /></NFormItem><NFormItem label="通用资源范围"><NSelect v-model:value="form.scope_revision_id" clearable :options="scopeOptions" placeholder="需要数据隔离时选择固定 Revision" /></NFormItem><div class="database-binding-card"><div class="database-binding-heading"><div><strong>数据库访问</strong><span>每个绑定固定到一个 PostgreSQL 数据库 Scope；一个 Agent 可以绑定多个数据库，但不能在任务中切换物理地址。</span></div><NButton size="small" secondary :disabled="!databaseConnections.some(item=>item.status==='READY')" @click="addDatabaseBinding"><template #icon><NIcon :component="Plus" /></template>添加数据库</NButton></div><div v-if="!databaseConnections.some(item=>item.status==='READY')" class="database-binding-empty">当前没有 READY 的数据库 Scope，请先在“平台管理 → 数据库连接”完成连接测试和范围配置。</div><div v-else-if="!form.database_bindings.length" class="database-binding-empty">当前 Agent 不访问数据库。</div><article v-for="(binding,index) in form.database_bindings" :key="index" class="database-binding-item"><header><strong>数据库绑定 {{ index + 1 }}</strong><NButton quaternary type="error" size="small" @click="removeDatabaseBinding(index)"><template #icon><NIcon :component="Trash" /></template>移除</NButton></header><NFormItem label="数据库 Scope" required><NSelect v-model:value="binding.scope_revision_id" filterable :options="databaseScopeOptions" placeholder="选择固定数据库 Scope" /></NFormItem><div v-if="databaseBindingInfo(binding.scope_revision_id)" class="database-scope-preview"><strong>{{ databaseBindingInfo(binding.scope_revision_id)?.connection_name }} / {{ databaseBindingInfo(binding.scope_revision_id)?.database }}</strong><span>{{ Object.keys(databaseBindingInfo(binding.scope_revision_id)?.schemas || {}).join('、') }} · 最大 {{ databaseBindingInfo(binding.scope_revision_id)?.limits.max_rows }} 行 · {{ databaseBindingInfo(binding.scope_revision_id)?.limits.statement_timeout_ms }} ms</span></div><div class="form-grid"><NFormItem label="工具别名前缀" required><NInput v-model:value="binding.tool_prefix" placeholder="business_db" /></NFormItem><NFormItem label="允许的数据库工具" required><NSelect v-model:value="binding.operations" multiple :options="databaseOperationOptions" /></NFormItem></div></article></div><NAlert type="info" :bordered="false">Endpoint、数据库名、用户名、密码和 Scope ID 都由平台注入，模型只看到工具别名和业务参数。</NAlert></template>
        <template v-else><NAlert :type="preflight?.state==='READY' ? 'success' : 'warning'" :bordered="false" style="margin-bottom:16px">{{ preflight?.state==='READY' ? '发布检查通过，可以测试和发布。' : '发布检查未通过，请处理下列问题。' }}</NAlert><div v-if="preflight?.issues.length" class="preflight-list"><div v-for="item in preflight.issues" :key="`${item.code}-${item.path}`"><strong>{{ item.message }}</strong><span class="mono">{{ item.code }} / {{ item.path }}</span></div></div><NFormItem label="测试输入"><NInput v-model:value="testInput" type="textarea" :rows="5" /></NFormItem><div v-if="testResult" class="result-preview"><strong>测试输出</strong><pre>{{ testResult }}</pre></div></template>
      </NForm>
      <footer class="wizard-footer"><NButton v-if="step>0 && !createdAgentId" @click="step-=1">上一步</NButton><span /><NButton v-if="step<3" type="primary" :loading="saving" @click="next"><template #icon><NIcon :component="step===2 ? DeviceFloppy : ArrowRight" /></template>{{ step===2 ? '保存并检查' : '下一步' }}</NButton><template v-else><NButton :disabled="preflight?.state!=='READY'" :loading="testing" @click="runTest"><template #icon><NIcon :component="PlayerPlay" /></template>测试运行</NButton><NButton type="primary" :disabled="preflight?.state!=='READY'" :loading="publishing" @click="publish"><template #icon><NIcon :component="Rocket" /></template>发布 Agent</NButton></template></footer>
    </section>
  </div>
</template>

<style scoped>
.preflight-list{display:grid;gap:8px;margin-bottom:16px}.preflight-list>div{display:grid;gap:4px;padding:12px;border:1px solid var(--line);border-radius:8px}.preflight-list span{color:var(--muted);font-size:11px}.result-preview{margin:14px 0;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.result-preview pre{overflow:auto;max-height:360px;white-space:pre-wrap}.wizard-footer{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:22px}.wizard-footer>span{flex:1}
.database-binding-card{display:grid;gap:12px;margin:14px 0;padding:16px;border:1px solid var(--line);border-radius:9px;background:var(--surface-subtle)}.database-binding-heading,.database-binding-item>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.database-binding-heading>div{display:grid;gap:4px}.database-binding-card span{color:var(--muted);font-size:12px}.database-binding-empty{padding:18px;border:1px dashed var(--line);border-radius:8px;color:var(--muted);text-align:center}.database-binding-item{padding:14px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.database-binding-item>header{margin-bottom:10px}.database-scope-preview{display:grid;gap:4px;margin:-2px 0 14px;padding:10px 12px;border-left:2px solid var(--accent);background:var(--accent-soft)}
</style>
