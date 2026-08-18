<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { Key, PlugConnected, Plus, Refresh, ShieldLock } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useManagementStore } from '@/stores/management'
import { formatDate } from '@/utils/format'
import type { CapabilityRecord, CredentialRecord, PlatformConnection } from '@/types/api'

const message = useMessage()
const management = useManagementStore()
const activeTab = ref<'connections' | 'capabilities' | 'credentials'>('connections')
const loading = ref(false)
const error = ref<string | null>(null)
const connections = ref<PlatformConnection[]>([])
const capabilities = ref<CapabilityRecord[]>([])
const credentials = ref<CredentialRecord[]>([])
const credentialOpen = ref(false)
const capabilityOpen = ref(false)
const wizardOpen = ref(false)
const saving = ref(false)
const wizardStep = ref(0)

const credentialForm = reactive({ name: '', credential_type: 'api_key', secret: '' })
const capabilityForm = reactive({ namespace: 'platform', key: '', display_name: '', description: '', risk_level: 'LOW' as 'LOW' | 'MEDIUM' | 'HIGH' })
const connectorForm = reactive({
  key: '', display_name: '', description: '', type: 'internal_rest' as 'internal_rest' | 'mcp',
  instance_name: 'production', endpoint: '', auth_type: 'none' as 'none' | 'bearer' | 'header', credential_ref: null as string | null,
  network_zone: 'internal' as 'internal' | 'dmz', auth_header: 'X-API-Key',
  operation_key: '', operation_name: '', method: 'POST', path_or_tool: '',
  request_schema: '{\n  "type": "object",\n  "properties": {},\n  "additionalProperties": false\n}',
  response_schema: '{\n  "type": "object",\n  "properties": {}\n}',
  capability_key: '', capability_name: '', capability_version: '1.0.0',
})

const credentialOptions = computed(() => credentials.value.map((item) => ({ label: `${item.name} (${item.masked_label})`, value: item.id })))
const wizardTitles = ['选择连接类型', '配置并测试', '定义 Operation', '发布 Capability']

function jsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 必须是 JSON 对象`)
  return parsed as Record<string, unknown>
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [connectionValues, capabilityValues, credentialValues] = await Promise.all([
      platformApi.listPlatformConnections(),
      platformApi.listCapabilities(),
      platformApi.listCredentials(),
    ])
    connections.value = connectionValues
    capabilities.value = capabilityValues
    credentials.value = credentialValues
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

function requireManagement(): boolean {
  if (management.unlocked) return true
  message.warning('请先使用页面右上角的管理员解锁功能')
  return false
}

async function saveCredential() {
  if (!requireManagement()) return
  saving.value = true
  try {
    await platformApi.createCredential(credentialForm, management.key)
    credentialOpen.value = false
    Object.assign(credentialForm, { name: '', credential_type: 'api_key', secret: '' })
    await load()
    message.success('凭据已加密保存')
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    saving.value = false
  }
}

async function saveCapability() {
  if (!requireManagement()) return
  saving.value = true
  try {
    await platformApi.createCapability(capabilityForm, management.key)
    capabilityOpen.value = false
    Object.assign(capabilityForm, { namespace: 'platform', key: '', display_name: '', description: '', risk_level: 'LOW' })
    await load()
    message.success('Capability Draft 已创建')
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    saving.value = false
  }
}

function nextWizard() {
  try {
    if (wizardStep.value === 0 && (!connectorForm.key || !connectorForm.display_name)) throw new Error('请填写连接 Key 和名称')
    if (wizardStep.value === 1 && !connectorForm.endpoint) throw new Error('请填写固定 Endpoint')
    if (wizardStep.value === 2) {
      if (!connectorForm.operation_key || !connectorForm.path_or_tool) throw new Error('请填写 Operation Key 和调用路径')
      jsonObject(connectorForm.request_schema, 'Request Schema')
      jsonObject(connectorForm.response_schema, 'Response Schema')
    }
    if (wizardStep.value === 3 && (!connectorForm.capability_key || !connectorForm.capability_name)) throw new Error('请填写 Capability Key 和名称')
    wizardStep.value = Math.min(3, wizardStep.value + 1)
  } catch (cause) {
    message.warning((cause as Error).message)
  }
}

async function finishConnector() {
  if (!requireManagement()) return
  saving.value = true
  try {
    const requestSchema = jsonObject(connectorForm.request_schema, 'Request Schema')
    const responseSchema = jsonObject(connectorForm.response_schema, 'Response Schema')
    const connector = await platformApi.createConnector({
      key: connectorForm.key,
      display_name: connectorForm.display_name,
      description: connectorForm.description,
      type: connectorForm.type,
    }, management.key)
    const instance = await platformApi.createConnectorInstance(connector.id, { name: connectorForm.instance_name, environment: 'production' }, management.key)
    const revision = await platformApi.createConnectorRevision(instance.id, {
      endpoint: connectorForm.endpoint,
      auth_type: connectorForm.auth_type,
      credential_ref: connectorForm.credential_ref,
      network_zone: connectorForm.network_zone,
      connection_config: connectorForm.auth_type === 'header' ? { auth_header: connectorForm.auth_header } : {},
      timeout_policy: { connect_seconds: 5, read_seconds: 15 },
      retry_policy: { max_retries: 1 },
      health_check_config: {},
    }, management.key)
    const operation = await platformApi.createConnectorOperation(connector.id, {
      operation_key: connectorForm.operation_key,
      display_name: connectorForm.operation_name || connectorForm.operation_key,
      protocol: connectorForm.type,
      method: connectorForm.type === 'internal_rest' ? connectorForm.method : null,
      path_or_tool: connectorForm.path_or_tool,
      request_schema: requestSchema,
      response_schema: responseSchema,
      request_mapping: {}, response_mapping: {}, error_mapping: {}, side_effect: 'READ_ONLY',
    }, management.key)
    const capability = await platformApi.createCapability({
      namespace: 'platform', key: connectorForm.capability_key,
      display_name: connectorForm.capability_name, description: connectorForm.description, risk_level: 'LOW',
    }, management.key)
    const version = await platformApi.createCapabilityVersion(capability.id, {
      version: connectorForm.capability_version,
      input_schema: requestSchema, output_schema: responseSchema, ui_schema: {}, error_schema: {},
      side_effect: 'READ_ONLY', idempotency: 'SAFE_RETRY', cache_policy: {}, default_timeout_ms: 15000, compatibility: {},
    }, management.key)
    await platformApi.testCapabilityVersion(version.id, management.key)
    await platformApi.publishCapabilityVersion(version.id, management.key)
    await platformApi.createCapabilityImplementation({
      capability_version_id: version.id,
      connector_operation_id: operation.id,
      connector_instance_revision_id: revision.id,
      mapping_override: {}, priority: 100, routing_weight: 100,
    }, management.key)
    const health = await platformApi.testConnectorRevision(revision.id, management.key)
    wizardOpen.value = false
    wizardStep.value = 0
    await load()
    message.success(`连接与能力已发布，健康状态：${health.status}`)
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="连接与能力" description="统一管理真实接口、加密凭据和 Agent 可绑定的抽象能力。">
      <template #actions>
        <NButton secondary :loading="loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" :disabled="!management.unlocked" @click="wizardOpen = true"><template #icon><NIcon :component="Plus" /></template>创建连接</NButton>
      </template>
    </PageHeader>

    <NAlert v-if="!management.unlocked" type="warning" :bordered="false" style="margin-bottom: 16px">
      当前为只读模式。使用右上角“管理员解锁”后才能创建、测试或发布连接。
    </NAlert>
    <div v-if="error" class="error-panel" style="margin-bottom: 16px">{{ error }}</div>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="connections" tab="连接">
        <section class="surface panel-flush">
          <div v-if="loading" class="loading-stack" style="padding: 20px"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
          <div v-else-if="connections.length === 0" class="empty-state"><div><NIcon :component="PlugConnected" size="28" /><h3>还没有连接</h3><p>创建 Internal REST 或 MCP 连接后，Capability 才能获得真实实现。</p></div></div>
          <div v-else class="registry-list">
            <div v-for="item in connections" :key="item.id" class="registry-row">
              <div><strong>{{ item.name }}</strong><span class="mono">{{ item.key }} / {{ item.type }}</span></div>
              <span>{{ item.instances }} 个实例</span><span>{{ item.capability_count }} 个能力</span>
              <StatusTag :status="item.status" /><span class="muted">{{ formatDate(item.updated_at) }}</span>
            </div>
          </div>
        </section>
      </NTabPane>
      <NTabPane name="capabilities" tab="能力">
        <div class="toolbar-row"><span class="muted">Published Version 不允许原地修改。</span><NButton :disabled="!management.unlocked" @click="capabilityOpen = true">新建 Capability</NButton></div>
        <section class="surface panel-flush"><div class="registry-list">
          <div v-for="item in capabilities" :key="item.id" class="registry-row"><div><strong>{{ item.display_name }}</strong><span class="mono">{{ item.namespace }}.{{ item.key }}</span></div><span>{{ item.risk_level }}</span><StatusTag :status="item.status" /></div>
          <div v-if="!capabilities.length" class="empty-state"><div><h3>暂无 Capability</h3><p>能力用于解耦 Skill 与真实接口。</p></div></div>
        </div></section>
      </NTabPane>
      <NTabPane name="credentials" tab="凭据">
        <div class="toolbar-row"><span class="muted">密钥明文不会从后端返回。</span><NButton :disabled="!management.unlocked" @click="credentialOpen = true"><template #icon><NIcon :component="Key" /></template>新增凭据</NButton></div>
        <section class="surface panel-flush"><div class="registry-list">
          <div v-for="item in credentials" :key="item.id" class="registry-row"><div><strong>{{ item.name }}</strong><span>{{ item.credential_type }}</span></div><span class="mono">{{ item.masked_label }}</span><StatusTag :status="item.rotation_status" /><span>{{ formatDate(item.last_rotated_at) }}</span></div>
          <div v-if="!credentials.length" class="empty-state"><div><NIcon :component="ShieldLock" size="28" /><h3>暂无加密凭据</h3><p>凭据通过 Fernet 加密，Runtime 和 Agent 不接触明文。</p></div></div>
        </div></section>
      </NTabPane>
    </NTabs>

    <NModal v-model:show="credentialOpen" preset="card" title="新增加密凭据" style="width: min(560px, calc(100vw - 32px))">
      <NForm label-placement="top"><NFormItem label="名称" required><NInput v-model:value="credentialForm.name" /></NFormItem><NFormItem label="类型" required><NInput v-model:value="credentialForm.credential_type" /></NFormItem><NFormItem label="密钥" required><NInput v-model:value="credentialForm.secret" type="password" show-password-on="click" /></NFormItem></NForm>
      <template #footer><div class="dialog-actions"><NButton @click="credentialOpen = false">取消</NButton><NButton type="primary" :loading="saving" @click="saveCredential">加密保存</NButton></div></template>
    </NModal>

    <NModal v-model:show="capabilityOpen" preset="card" title="新建 Capability Draft" style="width: min(620px, calc(100vw - 32px))">
      <NForm label-placement="top"><div class="form-grid"><NFormItem label="Namespace"><NInput v-model:value="capabilityForm.namespace" /></NFormItem><NFormItem label="Key" required><NInput v-model:value="capabilityForm.key" placeholder="knowledge.search" /></NFormItem><NFormItem label="名称" required><NInput v-model:value="capabilityForm.display_name" /></NFormItem><NFormItem label="风险"><NSelect v-model:value="capabilityForm.risk_level" :options="['LOW','MEDIUM','HIGH'].map(value => ({label:value,value}))" /></NFormItem><NFormItem class="span-2" label="描述"><NInput v-model:value="capabilityForm.description" type="textarea" /></NFormItem></div></NForm>
      <template #footer><div class="dialog-actions"><NButton @click="capabilityOpen = false">取消</NButton><NButton type="primary" :loading="saving" @click="saveCapability">创建 Draft</NButton></div></template>
    </NModal>

    <NModal v-model:show="wizardOpen" preset="card" title="创建连接" style="width: min(860px, calc(100vw - 32px))" :mask-closable="false">
      <nav class="compact-steps" aria-label="创建连接步骤"><span v-for="(title, index) in wizardTitles" :key="title" :class="{ active: index === wizardStep, complete: index < wizardStep }">{{ index + 1 }}. {{ title }}</span></nav>
      <NForm label-placement="top" style="margin-top: 22px">
        <div v-if="wizardStep === 0" class="form-grid"><NFormItem label="连接类型" required><NSelect v-model:value="connectorForm.type" :options="[{label:'Internal REST',value:'internal_rest'},{label:'MCP',value:'mcp'}]" /></NFormItem><NFormItem label="Connector Key" required><NInput v-model:value="connectorForm.key" /></NFormItem><NFormItem label="显示名称" required><NInput v-model:value="connectorForm.display_name" /></NFormItem><NFormItem label="实例名称"><NInput v-model:value="connectorForm.instance_name" /></NFormItem><NFormItem class="span-2" label="描述"><NInput v-model:value="connectorForm.description" type="textarea" /></NFormItem></div>
        <div v-else-if="wizardStep === 1" class="form-grid"><NFormItem class="span-2" label="固定 Endpoint" required><NInput v-model:value="connectorForm.endpoint" placeholder="http://service:8080 或 https://api.example" /></NFormItem><NFormItem label="网络区域"><NSelect v-model:value="connectorForm.network_zone" :options="[{label:'Internal',value:'internal'},{label:'DMZ',value:'dmz'}]" /></NFormItem><NFormItem label="认证方式"><NSelect v-model:value="connectorForm.auth_type" :options="[{label:'无',value:'none'},{label:'Bearer',value:'bearer'},{label:'自定义 Header',value:'header'}]" /></NFormItem><NFormItem v-if="connectorForm.auth_type !== 'none'" label="加密凭据"><NSelect v-model:value="connectorForm.credential_ref" :options="credentialOptions" /></NFormItem><NFormItem v-if="connectorForm.auth_type === 'header'" label="Header 名称"><NInput v-model:value="connectorForm.auth_header" /></NFormItem></div>
        <div v-else-if="wizardStep === 2" class="form-grid"><NFormItem label="Operation Key" required><NInput v-model:value="connectorForm.operation_key" /></NFormItem><NFormItem label="显示名称"><NInput v-model:value="connectorForm.operation_name" /></NFormItem><NFormItem v-if="connectorForm.type === 'internal_rest'" label="HTTP Method"><NSelect v-model:value="connectorForm.method" :options="['GET','POST','PUT','PATCH','DELETE'].map(value => ({label:value,value}))" /></NFormItem><NFormItem label="路径或 MCP Tool" required><NInput v-model:value="connectorForm.path_or_tool" /></NFormItem><NFormItem label="Request Schema"><NInput v-model:value="connectorForm.request_schema" type="textarea" :rows="10" class="mono" /></NFormItem><NFormItem label="Response Schema"><NInput v-model:value="connectorForm.response_schema" type="textarea" :rows="10" class="mono" /></NFormItem></div>
        <div v-else class="form-grid"><NFormItem label="Capability Key" required><NInput v-model:value="connectorForm.capability_key" placeholder="knowledge.search" /></NFormItem><NFormItem label="显示名称" required><NInput v-model:value="connectorForm.capability_name" /></NFormItem><NFormItem label="版本"><NInput v-model:value="connectorForm.capability_version" /></NFormItem><NFormItem label="副作用"><NInput value="READ_ONLY" disabled /></NFormItem><NAlert class="span-2" type="info" :bordered="false">完成后会依次创建 Connector、Revision、Operation、Capability Version 和固定实现，并执行健康检查。</NAlert></div>
      </NForm>
      <template #footer><div class="dialog-actions"><NButton @click="wizardOpen = false">取消</NButton><NButton v-if="wizardStep > 0" @click="wizardStep -= 1">上一步</NButton><NButton v-if="wizardStep < 3" type="primary" @click="nextWizard">下一步</NButton><NButton v-else type="primary" :loading="saving" @click="finishConnector">发布并测试</NButton></div></template>
    </NModal>
  </div>
</template>

<style scoped>
.toolbar-row,.dialog-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.dialog-actions{justify-content:flex-end;margin:0}.registry-list{display:grid}.registry-row{display:grid;grid-template-columns:minmax(220px,1.6fr) repeat(3,minmax(100px,.55fr));gap:16px;align-items:center;padding:15px 20px;border-bottom:1px solid var(--line)}.registry-row:last-child{border-bottom:0}.registry-row>div{display:grid;gap:4px}.registry-row span{font-size:12px}.compact-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.compact-steps span{padding:10px 12px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}.compact-steps .active{border-color:var(--accent);color:var(--ink);background:var(--accent-soft)}.compact-steps .complete{color:#63c174}@media(max-width:760px){.registry-row{grid-template-columns:1fr}.compact-steps{grid-template-columns:1fr 1fr}}
</style>
