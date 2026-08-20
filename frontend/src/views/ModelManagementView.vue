<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NForm, NFormItem, NIcon, NInputNumber, NModal, NSwitch, useDialog, useMessage } from 'naive-ui'
import { Plus, Refresh, Robot, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import type {
  ModelAdapterName,
  ModelCreatePayload,
  ModelProvider,
  RegisteredModel,
} from '@/types/api'

const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const error = ref('')
const query = ref('')
const models = ref<RegisteredModel[]>([])
const showEditor = ref(false)
const editingId = ref<string | null>(null)

const form = reactive({
  id: '',
  displayName: '',
  provider: 'custom' as ModelProvider,
  adapter: 'hermes' as ModelAdapterName,
  baseUrl: '',
  upstreamModel: '',
  apiKey: '',
  clearApiKey: false,
  enabled: true,
  makeDefault: false,
  timeoutSeconds: 180,
  maxRetries: 2,
})

const providerOptions = [
  { label: 'Qwen', value: 'qwen' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Claude', value: 'claude' },
  { label: '自定义 OpenAI Compatible', value: 'custom' },
]
const adapterOptions = [
  { label: 'Hermes', value: 'hermes' },
  { label: 'Qwen', value: 'qwen' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'GPT / OpenAI', value: 'gpt' },
  { label: 'Claude', value: 'claude' },
]
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return models.value
  return models.value.filter((item) => [
    item.id,
    item.display_name,
    item.provider,
    item.base_url,
    item.upstream_model,
  ].some((value) => value.toLowerCase().includes(keyword)))
})
const enabledCount = computed(() => models.value.filter((item) => item.is_enabled).length)
const onlineCount = computed(() => models.value.filter((item) => item.status === 'online').length)

async function load() {
  loading.value = true
  try {
    models.value = await platformApi.listModels()
    error.value = ''
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    id: '', displayName: '', provider: 'custom', adapter: 'hermes', baseUrl: '',
    upstreamModel: '', apiKey: '', clearApiKey: false, enabled: true,
    makeDefault: models.value.length === 0, timeoutSeconds: 180, maxRetries: 2,
  })
  showEditor.value = true
}

function openEdit(model: RegisteredModel) {
  editingId.value = model.id
  Object.assign(form, {
    id: model.id,
    displayName: model.display_name,
    provider: model.provider,
    adapter: model.adapter,
    baseUrl: model.base_url,
    upstreamModel: model.upstream_model,
    apiKey: '',
    clearApiKey: false,
    enabled: model.is_enabled,
    makeDefault: model.is_default,
    timeoutSeconds: model.timeout_seconds,
    maxRetries: model.max_retries,
  })
  showEditor.value = true
}

async function save() {
  if (!form.id.trim() || !form.displayName.trim() || !form.baseUrl.trim() || !form.upstreamModel.trim()) {
    message.warning('请完整填写模型 ID、显示名称、地址和上游模型名')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await platformApi.updateModel(editingId.value, {
        display_name: form.displayName.trim(),
        provider: form.provider,
        adapter: form.adapter,
        base_url: form.baseUrl.trim(),
        upstream_model: form.upstreamModel.trim(),
        api_key: form.apiKey || undefined,
        clear_api_key: form.clearApiKey,
        is_enabled: form.enabled,
        timeout_seconds: form.timeoutSeconds,
        max_retries: form.maxRetries,
      })
    } else {
      const payload: ModelCreatePayload = {
        id: form.id.trim(),
        display_name: form.displayName.trim(),
        provider: form.provider,
        adapter: form.adapter,
        base_url: form.baseUrl.trim(),
        upstream_model: form.upstreamModel.trim(),
        api_key: form.apiKey || null,
        is_enabled: form.enabled,
        is_default: form.makeDefault,
        timeout_seconds: form.timeoutSeconds,
        max_retries: form.maxRetries,
      }
      await platformApi.createModel(payload)
    }
    await load()
    showEditor.value = false
    message.success(editingId.value ? '模型配置已更新，网关将立即使用新配置' : '模型已注册')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 7000 })
  } finally {
    saving.value = false
  }
}

async function test(model: RegisteredModel) {
  testingId.value = model.id
  try {
    const result = await platformApi.testModel(model.id)
    await load()
    message[result.status === 'online' ? 'success' : 'error'](
      `${result.detail}，${result.latency_ms} ms`,
      { duration: 7000 },
    )
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 7000 })
  } finally {
    testingId.value = null
  }
}

