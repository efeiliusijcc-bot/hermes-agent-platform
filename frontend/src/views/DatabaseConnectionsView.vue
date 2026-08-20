<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NIcon, useDialog, useMessage } from 'naive-ui'
import { Database, Plus, Refresh, Settings, TestPipe, Trash } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import type {
  DatabaseConnectionPayload,
  DatabaseConnectionDetail,
  DatabaseConnectionSummary,
  DatabaseDiscovery,
  DatabaseDiscoveredObject,
  DatabaseScopePayload,
} from '@/types/api'

interface ScopeConfig {
  enabled: boolean
  allow_describe: boolean
  allow_query: boolean
  allow_preview: boolean
  allow_aggregate: boolean
  max_rows: number
  statement_timeout_ms: number
  requests_per_minute: number
}

const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref<string | null>(null)
const connections = ref<DatabaseConnectionSummary[]>([])
const wizardOpen = ref(false)
const wizardStep = ref(0)
const discovery = ref<DatabaseDiscovery | null>(null)
const managerOpen = ref(false)
const managerLoading = ref(false)
const managerSaving = ref(false)
const managerTab = ref<'overview' | 'scopes' | 'credential'>('overview')
const activeConnection = ref<DatabaseConnectionDetail | null>(null)
const managedDiscovery = ref<DatabaseDiscovery | null>(null)
const scopeOpen = ref(false)
const scopeDatabase = ref<string | null>(null)
const scopeSelectedObjects = ref<string[]>([])
const selectedObjects = ref<string[]>([])
const scopeConfigs = reactive<Record<string, ScopeConfig>>({})
const steps = ['基础连接', '数据库凭据', '测试与发现', '数据范围']
const form = reactive({
  name: '',
  environment: 'production' as 'development' | 'test' | 'production',
  host: '',
  port: 5432,
  maintenance_database: 'postgres',
  ssl_mode: 'disable' as 'disable' | 'prefer' | 'require' | 'verify-ca' | 'verify-full',
  connect_timeout_seconds: 5,
  username: '',
  password: '',
})
const editForm = reactive({
  name: '',
  environment: 'production' as 'development' | 'test' | 'production',
  host: '',
  port: 5432,
  maintenance_database: 'postgres',
  ssl_mode: 'disable' as 'disable' | 'prefer' | 'require' | 'verify-ca' | 'verify-full',
  connect_timeout_seconds: 5,
})
const credentialForm = reactive({ username: '', password: '' })
const newScope = reactive<ScopeConfig & { name: string }>({
  name: '',
  enabled: true,
  allow_describe: true,
  allow_query: true,
  allow_preview: true,
  allow_aggregate: true,
  max_rows: 200,
  statement_timeout_ms: 5000,
  requests_per_minute: 60,
})

function endpoint() {
  return {
    host: form.host.trim(),
    port: form.port,
    maintenance_database: form.maintenance_database.trim(),
    ssl_mode: form.ssl_mode,
    connect_timeout_seconds: form.connect_timeout_seconds,
  }
}

function editedEndpoint() {
  return {
    host: editForm.host.trim(),
    port: editForm.port,
    maintenance_database: editForm.maintenance_database.trim(),
    ssl_mode: editForm.ssl_mode,
    connect_timeout_seconds: editForm.connect_timeout_seconds,
  }
}

function key(database: string, schema: string, type: 'table' | 'view', name: string) {
  return JSON.stringify([database, schema, type, name])
}

function selected(database: string, schema: string, type: 'table' | 'view', name: string): boolean {
  return selectedObjects.value.includes(key(database, schema, type, name))
}

function toggle(database: string, schema: string, type: 'table' | 'view', name: string, checked: boolean) {
  const value = key(database, schema, type, name)
  selectedObjects.value = checked
    ? Array.from(new Set([...selectedObjects.value, value]))
    : selectedObjects.value.filter((item) => item !== value)
}

function scopeSelected(database: string, schema: string, type: 'table' | 'view', name: string): boolean {
  return scopeSelectedObjects.value.includes(key(database, schema, type, name))
}

function toggleScopeObject(database: string, schema: string, type: 'table' | 'view', name: string, checked: boolean) {
  const value = key(database, schema, type, name)
  scopeSelectedObjects.value = checked
    ? Array.from(new Set([...scopeSelectedObjects.value, value]))
    : scopeSelectedObjects.value.filter((item) => item !== value)
}

function openWizard() {
  wizardStep.value = 0
  discovery.value = null
  selectedObjects.value = []
  Object.keys(scopeConfigs).forEach((item) => delete scopeConfigs[item])
  Object.assign(form, {
    name: '', environment: 'production', host: '', port: 5432, maintenance_database: 'postgres',
    ssl_mode: 'disable', connect_timeout_seconds: 5, username: '', password: '',
  })
  wizardOpen.value = true
}

