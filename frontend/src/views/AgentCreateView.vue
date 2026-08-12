<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useMessage, type FormInst, type FormRules } from 'naive-ui'
import { NIcon } from 'naive-ui'
import { ArrowLeft, DeviceFloppy } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import type { AgentCreatePayload, AgentStatus, ResponseMode } from '@/types/api'

const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

interface FormModel {
  id: string
  name: string
  description: string
  role: string
  system_prompt: string
  model: string
  temperature: number
  status: AgentStatus
  response_mode: ResponseMode
  skillIds: string[]
  mcpIds: string[]
}

const form = reactive<FormModel>({
  id: '',
  name: '',
  description: '',
  role: '',
  system_prompt: '',
  model: '',
  temperature: 0.1,
  status: 'active',
  response_mode: 'sync',
  skillIds: [],
  mcpIds: [],
})

const idPattern = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/
const rules: FormRules = {
  id: [
    { required: true, message: '请输入 Agent ID', trigger: ['input', 'blur'] },
    { validator: (_rule, value: string) => idPattern.test(value), message: 'ID 需为 3-64 位小写字母、数字或连字符，首尾不能为连字符', trigger: ['input', 'blur'] },
  ],
  name: { required: true, message: '请输入 Agent 名称', trigger: ['input', 'blur'] },
  role: { required: true, message: '请输入角色定义', trigger: ['input', 'blur'] },
  system_prompt: { required: true, message: '请输入 System Prompt', trigger: ['input', 'blur'] },
}

const skillOptions = computed(() => resourceStore.skills.map((skill) => ({ label: skill.name, value: skill.id })))
const mcpOptions = computed(() => resourceStore.mcpServers.map((server) => ({ label: `${server.name}（${server.config.kind}）`, value: server.id })))

async function submit() {
  await formRef.value?.validate()
  submitting.value = true
  try {
    const modelConfig: Record<string, unknown> = { temperature: form.temperature }
    if (form.model.trim()) modelConfig.model = form.model.trim()
    const agent: AgentCreatePayload = {
      id: form.id,
      name: form.name,
      description: form.description.trim() || null,
      role: form.role,
      system_prompt: form.system_prompt,
      model_config: modelConfig,
      status: form.status,
      response_mode: form.response_mode,
    }
    const result = await agentStore.createAgentWorkflow({ agent, skillIds: form.skillIds, mcpIds: form.mcpIds })
    if (result.bindingErrors.length) {
      message.warning(`Agent 已创建，但部分绑定失败：${result.bindingErrors.join('；')}`, { duration: 8000 })
    } else {
      message.success('Agent 创建并绑定成功')
    }
    await router.push({ name: 'agent-detail', params: { id: result.agent.id } })
  } catch (error) {
    if (error && typeof error === 'object' && 'warnings' in error) return
    message.error(getApiErrorMessage(error), { duration: 6000 })
  } finally {
    submitting.value = false
  }
}