async function setDefault(model: RegisteredModel) {
  try {
    await platformApi.setDefaultModel(model.id)
    await load()
    message.success(`${model.display_name} 已设为默认模型`)
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 7000 })
  }
}

function remove(model: RegisteredModel) {
  dialog.warning({
    title: '删除模型配置',
    content: `确认删除 ${model.display_name}（${model.id}）？默认模型或仍被 Agent 使用的模型会被后端拒绝删除。`,
    positiveText: '删除',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await platformApi.deleteModel(model.id)
        await load()
        message.success('模型配置已删除')
      } catch (cause) {
        message.error(getApiErrorMessage(cause), { duration: 7000 })
      }
    },
  })
}

onMounted(load)
</script>

<template>
  <section class="model-page">
    <PageHeader eyebrow="MODEL REGISTRY" title="模型管理" description="统一管理 Agent 实际使用的模型地址、上游模型名和访问密钥。">
      <template #actions>
        <NButton :loading="loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" @click="openCreate"><template #icon><NIcon :component="Plus" /></template>新增模型</NButton>
      </template>
    </PageHeader>

    <NAlert type="warning" :bordered="false">
      模型 API Key 在数据库中加密保存，接口永不回显。模型配置修改会立即影响后续 Agent 调用。
    </NAlert>

    <NAlert v-if="error" type="error" closable @close="error = ''">{{ error }}</NAlert>

    <div class="model-metrics">
      <article><strong>{{ models.length }}</strong><span>注册模型</span></article>
      <article><strong>{{ enabledCount }}</strong><span>已启用</span></article>
      <article><strong>{{ onlineCount }}</strong><span>最近测试在线</span></article>
    </div>

    <div class="toolbar surface">
      <NInput v-model:value="query" clearable placeholder="搜索模型 ID、名称、Provider 或地址">
        <template #prefix><NIcon :component="Search" /></template>
      </NInput>
      <span>{{ filtered.length }} 项</span>
    </div>

    <div v-if="loading" class="model-grid">
      <article v-for="index in 3" :key="index" class="surface model-card"><div class="skeleton-line" /><div class="skeleton-line" /></article>
    </div>
    <div v-else-if="filtered.length" class="model-grid">
      <article v-for="model in filtered" :key="model.id" class="surface model-card">
        <header>
          <span class="model-icon"><NIcon :component="Robot" /></span>
          <div><span>{{ model.provider }} · {{ model.adapter }}</span><h2>{{ model.display_name }}</h2><code>{{ model.id }}</code></div>
          <div class="card-tags"><NTag v-if="model.is_default" type="success" :bordered="false">默认</NTag><StatusTag :status="model.is_enabled ? model.status : 'disabled'" /></div>
        </header>
        <dl>
          <div><dt>Base URL</dt><dd class="mono endpoint">{{ model.base_url }}</dd></div>
          <div><dt>上游模型</dt><dd class="mono">{{ model.upstream_model }}</dd></div>
          <div><dt>API Key</dt><dd>{{ model.api_key_configured ? '已配置（不回显）' : '未配置' }}</dd></div>
          <div><dt>超时 / 重试</dt><dd>{{ model.timeout_seconds }} 秒 / {{ model.max_retries }} 次</dd></div>
          <div><dt>最近检查</dt><dd>{{ model.last_health_at ? formatDate(model.last_health_at) : '尚未检查' }}</dd></div>
        </dl>
        <NAlert v-if="model.last_error" type="error" :bordered="false">{{ model.last_error }}</NAlert>
        <footer>
          <NButton size="small" @click="openEdit(model)">编辑</NButton>
          <NButton size="small" :loading="testingId === model.id" :disabled="!model.is_enabled" @click="test(model)">真实调用测试</NButton>
          <NButton v-if="!model.is_default" size="small" @click="setDefault(model)">设为默认</NButton>
          <NButton size="small" type="error" text :disabled="model.is_default" @click="remove(model)">删除</NButton>
        </footer>
      </article>
    </div>
    <div v-else class="surface empty-state"><div><h3>暂无模型配置</h3><p>新增模型后，Agent 创建与配置页面会从这里选择模型。</p></div></div>

    <NModal v-model:show="showEditor" preset="card" style="width: min(760px, 94vw)" :title="editingId ? '编辑模型配置' : '新增模型配置'">
      <NForm label-placement="top" @submit.prevent="save">
        <div class="form-grid">
          <NFormItem label="模型 ID / Agent 使用的别名" required><NInput v-model:value="form.id" :disabled="Boolean(editingId)" placeholder="report-model" /></NFormItem>
          <NFormItem label="显示名称" required><NInput v-model:value="form.displayName" placeholder="内网报告模型" /></NFormItem>
          <NFormItem label="Provider"><NSelect v-model:value="form.provider" :options="providerOptions" /></NFormItem>
          <NFormItem label="Agent Adapter"><NSelect v-model:value="form.adapter" :options="adapterOptions" /></NFormItem>
          <NFormItem class="span-2" label="Base URL" required><NInput v-model:value="form.baseUrl" placeholder="http://model-service.internal/v1" /></NFormItem>
          <NFormItem label="上游真实模型名" required><NInput v-model:value="form.upstreamModel" placeholder="Qwen3-30B-A3B-Instruct" /></NFormItem>
          <NFormItem label="模型 API Key"><NInput v-model:value="form.apiKey" type="password" show-password-on="click" autocomplete="new-password" :placeholder="editingId ? '留空表示保留原密钥' : '无鉴权服务可留空'" /></NFormItem>
          <NFormItem label="请求超时（秒）"><NInputNumber v-model:value="form.timeoutSeconds" :min="5" :max="1800" style="width:100%" /></NFormItem>
          <NFormItem label="失败重试次数"><NInputNumber v-model:value="form.maxRetries" :min="0" :max="5" style="width:100%" /></NFormItem>
        </div>
        <div class="switches">
          <label><NSwitch v-model:value="form.enabled" :disabled="Boolean(editingId && form.makeDefault)" />启用模型</label>
          <label v-if="!editingId"><NSwitch v-model:value="form.makeDefault" />设为默认模型</label>
          <label v-if="editingId"><NSwitch v-model:value="form.clearApiKey" />清除已保存的模型密钥</label>
        </div>
        <NAlert type="info" :bordered="false">保存后 Model Gateway 无需重启，下一次 Agent 调用会按模型 ID 读取最新配置。</NAlert>
        <div class="modal-actions"><NButton @click="showEditor = false">取消</NButton><NButton attr-type="submit" type="primary" :loading="saving">保存</NButton></div>
      </NForm>
    </NModal>
  </section>