function populateEditForm(value: DatabaseConnectionDetail) {
  Object.assign(editForm, {
    name: value.name,
    environment: value.environment,
    host: value.endpoint.host,
    port: value.endpoint.port,
    maintenance_database: value.endpoint.maintenance_database,
    ssl_mode: value.endpoint.ssl_mode,
    connect_timeout_seconds: value.endpoint.connect_timeout_seconds,
  })
}

async function openManager(item: DatabaseConnectionSummary) {
  managerOpen.value = true
  managerLoading.value = true
  managerTab.value = 'overview'
  managedDiscovery.value = null
  activeConnection.value = null
  Object.assign(credentialForm, { username: '', password: '' })
  try {
    const detail = await platformApi.getDatabaseConnection(item.id)
    activeConnection.value = detail
    populateEditForm(detail)
  } catch (cause) {
    managerOpen.value = false
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    managerLoading.value = false
  }
}

function closeManager() {
  managerOpen.value = false
  activeConnection.value = null
  managedDiscovery.value = null
  Object.assign(credentialForm, { username: '', password: '' })
}

async function load() {
  loading.value = true
  error.value = null
  try {
    connections.value = await platformApi.listDatabaseConnections()
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

function next() {
  if (wizardStep.value === 0) {
    if (!form.name.trim() || !form.host.trim() || !form.maintenance_database.trim()) {
      message.warning('请填写连接名称、主机和维护库')
      return
    }
  }
  if (wizardStep.value === 1 && (!form.username.trim() || !form.password)) {
    message.warning('请填写数据库用户名和密码')
    return
  }
  if (wizardStep.value === 2 && !discovery.value) {
    message.warning('请先执行连接测试和资源发现')
    return
  }
  wizardStep.value = Math.min(3, wizardStep.value + 1)
}

async function testTemporary() {
  testing.value = true
  try {
    const result = await platformApi.testDatabaseConnection(
      endpoint(),
      { username: form.username.trim(), password: form.password },
    )
    discovery.value = result
    selectedObjects.value = []
    Object.keys(scopeConfigs).forEach((item) => delete scopeConfigs[item])
    result.databases.filter((item) => item.status === 'READY').forEach((database) => {
      scopeConfigs[database.name] = {
        enabled: true,
        allow_describe: true,
        allow_query: true,
        allow_preview: true,
        allow_aggregate: true,
        max_rows: 200,
        statement_timeout_ms: 5000,
        requests_per_minute: 60,
      }
      database.schemas.forEach((schema) => {
        schema.tables.forEach((item) => selectedObjects.value.push(key(database.name, schema.name, 'table', item.name)))
        schema.views.forEach((item) => selectedObjects.value.push(key(database.name, schema.name, 'view', item.name)))
      })
    })
    message.success(`连接正常，发现 ${result.databases.length} 个数据库`)
  } catch (cause) {
    discovery.value = null
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    testing.value = false
  }
}

function buildScopes(): DatabaseScopePayload[] {
  const result: DatabaseScopePayload[] = []
  for (const database of discovery.value?.databases || []) {
    const config = scopeConfigs[database.name]
    if (!config?.enabled || database.status !== 'READY') continue
    const schemas = database.schemas.map((schema) => ({
      name: schema.name,
      tables: schema.tables.filter((item) => selected(database.name, schema.name, 'table', item.name)).map((item) => item.name),
      views: schema.views.filter((item) => selected(database.name, schema.name, 'view', item.name)).map((item) => item.name),
    })).filter((schema) => schema.tables.length || schema.views.length)
    if (!schemas.length) throw new Error(`数据库 ${database.name} 至少选择一个表或视图`)
    result.push({
      database: database.name,
      name: `${form.name} / ${database.name}`,
      schemas,
      allow_describe: config.allow_describe,
      allow_query: config.allow_query,
      allow_preview: config.allow_preview,
      allow_aggregate: config.allow_aggregate,
      max_rows: config.max_rows,
      statement_timeout_ms: config.statement_timeout_ms,
      lock_timeout_ms: 1000,
      max_response_bytes: 2_097_152,
      requests_per_minute: config.requests_per_minute,
    })
  }
  if (!result.length) throw new Error('至少启用一个数据库 Scope')
  return result
}

async function save() {
  saving.value = true
  try {
    const payload: DatabaseConnectionPayload = {
      name: form.name.trim(),
      environment: form.environment,
      endpoint: endpoint(),
      credential: { username: form.username.trim(), password: form.password },
      scopes: buildScopes(),
    }
    await platformApi.createDatabaseConnection(payload)
    form.password = ''
    wizardOpen.value = false
    await load()
    message.success('数据库连接、资源范围和只读能力已保存')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    saving.value = false
  }
}

async function testSaved(item: DatabaseConnectionSummary) {
  testing.value = true
  try {
    const result = await platformApi.testSavedDatabaseConnection(item.id)
    await load()
    message.success(`${item.name} 测试通过，发现 ${result.databases.length} 个数据库`)
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    testing.value = false
  }
}

async function testManaged() {
  if (!activeConnection.value) return
  testing.value = true
  try {
    managedDiscovery.value = await platformApi.testSavedDatabaseConnection(activeConnection.value.id)
    activeConnection.value = await platformApi.getDatabaseConnection(activeConnection.value.id)
    await load()
    message.success('连接测试通过，资源树已刷新')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    testing.value = false
  }
}

async function discoverManaged() {
  if (!activeConnection.value) return
  testing.value = true
  try {
    managedDiscovery.value = await platformApi.discoverDatabaseConnection(activeConnection.value.id)
    activeConnection.value = await platformApi.getDatabaseConnection(activeConnection.value.id)
    message.success(`重新发现完成，共 ${managedDiscovery.value.databases.length} 个数据库`)
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    testing.value = false
  }
}

async function saveManagedConnection() {
  if (!activeConnection.value) return
  if (!editForm.name.trim() || !editForm.host.trim() || !editForm.maintenance_database.trim()) {
    message.warning('请填写连接名称、主机和维护库')
    return
  }
  managerSaving.value = true
  try {
    const endpointChanged = JSON.stringify(editedEndpoint()) !== JSON.stringify(activeConnection.value.endpoint)
    const detail = await platformApi.updateDatabaseConnection(
      activeConnection.value.id,
      {
        name: editForm.name.trim(),
        environment: editForm.environment,
        ...(endpointChanged ? { endpoint: editedEndpoint() } : {}),
      },
    )
    activeConnection.value = detail
    populateEditForm(detail)
    if (endpointChanged) managedDiscovery.value = null
    await load()
    message.success(endpointChanged ? '已测试新配置并创建 Connector Revision' : '连接信息已更新')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    managerSaving.value = false
  }
}

async function setManagedEnabled(enabled: boolean) {
  if (!activeConnection.value) return
  managerSaving.value = true
  try {
    activeConnection.value = await platformApi.updateDatabaseConnection(
      activeConnection.value.id,
      { enabled },
    )
    await load()
    message.success(enabled ? '数据库连接已启用' : '数据库连接已停用')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    managerSaving.value = false
  }
}

async function rotateCredential() {
  if (!activeConnection.value) return
  if (!credentialForm.username.trim() || !credentialForm.password) {
    message.warning('请填写新的数据库用户名和密码')
    return
  }
  managerSaving.value = true
  try {
    await platformApi.replaceDatabaseCredential(
      activeConnection.value.id,
      { username: credentialForm.username.trim(), password: credentialForm.password },
    )
    Object.assign(credentialForm, { username: '', password: '' })
    activeConnection.value = await platformApi.getDatabaseConnection(activeConnection.value.id)
    await load()
    message.success('新凭据连接测试通过并已完成轮换，旧连接池已失效')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    credentialForm.password = ''
    managerSaving.value = false
  }
}

function openScopeCreator(database: string) {
  if (!managedDiscovery.value || !activeConnection.value) return
  const source = managedDiscovery.value.databases.find((item) => item.name === database)
  if (!source || source.status !== 'READY') return
  scopeDatabase.value = database
  scopeSelectedObjects.value = []
  source.schemas.forEach((schema) => {
    schema.tables.forEach((item) => scopeSelectedObjects.value.push(key(database, schema.name, 'table', item.name)))
    schema.views.forEach((item) => scopeSelectedObjects.value.push(key(database, schema.name, 'view', item.name)))
  })
  Object.assign(newScope, {
    name: `${activeConnection.value.name} / ${database}`,
    enabled: true,
    allow_describe: true,
    allow_query: true,
    allow_preview: true,
    allow_aggregate: true,
    max_rows: 200,
    statement_timeout_ms: 5000,
    requests_per_minute: 60,
  })
  scopeOpen.value = true
}

function managedScopePayload(): DatabaseScopePayload {
  if (!managedDiscovery.value || !scopeDatabase.value) throw new Error('请先选择数据库')
  const database = managedDiscovery.value.databases.find((item) => item.name === scopeDatabase.value)
  if (!database) throw new Error('发现结果中不存在该数据库')
  const schemas = database.schemas.map((schema) => ({
    name: schema.name,
    tables: schema.tables.filter((item) => scopeSelected(database.name, schema.name, 'table', item.name)).map((item) => item.name),
    views: schema.views.filter((item) => scopeSelected(database.name, schema.name, 'view', item.name)).map((item) => item.name),
  })).filter((schema) => schema.tables.length || schema.views.length)
  if (!schemas.length) throw new Error('至少选择一个表或视图')
  return {
    database: database.name,
    name: newScope.name.trim() || `${activeConnection.value?.name || '数据库'} / ${database.name}`,
    schemas,
    allow_describe: newScope.allow_describe,
    allow_query: newScope.allow_query,
    allow_preview: newScope.allow_preview,
    allow_aggregate: newScope.allow_aggregate,
    max_rows: newScope.max_rows,
    statement_timeout_ms: newScope.statement_timeout_ms,
    lock_timeout_ms: 1000,
    max_response_bytes: 2_097_152,
    requests_per_minute: newScope.requests_per_minute,
  }
}

async function saveManagedScope() {
  if (!activeConnection.value) return
  managerSaving.value = true
  try {
    await platformApi.createDatabaseScope(activeConnection.value.id, managedScopePayload())
    scopeOpen.value = false
    activeConnection.value = await platformApi.getDatabaseConnection(activeConnection.value.id)
    await load()
    message.success('新的不可变 Resource Scope Revision 已创建')
  } catch (cause) {
    message.error(getApiErrorMessage(cause), { duration: 8000 })
  } finally {
    managerSaving.value = false
  }
}

function disable(item: DatabaseConnectionSummary) {
  dialog.warning({
    title: '停用数据库连接',
    content: `停用 ${item.name} 后，所有绑定该连接的 Agent 将立即不能继续查询。历史记录不会删除。`,
    positiveText: '确认停用',
    negativeText: '取消',
    onPositiveClick: async () => {
      await platformApi.disableDatabaseConnection(item.id)
      await load()
      message.success('数据库连接已停用')
    },
  })
}

function columnsSummary(item: DatabaseDiscoveredObject) {
  return item.columns.map((column) => `${column.name} ${column.type}`).join(' · ')
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="数据库连接" description="管理内网 PostgreSQL、发现数据资源，并为 Agent 冻结只读数据范围。">
      <template #actions>
        <NButton secondary :loading="loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" @click="openWizard"><template #icon><NIcon :component="Plus" /></template>创建数据库连接</NButton>
      </template>
    </PageHeader>
    <div v-if="error" class="error-panel" style="margin-bottom:16px">{{ error }}</div>
    <section class="surface panel-flush">
      <div v-if="loading" class="loading-stack" style="padding:20px"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
      <div v-else-if="!connections.length" class="empty-state"><div><NIcon :component="Database" size="30" /><h3>暂无数据库连接</h3><p>先将 postgres-mcp 容器加入目标数据库网络，再通过向导完成配置。</p></div></div>
      <div v-else class="connection-list">
        <article v-for="item in connections" :key="item.id" class="connection-row">
          <div><strong>{{ item.name }}</strong><span class="mono">{{ item.host }}:{{ item.port }} / {{ item.maintenance_database }}</span></div>
          <div><span>{{ item.environment }}</span><small>{{ item.scope_count }} 个数据库 Scope</small></div>
          <StatusTag :status="item.status" />
          <span class="muted">{{ formatDate(item.updated_at) }}</span>
          <div class="row-actions"><NButton size="small" secondary @click="openManager(item)"><template #icon><NIcon :component="Settings" /></template>管理</NButton><NButton size="small" secondary :loading="testing" @click="testSaved(item)"><template #icon><NIcon :component="TestPipe" /></template>测试</NButton><NButton size="small" quaternary type="error" :disabled="item.status==='disabled'" @click="disable(item)"><template #icon><NIcon :component="Trash" /></template>停用</NButton></div>
        </article>
      </div>
    </section>

    <NModal v-model:show="wizardOpen" preset="card" title="创建 PostgreSQL 连接" style="width:min(1120px,calc(100vw - 32px))" :mask-closable="false">
      <nav class="db-steps" aria-label="数据库连接创建步骤"><span v-for="(title,index) in steps" :key="title" :class="{active:index===wizardStep,complete:index<wizardStep}">{{ index + 1 }}. {{ title }}</span></nav>
      <div class="wizard-body">
        <NForm v-if="wizardStep===0" label-placement="top"><div class="form-grid">
          <NFormItem label="连接名称" required><NInput v-model:value="form.name" placeholder="业务知识库" /></NFormItem>
          <NFormItem label="环境"><NSelect v-model:value="form.environment" :options="[{label:'开发',value:'development'},{label:'测试',value:'test'},{label:'生产',value:'production'}]" /></NFormItem>
          <NFormItem label="主机 / 容器名" required><NInput v-model:value="form.host" placeholder="business-postgres" /></NFormItem>
          <NFormItem label="端口"><NInputNumber v-model:value="form.port" :min="1" :max="65535" /></NFormItem>
          <NFormItem label="维护库"><NInput v-model:value="form.maintenance_database" /></NFormItem>
          <NFormItem label="SSL 模式"><NSelect v-model:value="form.ssl_mode" :options="['disable','prefer','require','verify-ca','verify-full'].map(value=>({label:value,value}))" /></NFormItem>
          <NFormItem label="连接超时（秒）"><NInputNumber v-model:value="form.connect_timeout_seconds" :min="1" :max="60" /></NFormItem>
          <NAlert class="span-2" type="info" :bordered="false">容器间访问请填写 PostgreSQL 容器名，不要填写 127.0.0.1。平台不会修改 Docker 网络。</NAlert>
        </div></NForm>
        <NForm v-else-if="wizardStep===1" label-placement="top"><div class="form-grid credential-grid">
          <NFormItem label="数据库用户名" required><NInput v-model:value="form.username" autocomplete="off" /></NFormItem>
          <NFormItem label="数据库密码" required><NInput v-model:value="form.password" type="password" show-password-on="click" autocomplete="new-password" /></NFormItem>
          <NAlert class="span-2" type="info" :bordered="false">密码通过内网提交并加密保存，保存后前端不再回显；模型、Trace 和 Artifact 均不会获得密码。</NAlert>
        </div></NForm>
        <div v-else-if="wizardStep===2" class="test-stage">
          <div class="test-toolbar"><div><h3>连接测试与资源发现</h3><p>一次检查连接，并读取所有可访问数据库、Schema、表、视图和字段。</p></div><NButton type="primary" :loading="testing" @click="testTemporary"><template #icon><NIcon :component="TestPipe" /></template>开始测试</NButton></div>
          <div v-if="discovery" class="discovery-result"><div class="result-summary"><StatusTag :status="discovery.status" /><strong>{{ discovery.server.version }}</strong><span>{{ discovery.latency_ms }} ms</span><span>{{ discovery.databases.length }} 个数据库</span></div><div class="check-grid"><div v-for="check in discovery.checks" :key="check.name"><strong>✓ {{ check.name }}</strong><span>{{ check.detail || '通过' }}</span></div></div><NAlert v-for="warning in discovery.warnings" :key="warning" type="warning" :bordered="false">{{ warning }}</NAlert></div>
          <div v-else class="empty-state compact"><div><NIcon :component="TestPipe" size="28" /><h3>等待测试</h3><p>测试不会保存当前密码或连接配置。</p></div></div>
        </div>
        <div v-else class="scope-stage">
          <NAlert type="info" :bordered="false" style="margin-bottom:14px">每个启用的数据库形成独立不可变 Scope。字段只用于查看结构，首版授权粒度为 Schema、表和视图。</NAlert>
          <article v-for="database in discovery?.databases || []" :key="database.name" class="database-card" :class="{unavailable:database.status!=='READY'}">
            <header><NCheckbox v-if="scopeConfigs[database.name]" v-model:checked="scopeConfigs[database.name].enabled" :disabled="database.status!=='READY'"><strong>{{ database.name }}</strong></NCheckbox><strong v-else>{{ database.name }}</strong><StatusTag :status="database.status" /></header>
            <template v-if="scopeConfigs[database.name]"><div class="scope-policy"><NCheckbox v-model:checked="scopeConfigs[database.name].allow_describe">查看结构</NCheckbox><NCheckbox v-model:checked="scopeConfigs[database.name].allow_preview">预览</NCheckbox><NCheckbox v-model:checked="scopeConfigs[database.name].allow_query">查询</NCheckbox><NCheckbox v-model:checked="scopeConfigs[database.name].allow_aggregate">聚合</NCheckbox><label>最大行数 <NInputNumber v-model:value="scopeConfigs[database.name].max_rows" :min="1" :max="10000" size="small" /></label><label>超时 ms <NInputNumber v-model:value="scopeConfigs[database.name].statement_timeout_ms" :min="100" :max="300000" size="small" /></label><label>每分钟 <NInputNumber v-model:value="scopeConfigs[database.name].requests_per_minute" :min="1" :max="10000" size="small" /></label></div>
              <div class="schema-tree"><section v-for="schema in database.schemas" :key="schema.name"><h4>{{ schema.name }}</h4><div class="object-list"><label v-for="item in schema.tables" :key="`t-${item.name}`"><NCheckbox :checked="selected(database.name,schema.name,'table',item.name)" :disabled="!scopeConfigs[database.name].enabled" @update:checked="(value: boolean)=>toggle(database.name,schema.name,'table',item.name,value)"><strong>{{ item.name }}</strong><span>表</span></NCheckbox><small>{{ columnsSummary(item) }}</small></label><label v-for="item in schema.views" :key="`v-${item.name}`"><NCheckbox :checked="selected(database.name,schema.name,'view',item.name)" :disabled="!scopeConfigs[database.name].enabled" @update:checked="(value: boolean)=>toggle(database.name,schema.name,'view',item.name,value)"><strong>{{ item.name }}</strong><span>视图</span></NCheckbox><small>{{ columnsSummary(item) }}</small></label></div></section></div>
            </template>
          </article>
        </div>
      </div>
      <template #footer><div class="wizard-actions"><NButton @click="wizardOpen=false">取消</NButton><span /><NButton v-if="wizardStep>0" @click="wizardStep-=1">上一步</NButton><NButton v-if="wizardStep<3" type="primary" @click="next">下一步</NButton><NButton v-else type="primary" :loading="saving" @click="save">保存连接与 Scope</NButton></div></template>
    </NModal>

    <NModal :show="managerOpen" preset="card" :title="activeConnection ? `管理连接 · ${activeConnection.name}` : '管理数据库连接'" style="width:min(1180px,calc(100vw - 32px))" :mask-closable="false" @update:show="(value:boolean)=>{if(!value)closeManager()}">
      <div v-if="managerLoading" class="loading-stack manager-loading"><div v-for="item in 6" :key="item" class="skeleton-line" /></div>
      <template v-else-if="activeConnection">
        <div class="manager-summary">
          <div><span>当前状态</span><StatusTag :status="activeConnection.status" /></div>
          <div><span>Connector Revision</span><strong class="mono">{{ activeConnection.current_revision_id.slice(0,8) }}</strong></div>
          <div><span>数据库范围</span><strong>{{ activeConnection.scopes.length }} 个 Scope</strong></div>
          <div><span>凭据</span><strong>{{ activeConnection.credential.masked_username || '未配置' }}</strong></div>
        </div>
        <NTabs v-model:value="managerTab" type="line" animated>
          <NTabPane name="overview" tab="连接配置">
            <div class="manager-pane">
              <NAlert type="info" :bordered="false">修改主机、端口、维护库、SSL 或超时会先用现有凭据真实测试，成功后创建新的不可变 Connector Revision；历史 Execution 仍引用旧 Revision。</NAlert>
              <NForm label-placement="top"><div class="form-grid">
                <NFormItem label="连接名称"><NInput v-model:value="editForm.name" /></NFormItem>
                <NFormItem label="环境"><NSelect v-model:value="editForm.environment" :options="[{label:'开发',value:'development'},{label:'测试',value:'test'},{label:'生产',value:'production'}]" /></NFormItem>
                <NFormItem label="主机 / 容器名"><NInput v-model:value="editForm.host" /></NFormItem>
                <NFormItem label="端口"><NInputNumber v-model:value="editForm.port" :min="1" :max="65535" /></NFormItem>
                <NFormItem label="维护库"><NInput v-model:value="editForm.maintenance_database" /></NFormItem>
                <NFormItem label="SSL 模式"><NSelect v-model:value="editForm.ssl_mode" :options="['disable','prefer','require','verify-ca','verify-full'].map(value=>({label:value,value}))" /></NFormItem>
                <NFormItem label="连接超时（秒）"><NInputNumber v-model:value="editForm.connect_timeout_seconds" :min="1" :max="60" /></NFormItem>
              </div></NForm>
              <div class="manager-actions"><NButton :loading="testing" @click="testManaged"><template #icon><NIcon :component="TestPipe" /></template>测试当前 Revision</NButton><span /><NButton v-if="activeConnection.enabled" type="error" secondary :loading="managerSaving" @click="setManagedEnabled(false)">停用连接</NButton><NButton v-else type="success" secondary :loading="managerSaving" @click="setManagedEnabled(true)">重新启用</NButton><NButton type="primary" :loading="managerSaving" @click="saveManagedConnection">保存配置</NButton></div>
            </div>
          </NTabPane>
          <NTabPane name="scopes" tab="资源与 Scope">
            <div class="manager-pane">
              <div class="scope-toolbar"><div><strong>不可变数据范围</strong><p>重新发现只更新资源目录；已有 Scope Revision 和历史绑定不会被覆盖。</p></div><div><NButton :loading="testing" @click="testManaged">测试并发现</NButton><NButton type="primary" secondary :loading="testing" @click="discoverManaged">重新发现资源</NButton></div></div>
              <div v-if="activeConnection.scopes.length" class="saved-scope-list">
                <article v-for="scope in activeConnection.scopes" :key="scope.id">
                  <header><div><strong>{{ scope.name }}</strong><span class="mono">Revision {{ scope.revision }} · {{ scope.database }}</span></div><span class="mono muted">{{ scope.digest.slice(0,12) }}</span></header>
                  <div class="scope-facts"><span>结构 {{ scope.definition.permissions.describe ? '允许' : '禁止' }}</span><span>预览 {{ scope.definition.permissions.preview ? '允许' : '禁止' }}</span><span>查询 {{ scope.definition.permissions.query ? '允许' : '禁止' }}</span><span>最大 {{ scope.definition.limits.max_rows }} 行</span><span>超时 {{ scope.definition.limits.statement_timeout_ms }} ms</span></div>
                  <div class="saved-schema-list"><div v-for="(schema,schemaName) in scope.definition.schemas" :key="schemaName"><strong>{{ schemaName }}</strong><span>表：{{ schema.tables.join('、') || '无' }}</span><span>视图：{{ schema.views.join('、') || '无' }}</span></div></div>
                </article>
              </div>
              <div v-else class="empty-state compact"><div><NIcon :component="Database" size="28" /><h3>尚未创建数据库 Scope</h3><p>先测试或重新发现资源，再为某个数据库创建只读范围。</p></div></div>
              <template v-if="managedDiscovery">
                <NAlert v-for="warning in managedDiscovery.warnings" :key="warning" type="warning" :bordered="false">{{ warning }}</NAlert>
                <div class="managed-databases">
                  <article v-for="database in managedDiscovery.databases" :key="database.name" class="managed-database-card">
                    <header><div><strong>{{ database.name }}</strong><span>{{ database.schemas.length }} 个 Schema</span></div><div><StatusTag :status="database.status" /><NButton v-if="database.status==='READY'" size="small" type="primary" secondary @click="openScopeCreator(database.name)"><template #icon><NIcon :component="Plus" /></template>新增 Scope</NButton></div></header>
                    <p v-if="database.error" class="error-text">{{ database.error }}</p>
                    <div v-else class="discovery-schema-grid"><section v-for="schema in database.schemas" :key="schema.name"><strong>{{ schema.name }}</strong><span>{{ schema.tables.length }} 表 · {{ schema.views.length }} 视图</span><small>{{ [...schema.tables,...schema.views].map(item=>item.name).join('、') || '无对象' }}</small></section></div>
                  </article>
                </div>
              </template>
            </div>
          </NTabPane>
          <NTabPane name="credential" tab="凭据轮换">
            <div class="manager-pane credential-pane">
              <NAlert type="warning" :bordered="false">平台不会回显现有密码。轮换时必须同时提交用户名和新密码；新凭据真实连接测试成功后才替换旧凭据并关闭旧连接池。</NAlert>
              <div class="credential-status"><span>当前用户</span><strong>{{ activeConnection.credential.masked_username || '未配置' }}</strong><span>最近轮换</span><strong>{{ activeConnection.credential.password_updated_at ? formatDate(activeConnection.credential.password_updated_at) : '暂无记录' }}</strong></div>
              <NForm label-placement="top"><div class="form-grid credential-grid"><NFormItem label="新用户名" required><NInput v-model:value="credentialForm.username" autocomplete="off" /></NFormItem><NFormItem label="新密码" required><NInput v-model:value="credentialForm.password" type="password" show-password-on="click" autocomplete="new-password" /></NFormItem></div></NForm>
              <div class="manager-actions"><span /><NButton type="primary" :loading="managerSaving" @click="rotateCredential">测试并轮换凭据</NButton></div>
            </div>
          </NTabPane>
        </NTabs>
      </template>
      <template #footer><div class="wizard-actions"><span /><NButton @click="closeManager">关闭</NButton></div></template>
    </NModal>

    <NModal :show="scopeOpen" preset="card" :title="`新增数据库 Scope · ${scopeDatabase || ''}`" style="width:min(1080px,calc(100vw - 32px))" :mask-closable="false" @update:show="(value:boolean)=>{scopeOpen=value}">
      <div v-if="scopeDatabase && managedDiscovery" class="scope-stage">
        <NAlert type="info" :bordered="false">保存后生成新的 Resource Scope Revision。一个 Scope 只对应一个物理数据库，Agent 不能在查询中切换数据库。</NAlert>
        <NForm label-placement="top"><div class="form-grid scope-basics"><NFormItem label="Scope 名称"><NInput v-model:value="newScope.name" /></NFormItem><NFormItem label="最大返回行数"><NInputNumber v-model:value="newScope.max_rows" :min="1" :max="10000" /></NFormItem><NFormItem label="查询超时 ms"><NInputNumber v-model:value="newScope.statement_timeout_ms" :min="100" :max="300000" /></NFormItem><NFormItem label="每分钟调用次数"><NInputNumber v-model:value="newScope.requests_per_minute" :min="1" :max="10000" /></NFormItem></div></NForm>
        <div class="scope-policy"><NCheckbox v-model:checked="newScope.allow_describe">查看结构</NCheckbox><NCheckbox v-model:checked="newScope.allow_preview">预览</NCheckbox><NCheckbox v-model:checked="newScope.allow_query">查询</NCheckbox><NCheckbox v-model:checked="newScope.allow_aggregate">聚合</NCheckbox></div>
        <template v-for="database in managedDiscovery.databases.filter(item=>item.name===scopeDatabase)" :key="database.name"><div class="schema-tree"><section v-for="schema in database.schemas" :key="schema.name"><h4>{{ schema.name }}</h4><div class="object-list"><label v-for="item in schema.tables" :key="`managed-t-${item.name}`"><NCheckbox :checked="scopeSelected(database.name,schema.name,'table',item.name)" @update:checked="(value:boolean)=>toggleScopeObject(database.name,schema.name,'table',item.name,value)"><strong>{{ item.name }}</strong><span>表</span></NCheckbox><small>{{ columnsSummary(item) }}</small></label><label v-for="item in schema.views" :key="`managed-v-${item.name}`"><NCheckbox :checked="scopeSelected(database.name,schema.name,'view',item.name)" @update:checked="(value:boolean)=>toggleScopeObject(database.name,schema.name,'view',item.name,value)"><strong>{{ item.name }}</strong><span>视图</span></NCheckbox><small>{{ columnsSummary(item) }}</small></label></div></section></div></template>
      </div>
      <template #footer><div class="wizard-actions"><NButton @click="scopeOpen=false">取消</NButton><span /><NButton type="primary" :loading="managerSaving" @click="saveManagedScope">创建 Scope Revision</NButton></div></template>
    </NModal>
  </div>
</template>

<style scoped>
.connection-list{display:grid}.connection-row{display:grid;grid-template-columns:minmax(220px,1.5fr) minmax(130px,.65fr) 110px 150px auto;gap:16px;align-items:center;padding:16px 20px;border-bottom:1px solid var(--line)}.connection-row:last-child{border-bottom:0}.connection-row>div{display:grid;gap:4px}.connection-row span,.connection-row small{font-size:12px}.row-actions{display:flex!important;grid-auto-flow:column;flex-wrap:wrap;justify-content:end}.db-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.db-steps span{padding:11px 13px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}.db-steps .active{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}.db-steps .complete{color:#63c174}.wizard-body{min-height:480px;padding-top:22px}.credential-grid{max-width:720px}.test-stage,.scope-stage{display:grid;gap:14px}.test-toolbar,.result-summary,.database-card>header,.wizard-actions{display:flex;align-items:center;gap:14px}.test-toolbar,.database-card>header{justify-content:space-between}.test-toolbar h3,.test-toolbar p{margin:0}.test-toolbar p{margin-top:5px;color:var(--muted);font-size:13px}.discovery-result{display:grid;gap:14px}.check-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.check-grid>div{display:grid;gap:4px;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.check-grid span{color:var(--muted);font-size:12px}.database-card{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface)}.database-card>header{padding:14px 16px;border-bottom:1px solid var(--line)}.database-card.unavailable{opacity:.65}.scope-policy{display:flex;flex-wrap:wrap;align-items:center;gap:14px;padding:13px 16px;background:var(--surface-subtle)}.scope-policy label{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}.schema-tree{display:grid;gap:12px;padding:14px 16px}.schema-tree section{display:grid;gap:8px}.schema-tree h4{margin:0;color:var(--muted);font-size:12px;text-transform:uppercase}.object-list{display:grid;grid-template-columns:1fr 1fr;gap:8px}.object-list>label{display:grid;gap:5px;padding:10px 12px;border:1px solid var(--line);border-radius:7px}.object-list small{overflow:hidden;color:var(--muted);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.object-list span{margin-left:7px;color:var(--muted);font-size:11px}.wizard-actions span{flex:1}.manager-loading{min-height:420px;padding:24px}.manager-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}.manager-summary>div{display:grid;gap:7px;padding:13px 14px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.manager-summary span{color:var(--muted);font-size:11px}.manager-pane{display:grid;gap:18px;min-height:440px;padding:14px 2px}.manager-actions{display:flex;align-items:center;gap:10px}.manager-actions>span{flex:1}.scope-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px}.scope-toolbar p{margin:5px 0 0;color:var(--muted);font-size:12px}.scope-toolbar>div:last-child{display:flex;gap:8px}.saved-scope-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.saved-scope-list>article{display:grid;gap:12px;padding:14px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.saved-scope-list header,.managed-database-card>header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.saved-scope-list header>div,.managed-database-card header>div{display:grid;gap:4px}.saved-scope-list header span,.managed-database-card header span{font-size:11px}.scope-facts{display:flex;flex-wrap:wrap;gap:6px}.scope-facts span{padding:4px 7px;border-radius:5px;background:var(--surface-subtle);color:var(--muted);font-size:10px}.saved-schema-list{display:grid;gap:8px}.saved-schema-list>div{display:grid;gap:3px;padding-top:8px;border-top:1px solid var(--line)}.saved-schema-list span{overflow-wrap:anywhere;color:var(--muted);font-size:11px}.managed-databases{display:grid;gap:10px}.managed-database-card{display:grid;gap:12px;padding:14px;border:1px solid var(--line);border-radius:9px}.managed-database-card header>div:last-child{display:flex;align-items:center;gap:8px}.discovery-schema-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.discovery-schema-grid section{display:grid;gap:4px;padding:10px;border-radius:7px;background:var(--surface-subtle)}.discovery-schema-grid span,.discovery-schema-grid small{color:var(--muted);font-size:11px}.discovery-schema-grid small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.error-text{margin:0;color:var(--danger);font-size:12px}.credential-pane{max-width:780px}.credential-status{display:grid;grid-template-columns:130px 1fr 130px 1fr;gap:10px;align-items:center;padding:14px;border:1px solid var(--line);border-radius:8px}.credential-status span{color:var(--muted);font-size:12px}.scope-basics{grid-template-columns:repeat(4,1fr)}@media(max-width:900px){.connection-row{grid-template-columns:1fr 1fr}.check-grid,.object-list,.saved-scope-list,.manager-summary{grid-template-columns:1fr 1fr}.discovery-schema-grid{grid-template-columns:1fr 1fr}.scope-basics{grid-template-columns:1fr 1fr}}@media(max-width:680px){.db-steps{grid-template-columns:1fr 1fr}.connection-row,.manager-summary,.saved-scope-list,.discovery-schema-grid,.scope-basics{grid-template-columns:1fr}.scope-policy{align-items:flex-start;flex-direction:column}.scope-toolbar{align-items:flex-start;flex-direction:column}.credential-status{grid-template-columns:1fr}.manager-actions{flex-wrap:wrap}.manager-actions>span{display:none}}
</style>
