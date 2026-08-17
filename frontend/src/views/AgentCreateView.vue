<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowLeft, ArrowRight, Check, DeviceFloppy } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import type { Agent, AgentCreatePayload, AgentLifecycleStatus, AgentRuntime, AgentType, ModelAdapterName, RegisteredModel, ResponseMode, RuntimeType } from '@/types/api'

const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const submitting = ref(false)
const step = ref(0)
const existingAgents = ref<Agent[]>([])
const runtimes = ref<AgentRuntime[]>([])
const models = ref<RegisteredModel[]>([])

const steps = [
  { title: '基础信息', note: '名称、标识与职责' },
  { title: 'Model', note: '模型和运行参数' },
  { title: 'Skills', note: '绑定受控技能' },
  { title: 'MCP', note: '绑定只读工具' },
  { title: 'Schema', note: '输入输出契约' },
  { title: 'Review', note: '核对并创建' },
]

interface FormModel {
  id: string
  name: string
  description: string
  agent_type: AgentType
  parent_agent_id: string | null
  role: string
  system_prompt: string
  model: string
  model_adapter: ModelAdapterName
  runtime_type: RuntimeType
  runtime_id: string | null
  prompt_template: string
  temperature: number
  status: AgentLifecycleStatus
  response_mode: ResponseMode
  skillIds: string[]
  mcpIds: string[]
  inputSchema: string
  outputSchema: string
}

const form = reactive<FormModel>({
  id: '', name: '', description: '', agent_type: 'worker', parent_agent_id: null, role: '', system_prompt: '',
  model: '', model_adapter: 'hermes', runtime_type: 'hermes', runtime_id: null, prompt_template: '{{input}}', temperature: 0.1,
  status: 'active', response_mode: 'sync', skillIds: [], mcpIds: [],
  inputSchema: '{\n  "type": "object",\n  "properties": {}\n}',
  outputSchema: '{\n  "type": "object",\n  "properties": {}\n}',
})

const idPattern = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/
const skillOptions = computed(() => resourceStore.skills.map((skill) => ({
  label: `${skill.name} · v${skill.version} · ${skill.runtime_support.join('/')}`,
  value: skill.id,
  disabled: !skill.runtime_support.includes(form.runtime_type),
})))
const runtimeOptions = computed(() => runtimes.value
  .filter((runtime) => runtime.type === form.runtime_type && runtime.status !== 'disabled')
  .map((runtime) => ({
    label: `${runtime.name} · ${runtime.version} · ${runtime.status}`,
    value: runtime.id,
  })))
const selectedRuntime = computed(() => runtimes.value.find((item) => item.id === form.runtime_id) || null)
const selectedModel = computed(() => models.value.find((item) => item.id === form.model) || null)
const modelOptions = computed(() => models.value
  .filter((item) => item.is_enabled)
  .map((item) => ({
    label: `${item.display_name} · ${item.provider}${item.is_default ? ' · 默认' : ''}`,
    value: item.id,
  })))
const mcpOptions = computed(() => resourceStore.mcpServers.map((server) => ({ label: `${server.name} · ${server.config.kind}`, value: server.id })))
const selectedSkills = computed(() => resourceStore.skills.filter((item) => form.skillIds.includes(item.id)))
const selectedMCPs = computed(() => resourceStore.mcpServers.filter((item) => form.mcpIds.includes(item.id)))
const managerOptions = computed(() => existingAgents.value
  .filter((agent) => agent.agent_type === 'manager' && agent.status === 'active')
  .map((agent) => ({ label: agent.name, value: agent.id })))