</template>

<style scoped>
.model-page { display: grid; gap: 18px; }
.model-icon { display: grid; place-items: center; border-radius: 12px; color: var(--brand); background: var(--brand-soft); }
.model-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.model-metrics article { padding: 16px 18px; border: 1px solid var(--border-color); border-radius: 14px; background: var(--surface); }
.model-metrics strong, .model-metrics span { display: block; }
.model-metrics strong { font-size: 25px; }
.model-metrics span { color: var(--text-muted); font-size: 12px; }
.toolbar { display: grid; grid-template-columns: minmax(260px, 520px) 1fr; align-items: center; gap: 16px; padding: 12px 14px; }
.toolbar > span { justify-self: end; color: var(--text-muted); font-size: 11px; }
.model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.model-card { display: grid; gap: 16px; padding: 20px; }
.model-card header { display: grid; grid-template-columns: 44px 1fr auto; align-items: start; gap: 12px; }
.model-icon { width: 44px; height: 44px; font-size: 22px; }
.model-card header span, .model-card header code { color: var(--text-muted); font-size: 10px; }
.model-card h2 { margin: 3px 0; font-size: 17px; }
.card-tags { display: flex; align-items: center; gap: 6px; }
.model-card dl { display: grid; gap: 9px; margin: 0; }
.model-card dl div { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-color); }
.model-card dt { color: var(--text-muted); font-size: 11px; }
.model-card dd { margin: 0; overflow: hidden; font-size: 12px; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.model-card footer, .modal-actions, .switches { display: flex; align-items: center; gap: 10px; }
.model-card footer { flex-wrap: wrap; }
.model-card footer :last-child { margin-left: auto; }
.switches { margin: 2px 0 16px; flex-wrap: wrap; gap: 20px; }
.switches label { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.modal-actions { justify-content: flex-end; margin-top: 18px; }
.mono { font-family: var(--font-mono); }
@media (max-width: 900px) { .model-grid { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .model-metrics { grid-template-columns: 1fr; } }
</style>
