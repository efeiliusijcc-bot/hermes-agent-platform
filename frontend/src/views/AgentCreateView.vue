<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowLeft, ArrowRight, DeviceFloppy, PlayerPlay, Rocket } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useAgentStore } from '@/stores/agents'
import { useManagementStore } from '@/stores/management'
import { useResourceStore } from '@/stores/resources'
import type { AgentCreatePayload, AgentRuntime, AgentType, CapabilityCatalogItem, CapabilityResolution, ModelAdapterName, RegisteredModel, ResourceScopeRecord, ResponseMode, RuntimeType, WorkspaceType } from '@/types/api'

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
const preflight = ref<CapabilityResolution | null>(null)
const testResult = ref<string | null>(null)
const testInput = ref('请根据已配置的能力完成一次最小测试。')

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
})

const idPattern = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/
const modelOptions = computed(() => models.value.filter((item) => item.is_enabled).map((item) => ({ label: `${item.display_name} / ${item.provider}`, value: item.id })))
const runtimeOptions = computed(() => runtimes.value.filter((item) => item.type === form.runtime_type && item.status !== 'disabled').map((item) => ({ label: `${item.name} / ${item.version} / ${item.status}`, value: item.id })))
const skillOptions = computed(() => resources.skills.map((item) => ({ label: `${item.name} / v${item.version}`, value: item.id, disabled: !item.runtime_support.includes(form.runtime_type) })))
const capabilityOptions = computed(() => capabilities.value.map((item) => ({ label: `${item.label} / ${item.key}@${item.version}`, value: item.id })))
const scopeOptions = computed(() => scopes.value.map((item) => ({ label: `${item.name} / ${item.resource_type}`, value: item.current_revision_id, disabled: !item.current_revision_id })))

function warn(value: string): false { message.warning(value); return false }

function validateCurrent(index = step.value): boolean {
  if (index === 0) {
    if (!idPattern.test(form.id)) return warn('Agent ID 需为 3-64 位小写字母、数字或连字符')
    if (!form.name.trim() || !form.role.trim() || !form.system_prompt.trim()) return warn('名称、职责和系统指令必须填写')
  }
  if (index === 1) {
    if (!form.model || !form.runtime_id) return warn('请选择已启用模型和在线 Runtime')
    if (form.runtime_type === 'deepseek' && form.workspace_type !== 'repository') return warn('DeepSeek Harness 必须使用代码仓库工作区')
  }
  return true
}

async function next() {
  if (!validateCurrent()) return
  if (step.value === 2) return prepareDraft()
  step.value = Math.min(3, step.value + 1)
}

async function prepareDraft() {
  if (!management.unlocked) return warn('请先使用页面右上角的管理员解锁功能')
  saving.value = true
  try {
    if (!createdAgentId.value) {
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
    }
    await platformApi.updateAgentEditorSection(createdAgentId.value, 'behavior', {
      runtime_type: form.runtime_type, runtime_id: form.runtime_id, model: form.model,
      model_adapter: form.model_adapter, response_mode: form.response_mode, execution_mode: form.execution_mode,
    }, management.key)
    const selected = capabilities.value.filter((item) => form.capability_version_ids.includes(item.id))
    await platformApi.updateCapabilityBindings(createdAgentId.value, selected.map((item) => ({
      tool_alias: item.key.replaceAll('.', '_').replaceAll('-', '_'),
      capability_version_id: item.id, implementation_mode: 'DEFAULT_PRIORITY',
      resource_scope_revision_id: form.scope_revision_id, parameter_policy: {},
      quota_policy: { calls_per_execution: 20, max_concurrency: 2, calls_per_minute: 60 },
      approval_policy: {}, source_type: 'direct',
    })), management.key)
    preflight.value = await platformApi.preflightAgent(createdAgentId.value)
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
        <template v-else-if="step===2"><NFormItem label="Capability"><NSelect v-model:value="form.capability_version_ids" multiple filterable :options="capabilityOptions" placeholder="不需要外部能力时可留空" /></NFormItem><NFormItem label="资源范围"><NSelect v-model:value="form.scope_revision_id" clearable :options="scopeOptions" placeholder="需要数据隔离时选择固定 Revision" /></NFormItem><NAlert type="info" :bordered="false">Skill 与真实接口解耦。Endpoint、凭据和 Scope 都由 Gateway 注入，模型无法看到。</NAlert></template>
        <template v-else><NAlert :type="preflight?.state==='READY' ? 'success' : 'warning'" :bordered="false" style="margin-bottom:16px">{{ preflight?.state==='READY' ? '发布检查通过，可以测试和发布。' : '发布检查未通过，请处理下列问题。' }}</NAlert><div v-if="preflight?.issues.length" class="preflight-list"><div v-for="item in preflight.issues" :key="`${item.code}-${item.path}`"><strong>{{ item.message }}</strong><span class="mono">{{ item.code }} / {{ item.path }}</span></div></div><NFormItem label="测试输入"><NInput v-model:value="testInput" type="textarea" :rows="5" /></NFormItem><div v-if="testResult" class="result-preview"><strong>测试输出</strong><pre>{{ testResult }}</pre></div></template>
      </NForm>
      <footer class="wizard-footer"><NButton v-if="step>0 && !createdAgentId" @click="step-=1">上一步</NButton><span /><NButton v-if="step<3" type="primary" :loading="saving" @click="next"><template #icon><NIcon :component="step===2 ? DeviceFloppy : ArrowRight" /></template>{{ step===2 ? '保存并检查' : '下一步' }}</NButton><template v-else><NButton :disabled="preflight?.state!=='READY'" :loading="testing" @click="runTest"><template #icon><NIcon :component="PlayerPlay" /></template>测试运行</NButton><NButton type="primary" :disabled="preflight?.state!=='READY'" :loading="publishing" @click="publish"><template #icon><NIcon :component="Rocket" /></template>发布 Agent</NButton></template></footer>
    </section>
  </div>
</template>

<style scoped>
.preflight-list{display:grid;gap:8px;margin-bottom:16px}.preflight-list>div{display:grid;gap:4px;padding:12px;border:1px solid var(--line);border-radius:8px}.preflight-list span{color:var(--muted);font-size:11px}.result-preview{margin:14px 0;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.result-preview pre{overflow:auto;max-height:360px;white-space:pre-wrap}.wizard-footer{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:22px}.wizard-footer>span{flex:1}
</style>