onMounted(() => resourceStore.fetchAll().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="创建 Agent" description="先写入 Agent 配置，再通过后端的独立绑定接口关联 Skill 和 MCP。">
      <template #actions>
        <NButton @click="router.push({ name: 'agents' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回列表</NButton>
      </template>
    </PageHeader>

    <div v-if="resourceStore.error" class="error-panel" style="margin-bottom: 16px">能力资源加载失败：{{ resourceStore.error }}</div>

    <div class="form-shell">
      <NForm ref="formRef" :model="form" :rules="rules" label-placement="top" class="surface form-panel" @submit.prevent="submit">
        <section class="form-section">
          <h2 class="form-section-title">基础信息</h2>
          <div class="form-grid">
            <NFormItem label="Agent ID" path="id">
              <NInput v-model:value="form.id" maxlength="64" placeholder="knowledge-analyst" />
            </NFormItem>
            <NFormItem label="名称" path="name">
              <NInput v-model:value="form.name" maxlength="255" placeholder="知识分析 Agent" />
            </NFormItem>
            <NFormItem class="span-2" label="描述" path="description">
              <NInput v-model:value="form.description" type="textarea" :rows="2" placeholder="说明该 Agent 负责的业务任务" />
            </NFormItem>
            <NFormItem label="状态" path="status">
              <NSelect v-model:value="form.status" :options="[{ label: '启用，可立即执行', value: 'active' }, { label: '草稿，不允许执行', value: 'draft' }, { label: '禁用', value: 'disabled' }]" />
            </NFormItem>
            <NFormItem label="模型标识（配置元数据）" path="model">
              <NInput v-model:value="form.model" placeholder="qwen-300b" />
            </NFormItem>
            <NFormItem label="默认响应模式" path="response_mode">
              <NSelect v-model:value="form.response_mode" :options="[{ label: 'Sync JSON', value: 'sync' }, { label: 'SSE Stream', value: 'stream' }]" />
            </NFormItem>
            <NFormItem class="span-2" label="温度（配置元数据）" path="temperature">
              <NSlider v-model:value="form.temperature" :min="0" :max="2" :step="0.1" :tooltip="true" />
            </NFormItem>
          </div>
          <NAlert type="info" :bordered="false">
            当前后端的 HermesClient 使用平台级 `HERMES_MODEL`。这里的 `model_config` 会保存并展示，但不会覆盖运行时模型。
          </NAlert>
        </section>

        <section class="form-section">
          <h2 class="form-section-title">角色与行为</h2>
          <NFormItem label="Role" path="role">
            <NInput v-model:value="form.role" type="textarea" :rows="3" placeholder="例如：企业知识分析专家" />
          </NFormItem>
          <NFormItem label="System Prompt" path="system_prompt">
            <NInput v-model:value="form.system_prompt" type="textarea" :rows="7" placeholder="写明职责、执行规则和禁止事项" />
          </NFormItem>
        </section>

        <section class="form-section">
          <h2 class="form-section-title">能力绑定</h2>
          <div class="form-grid">
            <NFormItem label="Skill">
              <NSelect v-model:value="form.skillIds" multiple filterable clearable :loading="resourceStore.loading" :options="skillOptions" placeholder="选择已注册 Skill" />
            </NFormItem>
            <NFormItem label="MCP">
              <NSelect v-model:value="form.mcpIds" multiple filterable clearable :loading="resourceStore.loading" :options="mcpOptions" placeholder="选择只读 MCP" />
            </NFormItem>
          </div>
        </section>

        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 26px">
          <NButton @click="router.push({ name: 'agents' })">取消</NButton>
          <NButton type="primary" attr-type="submit" :loading="submitting">
            <template #icon><NIcon :component="DeviceFloppy" /></template>创建并绑定
          </NButton>
        </div>
      </NForm>

      <aside class="surface sticky-summary">
        <h2>配置摘要</h2>
        <div class="summary-list">
          <div class="summary-row"><span>ID</span><strong class="mono">{{ form.id || '待填写' }}</strong></div>
          <div class="summary-row"><span>名称</span><strong>{{ form.name || '待填写' }}</strong></div>
          <div class="summary-row"><span>状态</span><strong>{{ { active: '启用', draft: '草稿', disabled: '禁用' }[form.status] }}</strong></div>
          <div class="summary-row"><span>响应</span><strong>{{ form.response_mode === 'stream' ? 'SSE Stream' : 'Sync JSON' }}</strong></div>
          <div class="summary-row"><span>Skill</span><strong>{{ form.skillIds.length }} 个</strong></div>
          <div class="summary-row"><span>MCP</span><strong>{{ form.mcpIds.length }} 个</strong></div>
        </div>
        <div class="summary-note">
          Agent 创建和资源绑定不是同一个后端事务。发生部分失败时，系统会保留已创建的 Agent，并明确报告失败项。
        </div>
      </aside>
    </div>
  </div>
</template>