function parseSchema(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 必须是 JSON 对象`)
  return parsed as Record<string, unknown>
}

function validateStep(index = step.value): boolean {
  if (index === 0) {
    if (!idPattern.test(form.id)) return warn('Agent ID 需为 3-64 位小写字母、数字或连字符，首尾不能为连字符')
    if (!form.name.trim()) return warn('请填写 Agent 名称')
    if (!form.role.trim()) return warn('请填写 Role；当前后端用 Role 表达职责分类')
    if (!form.system_prompt.trim()) return warn('请填写 System Prompt')
  }
  if (index === 1) {
    if (!selectedModel.value?.is_enabled) return warn('请选择模型管理中已启用的模型')
    if (form.runtime_id && selectedRuntime.value?.type !== form.runtime_type) return warn('Runtime 实例与 Runtime 类型不匹配')
  }
  if (index === 2 && selectedSkills.value.some((skill) => !skill.runtime_support.includes(form.runtime_type))) {
    return warn(`存在不支持 ${form.runtime_type} Runtime 的 Skill`)
  }
  if (index === 4) {
    try { parseSchema(form.inputSchema, 'Input Schema'); parseSchema(form.outputSchema, 'Output Schema') }
    catch (error) { return warn((error as Error).message) }
  }
  return true
}

function warn(text: string): false {
  message.warning(text)
  return false
}

function next() {
  if (!validateStep()) return
  step.value = Math.min(steps.length - 1, step.value + 1)
}

function previous() {
  step.value = Math.max(0, step.value - 1)
}

async function submit() {
  for (let index = 0; index < 5; index += 1) {
    if (!validateStep(index)) { step.value = index; return }
  }
  submitting.value = true
  try {
    const modelConfig: Record<string, unknown> = { temperature: form.temperature }
    const agent: AgentCreatePayload = {
      id: form.id,
      name: form.name.trim(),
      description: form.description.trim() || null,
      agent_type: form.agent_type,
      parent_agent_id: form.parent_agent_id,
      role: form.role.trim(),
      system_prompt: form.system_prompt,
      model_config: modelConfig,
      model: form.model.trim(),
      model_adapter: form.model_adapter,
      runtime_type: form.runtime_type,
      runtime_config: form.runtime_id ? { runtime_id: form.runtime_id } : {},
      prompt_template: form.prompt_template,
      status: form.status,
      response_mode: form.response_mode,
      input_schema: parseSchema(form.inputSchema, 'Input Schema'),
      output_schema: parseSchema(form.outputSchema, 'Output Schema'),
    }
    const result = await agentStore.createAgentWorkflow({ agent, skillIds: form.skillIds, mcpIds: form.mcpIds })
    if (result.bindingErrors.length) message.warning(`Agent 已创建，但部分绑定失败：${result.bindingErrors.join('；')}`, { duration: 8000 })
    else message.success('Agent 已创建，配置与能力绑定完成')
    await router.push({ name: 'agent-detail', params: { id: result.agent.id } })
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 7000 })
  } finally {
    submitting.value = false
  }
}

watch(() => form.model, () => {
  if (selectedModel.value) form.model_adapter = selectedModel.value.adapter
})

onMounted(async () => {
  resourceStore.fetchAll().catch(() => undefined)
  platformApi.listAgents().then((value) => { existingAgents.value = value }).catch(() => undefined)
  platformApi.listRuntimes().then((value) => { runtimes.value = value }).catch(() => undefined)
  try {
    models.value = await platformApi.listModels(true)
    const defaultModel = models.value.find((item) => item.is_default) || models.value[0]
    if (defaultModel) form.model = defaultModel.id
  } catch {
    models.value = []
  }
})
</script>

<template>
  <div>
    <PageHeader title="创建 Agent" description="按基础信息、模型、能力、契约和复核六步创建；最终严格调用现有 Agent 与绑定接口。">
      <template #actions><NButton @click="router.push({ name: 'agents' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回列表</NButton></template>
    </PageHeader>

    <div v-if="resourceStore.error" class="error-panel" style="margin-bottom: 16px">能力资源加载失败：{{ resourceStore.error }}</div>

    <nav class="wizard-steps" aria-label="Agent 创建步骤">
      <button v-for="(item, index) in steps" :key="item.title" type="button" :class="{ active: index === step, complete: index < step }" @click="index <= step && (step = index)">
        <span>{{ index < step ? '✓' : index + 1 }}</span><div><strong>{{ item.title }}</strong><small>{{ item.note }}</small></div>
      </button>
    </nav>

    <div class="wizard-layout">
      <section class="surface wizard-panel">
        <div class="wizard-heading"><span>步骤 {{ step + 1 }} / {{ steps.length }}</span><h2>{{ steps[step].title }}</h2><p>{{ steps[step].note }}</p></div>

        <NForm label-placement="top" @submit.prevent="step === 5 ? submit() : next()">
          <template v-if="step === 0">
            <div class="form-grid">
              <NFormItem label="Agent ID" required><NInput v-model:value="form.id" maxlength="64" placeholder="knowledge-analyst" /></NFormItem>
              <NFormItem label="名称" required><NInput v-model:value="form.name" maxlength="255" placeholder="知识分析 Agent" /></NFormItem>
              <NFormItem class="span-2" label="描述"><NInput v-model:value="form.description" type="textarea" :rows="3" placeholder="说明该 Agent 负责的业务任务" /></NFormItem>
              <NFormItem label="Agent 类型"><NSelect v-model:value="form.agent_type" :options="[{label:'Manager Agent',value:'manager'},{label:'Worker Agent',value:'worker'}]" /></NFormItem>
              <NFormItem label="上级 Manager"><NSelect v-model:value="form.parent_agent_id" clearable :options="managerOptions" placeholder="可选，用于父子关系" /></NFormItem>
              <NFormItem label="Role / 职责分类" required><NInput v-model:value="form.role" placeholder="企业知识分析" /></NFormItem>
              <NFormItem label="初始状态"><NSelect v-model:value="form.status" :options="[{label:'Active',value:'active'},{label:'Inactive',value:'inactive'}]" /></NFormItem>
            </div>
            <NFormItem label="System Prompt" required><NInput v-model:value="form.system_prompt" type="textarea" :rows="8" placeholder="写明职责、执行规则和禁止事项" /></NFormItem>
            <NAlert type="info" :bordered="false">现有后端没有独立 Category 字段，因此职责分类写入 Role，不创建无法持久化的前端字段。</NAlert>
          </template>

          <template v-else-if="step === 1">
            <div class="form-grid">
              <NFormItem label="模型" required><NSelect v-model:value="form.model" filterable :options="modelOptions" placeholder="从模型管理选择已启用模型" /></NFormItem>
              <NFormItem label="Provider / Adapter"><NInput :value="selectedModel ? `${selectedModel.provider} / ${selectedModel.adapter}` : '--'" disabled /></NFormItem>
              <NFormItem label="Agent Runtime"><NSelect v-model:value="form.runtime_type" :options="[{label:'Hermes Runtime',value:'hermes'},{label:'Pi Runtime',value:'pi'}]" /></NFormItem>
              <NFormItem label="Runtime 实例"><NSelect v-model:value="form.runtime_id" clearable :options="runtimeOptions" placeholder="未选择时使用环境变量默认端点" /></NFormItem>
              <NFormItem label="默认响应模式"><NSelect v-model:value="form.response_mode" :options="[{label:'Sync JSON',value:'sync'},{label:'SSE Stream',value:'stream'}]" /></NFormItem>
              <NFormItem label="Temperature"><NSlider v-model:value="form.temperature" :min="0" :max="2" :step="0.1" /></NFormItem>
            </div>
            <NFormItem label="Prompt Template"><NInput v-model:value="form.prompt_template" type="textarea" :rows="10" class="mono" /></NFormItem>
            <NAlert type="info" :bordered="false">模板变量由后端解析；input、agent_id、model、current_time 为内置变量。</NAlert>
          </template>

          <template v-else-if="step === 2">
            <NFormItem label="Select Skills"><NSelect v-model:value="form.skillIds" multiple filterable clearable :loading="resourceStore.loading" :options="skillOptions" placeholder="选择已注册 Skill" /></NFormItem>
            <div v-if="selectedSkills.length" class="selection-list"><div v-for="skill in selectedSkills" :key="skill.id"><strong>{{ skill.name }}</strong><span>{{ skill.id }} · v{{ skill.version }}</span></div></div>
            <div v-else class="schema-empty">没有选择 Skill。Agent 仍可创建，后续可在 Configuration 中绑定。</div>
          </template>

          <template v-else-if="step === 3">
            <NFormItem label="Select MCP"><NSelect v-model:value="form.mcpIds" multiple filterable clearable :loading="resourceStore.loading" :options="mcpOptions" placeholder="选择已注册 MCP" /></NFormItem>
            <NAlert type="warning" :bordered="false" style="margin-bottom: 14px">当前平台仅允许经 MCP Gateway 注册的 read_only filesystem/database 能力。</NAlert>
            <div v-if="selectedMCPs.length" class="selection-list"><div v-for="server in selectedMCPs" :key="server.id"><strong>{{ server.name }}</strong><span>{{ server.config.kind }} · {{ server.permission }} · {{ server.status }}</span></div></div>
            <div v-else class="schema-empty">没有选择 MCP。后续可在 Configuration 中绑定。</div>
          </template>

          <template v-else-if="step === 4">
            <div class="schema-grid">
              <NFormItem label="Input Schema"><NInput v-model:value="form.inputSchema" type="textarea" :rows="20" class="mono" /></NFormItem>
              <NFormItem label="Output Schema"><NInput v-model:value="form.outputSchema" type="textarea" :rows="20" class="mono" /></NFormItem>
            </div>
            <NAlert type="info" :bordered="false">创建时写入真实 input_schema 和 output_schema；后端会继续执行 JSON Schema 校验。</NAlert>
          </template>

          <template v-else>
            <div class="review-grid">
              <section><h3>Agent</h3><dl><div><dt>ID</dt><dd class="mono">{{ form.id }}</dd></div><div><dt>名称</dt><dd>{{ form.name }}</dd></div><div><dt>类型</dt><dd>{{ form.agent_type }}</dd></div><div><dt>Role</dt><dd>{{ form.role }}</dd></div><div><dt>状态</dt><dd>{{ form.status }}</dd></div></dl></section>
              <section><h3>Runtime</h3><dl><div><dt>Runtime</dt><dd>{{ form.runtime_type }}</dd></div><div><dt>实例</dt><dd>{{ selectedRuntime?.name || '环境变量默认端点' }}</dd></div><div><dt>版本</dt><dd>{{ selectedRuntime?.version || '--' }}</dd></div><div><dt>状态</dt><dd>{{ selectedRuntime?.status || '未注册' }}</dd></div><div><dt>Model</dt><dd class="mono">{{ form.model }}</dd></div><div><dt>Adapter</dt><dd>{{ form.model_adapter }}</dd></div><div><dt>响应</dt><dd>{{ form.response_mode }}</dd></div><div><dt>Temperature</dt><dd>{{ form.temperature }}</dd></div></dl></section>
              <section><h3>Capabilities</h3><dl><div><dt>Skills</dt><dd>{{ form.skillIds.length }}</dd></div><div><dt>MCP</dt><dd>{{ form.mcpIds.length }}</dd></div><div><dt>Input Schema</dt><dd>已配置</dd></div><div><dt>Output Schema</dt><dd>已配置</dd></div></dl></section>
            </div>
            <NAlert type="warning" :bordered="false">Agent 创建与 Skill/MCP 绑定不是同一后端事务；发生部分失败时会保留 Agent，并明确报告失败项。</NAlert>
          </template>

          <div class="wizard-actions">
            <NButton :disabled="step === 0 || submitting" @click="previous"><template #icon><NIcon :component="ArrowLeft" /></template>上一步</NButton>
            <NButton v-if="step < 5" type="primary" attr-type="submit">下一步<template #icon><NIcon :component="ArrowRight" /></template></NButton>
            <NButton v-else type="primary" attr-type="submit" :loading="submitting"><template #icon><NIcon :component="DeviceFloppy" /></template>创建 Agent</NButton>
          </div>
        </NForm>
      </section>

      <aside class="surface sticky-summary">
        <h2>配置摘要</h2>
        <div class="summary-list">
          <div class="summary-row"><span>ID</span><strong class="mono">{{ form.id || '待填写' }}</strong></div>
          <div class="summary-row"><span>名称</span><strong>{{ form.name || '待填写' }}</strong></div>
          <div class="summary-row"><span>类型</span><strong>{{ form.agent_type }}</strong></div>
          <div class="summary-row"><span>Runtime</span><strong>{{ form.runtime_type }}</strong></div>
          <div class="summary-row"><span>模型</span><strong class="mono">{{ form.model || '待填写' }}</strong></div>
          <div class="summary-row"><span>响应</span><strong>{{ form.response_mode }}</strong></div>
          <div class="summary-row"><span>Skill</span><strong>{{ form.skillIds.length }} 个</strong></div>
          <div class="summary-row"><span>MCP</span><strong>{{ form.mcpIds.length }} 个</strong></div>
        </div>
        <div class="summary-note"><NIcon :component="Check" /> 每一步都使用现有后端可持久化字段。</div>
      </aside>
    </div>
  </div>
</template>
