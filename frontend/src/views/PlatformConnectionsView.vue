<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NForm, NFormItem, NIcon, NInputNumber, NModal, useMessage } from 'naive-ui'
import { History, Key, Pencil, PlugConnected, Plus, Refresh, ShieldLock } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import AdminGuideLink from '@/components/AdminGuideLink.vue'
import StatusTag from '@/components/StatusTag.vue'
import { apiClient, getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import type { CapabilityRecord, CredentialRecord, PlatformConnection } from '@/types/api'

const message = useMessage()
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
const detailLoading = ref(false)
const connectionEditorOpen = ref(false)
const capabilityEditorOpen = ref(false)
const credentialRotateOpen = ref(false)
const editingConnection = ref<PlatformConnection | null>(null)
const editingCapability = ref<CapabilityRecord | null>(null)
const editingCredential = ref<CredentialRecord | null>(null)

interface ConnectionInstanceDetail {
  id: string
  name: string
  environment: string
  health: string
  enabled: boolean
  current_revision_id: string | null
}

interface ConnectorRevisionDetail {
  id: string
  revision: number
  endpoint: string
  auth_type: 'none' | 'bearer' | 'header'
  credential_ref: string | null
  network_zone: 'internal' | 'dmz'
  connection_config: Record<string, unknown>
  timeout_policy: Record<string, unknown>
  retry_policy: Record<string, unknown>
  health_check_config: Record<string, unknown>
}

interface CapabilityVersionDetail {
  id: string
  version: string
  status: string
  side_effect: string
  idempotency: string
  default_timeout_ms: number
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
}

const connectionDetail = ref<{ instances: ConnectionInstanceDetail[] }>({ instances: [] })
const connectorOperations = ref<Array<{ id: string; display_name: string; operation_key: string; path_or_tool: string; status: string }>>([])
const activeInstanceId = ref<string | null>(null)
const connectionEditForm = reactive({ display_name: '', description: '', status: 'draft' as 'draft' | 'published' | 'disabled' })
const revisionForm = reactive({
  endpoint: '', auth_type: 'none' as 'none' | 'bearer' | 'header', credential_ref: null as string | null,
  network_zone: 'internal' as 'internal' | 'dmz', auth_header: 'X-API-Key', connect_seconds: 5, read_seconds: 15, max_retries: 1,
})
const capabilityVersions = ref<CapabilityVersionDetail[]>([])
const capabilityEditForm = reactive({ display_name: '', description: '', risk_level: 'LOW' as 'LOW' | 'MEDIUM' | 'HIGH', status: 'draft' })
const versionForm = reactive({
  version: '1.0.0', input_schema: '{}', output_schema: '{}',
  side_effect: 'READ_ONLY', idempotency: 'SAFE_RETRY', default_timeout_ms: 15000,
})
const credentialRotateForm = reactive({ secret: '' })

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
const capabilityStatusOptions = computed(() => {
  const current = capabilityEditForm.status
  const allowed = current === 'published' ? ['published', 'deprecated', 'disabled'] : current === 'deprecated' ? ['deprecated', 'disabled'] : [current, 'disabled']
  return [...new Set(allowed)].map((value) => ({ label: value, value }))
})
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

async function saveCredential() {
  saving.value = true
  try {
    await platformApi.createCredential(credentialForm)
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
  saving.value = true
  try {
    await platformApi.createCapability(capabilityForm)
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

async function loadActiveRevision(instanceId: string | null) {
  activeInstanceId.value = instanceId
  const instance = connectionDetail.value.instances.find((item) => item.id === instanceId)
  if (!instance?.current_revision_id) {
    Object.assign(revisionForm, { endpoint: '', auth_type: 'none', credential_ref: null, network_zone: 'internal', auth_header: 'X-API-Key', connect_seconds: 5, read_seconds: 15, max_retries: 1 })
    return
  }
  const { data } = await apiClient.get<ConnectorRevisionDetail>(`/api/connector-instance-revisions/${encodeURIComponent(instance.current_revision_id)}`)
  Object.assign(revisionForm, {
    endpoint: data.endpoint,
    auth_type: data.auth_type,
    credential_ref: data.credential_ref,
    network_zone: data.network_zone,
    auth_header: String(data.connection_config?.auth_header || 'X-API-Key'),
    connect_seconds: Number(data.timeout_policy?.connect_seconds || 5),
    read_seconds: Number(data.timeout_policy?.read_seconds || 15),
    max_retries: Number(data.retry_policy?.max_retries || 1),
  })
}

async function openConnectionEditor(item: PlatformConnection) {
  editingConnection.value = item
  connectionEditorOpen.value = true
  detailLoading.value = true
  try {
    const encoded = encodeURIComponent(item.id)
    const [{ data: connector }, { data: detail }, { data: operations }] = await Promise.all([
      apiClient.get<{ display_name: string; description: string | null; status: 'draft' | 'published' | 'disabled' }>(`/api/connectors/${encoded}`),
      apiClient.get<{ instances: ConnectionInstanceDetail[] }>(`/api/console/platform/connections/${encoded}`),
      apiClient.get<typeof connectorOperations.value>(`/api/connectors/${encoded}/operations`),
    ])
    Object.assign(connectionEditForm, { display_name: connector.display_name, description: connector.description || '', status: connector.status })
    connectionDetail.value = detail
    connectorOperations.value = operations
    await loadActiveRevision(detail.instances[0]?.id || null)
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    detailLoading.value = false
  }
}

async function saveConnectionMetadata() {
  if (!editingConnection.value) return
  saving.value = true
  try {
    await apiClient.patch(`/api/connectors/${encodeURIComponent(editingConnection.value.id)}`, connectionEditForm)
    await load()
    message.success('连接基础信息已更新')
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    saving.value = false
  }
}

async function createConnectionRevision() {
  if (!activeInstanceId.value || !revisionForm.endpoint.trim()) return message.warning('请选择实例并填写 Endpoint')
  if (revisionForm.auth_type !== 'none' && !revisionForm.credential_ref) return message.warning('当前认证方式必须选择加密凭据')
  saving.value = true
  try {
    const revision = await platformApi.createConnectorRevision(activeInstanceId.value, {
      endpoint: revisionForm.endpoint.trim(), auth_type: revisionForm.auth_type,
      credential_ref: revisionForm.auth_type === 'none' ? null : revisionForm.credential_ref,
      network_zone: revisionForm.network_zone,
      connection_config: revisionForm.auth_type === 'header' ? { auth_header: revisionForm.auth_header } : {},
      timeout_policy: { connect_seconds: revisionForm.connect_seconds, read_seconds: revisionForm.read_seconds },
      retry_policy: { max_retries: revisionForm.max_retries }, health_check_config: {},
    })
    const result = await platformApi.testConnectorRevision(revision.id)
    if (editingConnection.value) await openConnectionEditor(editingConnection.value)
    await load()
    message.success(`新 Revision 已创建，健康状态：${result.status}`)
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    saving.value = false
  }
}

async function loadCapabilityVersions(capabilityId: string) {
  const { data } = await apiClient.get<CapabilityVersionDetail[]>(`/api/capabilities/${encodeURIComponent(capabilityId)}/versions`)
  capabilityVersions.value = data
}

async function openCapabilityEditor(item: CapabilityRecord) {
  editingCapability.value = item
  capabilityEditorOpen.value = true
  Object.assign(capabilityEditForm, { display_name: item.display_name, description: item.description || '', risk_level: item.risk_level, status: item.status })
  try {
    await loadCapabilityVersions(item.id)
    const latest = capabilityVersions.value[0]?.version?.split('.').map(Number)
    if (latest?.length === 3 && latest.every(Number.isInteger)) versionForm.version = `${latest[0]}.${latest[1]}.${latest[2]! + 1}`
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  }
}

async function saveCapabilityMetadata() {
  if (!editingCapability.value) return
  saving.value = true
  try {
    await apiClient.patch(`/api/capabilities/${encodeURIComponent(editingCapability.value.id)}`, capabilityEditForm)
    await load()
    message.success('Capability 信息已更新')
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    saving.value = false
  }
}

async function createNewCapabilityVersion() {
  if (!editingCapability.value) return
  saving.value = true
  try {
    await platformApi.createCapabilityVersion(editingCapability.value.id, {
      version: versionForm.version, input_schema: jsonObject(versionForm.input_schema, 'Input Schema'),
      output_schema: jsonObject(versionForm.output_schema, 'Output Schema'), ui_schema: {}, error_schema: {},
      side_effect: versionForm.side_effect, idempotency: versionForm.idempotency,
      cache_policy: {}, default_timeout_ms: versionForm.default_timeout_ms, compatibility: {},
    })
    await loadCapabilityVersions(editingCapability.value.id)
    message.success('新的 Capability Draft Version 已创建')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    saving.value = false
  }
}

async function changeCapabilityVersion(version: CapabilityVersionDetail, action: 'test' | 'publish' | 'deprecate') {
  saving.value = true
  try {
    if (action === 'test') await platformApi.testCapabilityVersion(version.id)
    if (action === 'publish') await platformApi.publishCapabilityVersion(version.id)
    if (action === 'deprecate') await apiClient.post(`/api/capability-versions/${encodeURIComponent(version.id)}/deprecate`)
    if (editingCapability.value) await loadCapabilityVersions(editingCapability.value.id)
    await load()
    message.success(action === 'test' ? 'Version 校验通过' : action === 'publish' ? 'Version 已发布' : 'Version 已废弃')
  } catch (cause) {
    message.error(getApiErrorMessage(cause))
  } finally {
    saving.value = false
  }
}

function openCredentialRotate(item: CredentialRecord) {
  editingCredential.value = item
  credentialRotateForm.secret = ''
  credentialRotateOpen.value = true
}

async function rotateCredential() {
  if (!editingCredential.value || !credentialRotateForm.secret) return
  saving.value = true
  try {
    await apiClient.post(`/api/credentials/${encodeURIComponent(editingCredential.value.id)}/rotate`, { secret: credentialRotateForm.secret })
    credentialRotateOpen.value = false
    credentialRotateForm.secret = ''
    await load()
    message.success('凭据已轮换，明文不会回显')
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
  saving.value = true
  try {
    const requestSchema = jsonObject(connectorForm.request_schema, 'Request Schema')
    const responseSchema = jsonObject(connectorForm.response_schema, 'Response Schema')
    const connector = await platformApi.createConnector({
      key: connectorForm.key,
      display_name: connectorForm.display_name,
      description: connectorForm.description,
      type: connectorForm.type,
    })
    const instance = await platformApi.createConnectorInstance(connector.id, { name: connectorForm.instance_name, environment: 'production' })
    const revision = await platformApi.createConnectorRevision(instance.id, {
      endpoint: connectorForm.endpoint,
      auth_type: connectorForm.auth_type,
      credential_ref: connectorForm.credential_ref,
      network_zone: connectorForm.network_zone,
      connection_config: connectorForm.auth_type === 'header' ? { auth_header: connectorForm.auth_header } : {},
      timeout_policy: { connect_seconds: 5, read_seconds: 15 },
      retry_policy: { max_retries: 1 },
      health_check_config: {},
    })
    const operation = await platformApi.createConnectorOperation(connector.id, {
      operation_key: connectorForm.operation_key,
      display_name: connectorForm.operation_name || connectorForm.operation_key,
      protocol: connectorForm.type,
      method: connectorForm.type === 'internal_rest' ? connectorForm.method : null,
      path_or_tool: connectorForm.path_or_tool,
      request_schema: requestSchema,
      response_schema: responseSchema,
      request_mapping: {}, response_mapping: {}, error_mapping: {}, side_effect: 'READ_ONLY',
    })
    const capability = await platformApi.createCapability({
      namespace: 'platform', key: connectorForm.capability_key,
      display_name: connectorForm.capability_name, description: connectorForm.description, risk_level: 'LOW',
    })
    const version = await platformApi.createCapabilityVersion(capability.id, {
      version: connectorForm.capability_version,
      input_schema: requestSchema, output_schema: responseSchema, ui_schema: {}, error_schema: {},
      side_effect: 'READ_ONLY', idempotency: 'SAFE_RETRY', cache_policy: {}, default_timeout_ms: 15000, compatibility: {},
    })
    await platformApi.testCapabilityVersion(version.id)
    await platformApi.publishCapabilityVersion(version.id)
    await platformApi.createCapabilityImplementation({
      capability_version_id: version.id,
      connector_operation_id: operation.id,
      connector_instance_revision_id: revision.id,
      mapping_override: {}, priority: 100, routing_weight: 100,
    })
    const health = await platformApi.testConnectorRevision(revision.id)
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
        <AdminGuideLink section="connections" />
        <NButton secondary :loading="loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" @click="wizardOpen = true"><template #icon><NIcon :component="Plus" /></template>创建连接</NButton>
      </template>
    </PageHeader>

    <div v-if="error" class="error-panel" style="margin-bottom: 16px">{{ error }}</div>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="connections" tab="连接">
        <section class="surface panel-flush">
          <div v-if="loading" class="loading-stack" style="padding: 20px"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
          <div v-else-if="connections.length === 0" class="empty-state"><div><NIcon :component="PlugConnected" size="28" /><h3>还没有连接</h3><p>创建 Internal REST 或 MCP 连接后，Capability 才能获得真实实现。</p></div></div>
          <div v-else class="registry-list">
            <div v-for="item in connections" :key="item.id" class="registry-row connection-registry-row">
              <div><strong>{{ item.name }}</strong><span class="mono">{{ item.key }} / {{ item.type }}</span></div>
              <span>{{ item.instances }} 个实例</span><span>{{ item.capability_count }} 个能力</span>
              <StatusTag :status="item.status" /><span class="muted">{{ formatDate(item.updated_at) }}</span>
              <NButton size="small" secondary @click="openConnectionEditor(item)"><template #icon><NIcon :component="Pencil" /></template>管理</NButton>
            </div>
          </div>
        </section>
      </NTabPane>
      <NTabPane name="capabilities" tab="能力">
        <div class="toolbar-row"><span class="muted">Published Version 不允许原地修改。</span><NButton @click="capabilityOpen = true">新建 Capability</NButton></div>
        <section class="surface panel-flush"><div class="registry-list">
          <div v-for="item in capabilities" :key="item.id" class="registry-row capability-registry-row"><div><strong>{{ item.display_name }}</strong><span class="mono">{{ item.namespace }}.{{ item.key }}</span></div><span>{{ item.risk_level }}</span><StatusTag :status="item.status" /><NButton size="small" secondary @click="openCapabilityEditor(item)"><template #icon><NIcon :component="Pencil" /></template>管理</NButton></div>
          <div v-if="!capabilities.length" class="empty-state"><div><h3>暂无 Capability</h3><p>能力用于解耦 Skill 与真实接口。</p></div></div>
        </div></section>
      </NTabPane>
      <NTabPane name="credentials" tab="凭据">
        <div class="toolbar-row"><span class="muted">密钥明文不会从后端返回。</span><NButton @click="credentialOpen = true"><template #icon><NIcon :component="Key" /></template>新增凭据</NButton></div>
        <section class="surface panel-flush"><div class="registry-list">
          <div v-for="item in credentials" :key="item.id" class="registry-row credential-registry-row"><div><strong>{{ item.name }}</strong><span>{{ item.credential_type }}</span></div><span class="mono">{{ item.masked_label }}</span><StatusTag :status="item.rotation_status" /><span>{{ formatDate(item.last_rotated_at) }}</span><NButton size="small" secondary @click="openCredentialRotate(item)"><template #icon><NIcon :component="History" /></template>轮换</NButton></div>
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

    <NModal v-model:show="connectionEditorOpen" preset="card" :title="editingConnection ? `管理连接：${editingConnection.name}` : '管理连接'" style="width: min(1040px, calc(100vw - 32px))" :mask-closable="false">
      <div v-if="detailLoading" class="loading-stack"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
      <NTabs v-else type="line" animated>
        <NTabPane name="base" tab="基础信息">
          <NAlert type="info" :bordered="false">Connector Key 和类型用于稳定引用，创建后不可修改。名称、说明和启停状态可以更新。</NAlert>
          <NForm label-placement="top" style="margin-top:16px"><div class="form-grid"><NFormItem label="显示名称" required><NInput v-model:value="connectionEditForm.display_name" /></NFormItem><NFormItem label="状态"><NSelect v-model:value="connectionEditForm.status" :options="[{label:'Draft',value:'draft'},{label:'Published',value:'published'},{label:'Disabled',value:'disabled'}]" /></NFormItem><NFormItem class="span-2" label="说明"><NInput v-model:value="connectionEditForm.description" type="textarea" /></NFormItem></div></NForm>
          <div class="dialog-actions"><NButton type="primary" :loading="saving" @click="saveConnectionMetadata">保存基础信息</NButton></div>
        </NTabPane>
        <NTabPane name="revision" tab="连接配置 Revision">
          <NAlert type="warning" :bordered="false">Endpoint、认证和超时策略不会覆盖旧配置。保存时创建新 Revision，历史执行仍保留原 Revision。</NAlert>
          <NForm label-placement="top" style="margin-top:16px"><div class="form-grid"><NFormItem class="span-2" label="连接实例"><NSelect :value="activeInstanceId" :options="connectionDetail.instances.map(item => ({label:`${item.name} / ${item.environment} / ${item.health}`,value:item.id}))" @update:value="loadActiveRevision" /></NFormItem><NFormItem class="span-2" label="Endpoint" required><NInput v-model:value="revisionForm.endpoint" placeholder="http://service:8080" /></NFormItem><NFormItem label="网络区域"><NSelect v-model:value="revisionForm.network_zone" :options="[{label:'Internal',value:'internal'},{label:'DMZ',value:'dmz'}]" /></NFormItem><NFormItem label="认证方式"><NSelect v-model:value="revisionForm.auth_type" :options="[{label:'无',value:'none'},{label:'Bearer',value:'bearer'},{label:'自定义 Header',value:'header'}]" /></NFormItem><NFormItem v-if="revisionForm.auth_type !== 'none'" label="加密凭据"><NSelect v-model:value="revisionForm.credential_ref" clearable :options="credentialOptions" /></NFormItem><NFormItem v-if="revisionForm.auth_type === 'header'" label="Header 名称"><NInput v-model:value="revisionForm.auth_header" /></NFormItem><NFormItem label="连接超时（秒）"><NInputNumber v-model:value="revisionForm.connect_seconds" :min="1" :max="300" /></NFormItem><NFormItem label="读取超时（秒）"><NInputNumber v-model:value="revisionForm.read_seconds" :min="1" :max="300" /></NFormItem><NFormItem label="最大重试"><NInputNumber v-model:value="revisionForm.max_retries" :min="0" :max="5" /></NFormItem></div></NForm>
          <div class="dialog-actions"><NButton type="primary" :loading="saving" @click="createConnectionRevision">创建新 Revision 并测试</NButton></div>
        </NTabPane>
        <NTabPane name="operations" tab="Operations">
          <NAlert type="info" :bordered="false">已发布 Operation 参与 Capability 实现，不允许在这里原地改写协议。需要变更协议时创建新的 Connector 和 Operation，再发布新 Capability Version。</NAlert>
          <div class="operation-list"><div v-for="operation in connectorOperations" :key="operation.id"><div><strong>{{ operation.display_name }}</strong><span class="mono">{{ operation.operation_key }} → {{ operation.path_or_tool }}</span></div><StatusTag :status="operation.status" /></div><div v-if="!connectorOperations.length" class="empty-state empty-state-compact"><div><h3>暂无 Operation</h3></div></div></div>
        </NTabPane>
      </NTabs>
      <template #footer><div class="dialog-actions"><NButton @click="connectionEditorOpen = false">关闭</NButton></div></template>
    </NModal>

    <NModal v-model:show="capabilityEditorOpen" preset="card" :title="editingCapability ? `管理 Capability：${editingCapability.display_name}` : '管理 Capability'" style="width: min(1040px, calc(100vw - 32px))" :mask-closable="false">
      <NTabs type="line" animated>
        <NTabPane name="metadata" tab="基础信息">
          <NForm label-placement="top"><div class="form-grid"><NFormItem label="显示名称" required><NInput v-model:value="capabilityEditForm.display_name" /></NFormItem><NFormItem label="风险等级"><NSelect v-model:value="capabilityEditForm.risk_level" :options="['LOW','MEDIUM','HIGH'].map(value => ({label:value,value}))" /></NFormItem><NFormItem label="状态"><NSelect v-model:value="capabilityEditForm.status" :options="capabilityStatusOptions" /></NFormItem><NFormItem class="span-2" label="说明"><NInput v-model:value="capabilityEditForm.description" type="textarea" /></NFormItem></div></NForm>
          <div class="dialog-actions"><NButton type="primary" :loading="saving" @click="saveCapabilityMetadata">保存基础信息</NButton></div>
        </NTabPane>
        <NTabPane name="versions" tab="版本与契约">
          <NAlert type="warning" :bordered="false">Published Version 不可编辑。输入输出契约变化必须创建新 SemVer Version，测试通过后再发布。</NAlert>
          <div class="capability-version-list"><div v-for="version in capabilityVersions" :key="version.id"><div><strong>v{{ version.version }}</strong><span>{{ version.side_effect }} / {{ version.idempotency }} / {{ version.default_timeout_ms }} ms</span></div><StatusTag :status="version.status" /><div class="version-actions"><NButton v-if="version.status === 'draft'" size="tiny" @click="changeCapabilityVersion(version,'test')">测试</NButton><NButton v-if="['draft','testing'].includes(version.status)" size="tiny" type="primary" @click="changeCapabilityVersion(version,'publish')">发布</NButton><NButton v-if="version.status === 'published'" size="tiny" secondary @click="changeCapabilityVersion(version,'deprecate')">废弃</NButton></div></div></div>
          <section class="new-version-panel"><h3>创建新 Draft Version</h3><NForm label-placement="top"><div class="form-grid"><NFormItem label="SemVer"><NInput v-model:value="versionForm.version" placeholder="1.1.0" /></NFormItem><NFormItem label="默认超时（毫秒）"><NInputNumber v-model:value="versionForm.default_timeout_ms" :min="100" :max="300000" /></NFormItem><NFormItem label="副作用"><NSelect v-model:value="versionForm.side_effect" :options="['READ_ONLY','WRITE','DESTRUCTIVE','EXTERNAL_COMMUNICATION','LONG_RUNNING'].map(value=>({label:value,value}))" /></NFormItem><NFormItem label="幂等性"><NSelect v-model:value="versionForm.idempotency" :options="['SAFE_RETRY','IDEMPOTENT','NON_IDEMPOTENT'].map(value=>({label:value,value}))" /></NFormItem><NFormItem label="Input Schema"><NInput v-model:value="versionForm.input_schema" type="textarea" :rows="8" class="mono" /></NFormItem><NFormItem label="Output Schema"><NInput v-model:value="versionForm.output_schema" type="textarea" :rows="8" class="mono" /></NFormItem></div></NForm><div class="dialog-actions"><NButton type="primary" :loading="saving" @click="createNewCapabilityVersion">创建 Draft Version</NButton></div></section>
        </NTabPane>
      </NTabs>
      <template #footer><div class="dialog-actions"><NButton @click="capabilityEditorOpen = false">关闭</NButton></div></template>
    </NModal>

    <NModal v-model:show="credentialRotateOpen" preset="card" :title="editingCredential ? `轮换凭据：${editingCredential.name}` : '轮换凭据'" style="width: min(560px, calc(100vw - 32px))">
      <NAlert type="warning" :bordered="false">新密钥只通过当前请求提交并加密保存，页面不会回显旧密钥或新密钥。</NAlert>
      <NForm label-placement="top" style="margin-top:16px"><NFormItem label="新密钥" required><NInput v-model:value="credentialRotateForm.secret" type="password" show-password-on="click" /></NFormItem></NForm>
      <template #footer><div class="dialog-actions"><NButton @click="credentialRotateOpen = false">取消</NButton><NButton type="primary" :loading="saving" :disabled="!credentialRotateForm.secret" @click="rotateCredential">轮换并加密保存</NButton></div></template>
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
.toolbar-row,.dialog-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.dialog-actions{justify-content:flex-end;margin:0}.registry-list{display:grid}.registry-row{display:grid;gap:16px;align-items:center;padding:15px 20px;border-bottom:1px solid var(--line)}.connection-registry-row{grid-template-columns:minmax(240px,1.6fr) repeat(3,minmax(90px,.5fr)) minmax(100px,.55fr) auto}.capability-registry-row{grid-template-columns:minmax(240px,1.6fr) minmax(90px,.5fr) minmax(110px,.55fr) auto}.credential-registry-row{grid-template-columns:minmax(220px,1.4fr) minmax(140px,.8fr) minmax(100px,.5fr) minmax(130px,.7fr) auto}.registry-row:last-child{border-bottom:0}.registry-row>div{display:grid;gap:4px}.registry-row span{font-size:12px}.compact-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.compact-steps span{padding:10px 12px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}.compact-steps .active{border-color:var(--accent);color:var(--ink);background:var(--accent-soft)}.compact-steps .complete{color:#63c174}.operation-list,.capability-version-list{display:grid;margin-top:16px;border:1px solid var(--line);border-radius:8px;overflow:hidden}.operation-list>div,.capability-version-list>div{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:12px 14px;background:var(--surface-subtle)}.operation-list>div+div,.capability-version-list>div+div{border-top:1px solid var(--line)}.operation-list>div>div,.capability-version-list>div>div{display:grid;gap:3px}.operation-list span,.capability-version-list span{color:var(--muted);font-size:10px}.capability-version-list>div{grid-template-columns:minmax(0,1fr) auto auto}.version-actions{display:flex!important;grid-auto-flow:column;gap:6px!important}.new-version-panel{margin-top:18px;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.new-version-panel h3{margin:0 0 16px;font-size:14px}@media(max-width:900px){.connection-registry-row,.capability-registry-row,.credential-registry-row{grid-template-columns:minmax(0,1fr) auto}.connection-registry-row>:not(:first-child):not(:last-child),.capability-registry-row>:not(:first-child):not(:last-child),.credential-registry-row>:not(:first-child):not(:last-child){display:none}}@media(max-width:760px){.registry-row{grid-template-columns:minmax(0,1fr) auto}.compact-steps{grid-template-columns:1fr 1fr}.capability-version-list>div{grid-template-columns:1fr auto}.version-actions{grid-column:1/-1}}
</style>
