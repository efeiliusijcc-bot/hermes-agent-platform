<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NCheckbox,
  NForm,
  NFormItem,
  NIcon,
  NInputNumber,
  NModal,
  NTabPane,
  NTabs,
  useDialog,
  useMessage,
} from 'naive-ui'
import { Database, Plus, Refresh, Settings, TestPipe, Trash } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import AdminGuideLink from '@/components/AdminGuideLink.vue'
import StatusTag from '@/components/StatusTag.vue'
import DatabaseObjectBrowser from '@/components/database/DatabaseObjectBrowser.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'
import type {
  DatabaseConnectionPayload,
  DatabaseConnectionDetail,
  DatabaseConnectionSummary,
  DatabaseDiscovery,
  DatabaseScopePayload,
  DatabaseScopeRecord,
  DatabaseType,
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
const managerTab = ref<'overview' | 'access' | 'credential'>('overview')
const activeConnection = ref<DatabaseConnectionDetail | null>(null)
const managedDiscovery = ref<DatabaseDiscovery | null>(null)
const wizardDatabaseName = ref<string | null>(null)
const managedDatabaseName = ref<string | null>(null)
const scopeOpen = ref(false)
const scopeDatabase = ref<string | null>(null)
const scopeSelectedObjects = ref<string[]>([])
const selectedObjects = ref<string[]>([])
const scopeConfigs = reactive<Record<string, ScopeConfig>>({})
const steps = ['基础连接', '数据库凭据', '测试与发现', '数据范围']
const databaseTypeOptions: Array<{ label: string; value: DatabaseType; port: number | null; maintenance: string }> = [
  { label: 'PostgreSQL', value: 'postgresql', port: 5432, maintenance: 'postgres' },
  { label: 'MySQL', value: 'mysql', port: 3306, maintenance: 'mysql' },
  { label: 'MariaDB', value: 'mariadb', port: 3306, maintenance: 'mysql' },
  { label: 'Apache Doris', value: 'doris', port: 9030, maintenance: 'information_schema' },
  { label: 'StarRocks', value: 'starrocks', port: 9030, maintenance: 'information_schema' },
  { label: 'SQL Server', value: 'sqlserver', port: 1433, maintenance: 'master' },
  { label: 'Oracle', value: 'oracle', port: 1521, maintenance: 'ORCL' },
  { label: '达梦 DM', value: 'dm', port: 5236, maintenance: 'DM' },
  { label: 'ClickHouse', value: 'clickhouse', port: 8123, maintenance: 'default' },
  { label: 'Elasticsearch', value: 'elasticsearch', port: 9200, maintenance: '_cluster' },
  { label: 'SQLite', value: 'sqlite', port: null, maintenance: 'main' },
]
const form = reactive({
  database_type: 'postgresql' as DatabaseType,
  name: '',
  environment: 'production' as 'development' | 'test' | 'production',
  host: '',
  port: 5432,
  maintenance_database: 'postgres',
  ssl_mode: 'disable' as 'disable' | 'prefer' | 'require' | 'verify-ca' | 'verify-full',
  connect_timeout_seconds: 5,
  service_name: '',
  database_file: '',
  url_path_prefix: '',
  username: '',
  password: '',
})
const editForm = reactive({
  database_type: 'postgresql' as DatabaseType,
  name: '',
  environment: 'production' as 'development' | 'test' | 'production',
  host: '',
  port: 5432,
  maintenance_database: 'postgres',
  ssl_mode: 'disable' as 'disable' | 'prefer' | 'require' | 'verify-ca' | 'verify-full',
  connect_timeout_seconds: 5,
  service_name: '',
  database_file: '',
  url_path_prefix: '',
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

const wizardDatabase = computed(() => discovery.value?.databases.find((item) => item.name === wizardDatabaseName.value) || null)
const managedDatabase = computed(() => managedDiscovery.value?.databases.find((item) => item.name === managedDatabaseName.value) || null)

function endpoint() {
  return {
    database_type: form.database_type,
    host: form.host.trim(),
    port: form.port,
    maintenance_database: form.maintenance_database.trim(),
    ssl_mode: form.ssl_mode,
    connect_timeout_seconds: form.connect_timeout_seconds,
    service_name: form.service_name.trim() || null,
    database_file: form.database_file.trim() || null,
    url_path_prefix: form.url_path_prefix.trim(),
  }
}

function editedEndpoint() {
  return {
    database_type: editForm.database_type,
    host: editForm.host.trim(),
    port: editForm.port,
    maintenance_database: editForm.maintenance_database.trim(),
    ssl_mode: editForm.ssl_mode,
    connect_timeout_seconds: editForm.connect_timeout_seconds,
    service_name: editForm.service_name.trim() || null,
    database_file: editForm.database_file.trim() || null,
    url_path_prefix: editForm.url_path_prefix.trim(),
  }
}

function key(database: string, schema: string, type: 'table' | 'view', name: string) {
  return JSON.stringify([database, schema, type, name])
}

function selected(database: string, schema: string, type: 'table' | 'view', name: string): boolean {
  return selectedObjects.value.includes(key(database, schema, type, name))
}

function scopeSelected(database: string, schema: string, type: 'table' | 'view', name: string): boolean {
  return scopeSelectedObjects.value.includes(key(database, schema, type, name))
}

function databaseObjectCount(database: DatabaseDiscovery['databases'][number]) {
  return database.schemas.reduce((total, schema) => total + schema.tables.length + schema.views.length, 0)
}

function rangeObjectCount(scope: DatabaseScopeRecord) {
  return Object.values(scope.definition.schemas).reduce(
    (total, schema) => total + schema.tables.length + schema.views.length,
    0,
  )
}

function summarizeNames(names: string[]) {
  if (!names.length) return '无'
  const visible = names.slice(0, 8).join('、')
  return names.length > 8 ? `${visible} 等 ${names.length} 个` : visible
}

function selectFirstReadyDatabase(value: DatabaseDiscovery | null) {
  return value?.databases.find((item) => item.status === 'READY')?.name || value?.databases[0]?.name || null
}

function openWizard() {
  wizardStep.value = 0
  discovery.value = null
  wizardDatabaseName.value = null
  selectedObjects.value = []
  Object.keys(scopeConfigs).forEach((item) => delete scopeConfigs[item])
  Object.assign(form, {
    database_type: 'postgresql', name: '', environment: 'production', host: '', port: 5432, maintenance_database: 'postgres',
    ssl_mode: 'disable', connect_timeout_seconds: 5, service_name: '', database_file: '', url_path_prefix: '', username: '', password: '',
  })
  wizardOpen.value = true
}

function populateEditForm(value: DatabaseConnectionDetail) {
  Object.assign(editForm, {
    database_type: value.database_type,
    name: value.name,
    environment: value.environment,
    host: value.endpoint.host,
    port: value.endpoint.port,
    maintenance_database: value.endpoint.maintenance_database,
    ssl_mode: value.endpoint.ssl_mode,
    connect_timeout_seconds: value.endpoint.connect_timeout_seconds,
    service_name: value.endpoint.service_name || '',
    database_file: value.endpoint.database_file || '',
    url_path_prefix: value.endpoint.url_path_prefix || '',
  })
}

function applyDatabaseTypeDefaults(type: DatabaseType) {
  const selected = databaseTypeOptions.find((item) => item.value === type)
  if (!selected) return
  form.port = selected.port as number
  form.maintenance_database = selected.maintenance
  form.service_name = type === 'oracle' ? selected.maintenance : ''
  form.database_file = ''
  form.url_path_prefix = ''
  discovery.value = null
}

function databaseTypeLabel(type: DatabaseType) {
  return databaseTypeOptions.find((item) => item.value === type)?.label || type
}

async function openManager(item: DatabaseConnectionSummary) {
  managerOpen.value = true
  managerLoading.value = true
  managerTab.value = 'overview'
  managedDiscovery.value = null
  managedDatabaseName.value = null
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
  managedDatabaseName.value = null
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
    if (!form.name.trim() || (form.database_type === 'sqlite' ? !form.database_file.trim() : !form.host.trim())) {
      message.warning(form.database_type === 'sqlite' ? '请填写连接名称和 SQLite 文件' : '请填写连接名称和主机')
      return
    }
  }
  if (wizardStep.value === 1 && form.database_type !== 'sqlite' && (!form.username.trim() || !form.password)) {
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
    wizardDatabaseName.value = selectFirstReadyDatabase(result)
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
    message.success(`${databaseTypeLabel(form.database_type)} 连接正常，发现 ${result.databases.length} 个数据库`)
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
  if (!result.length) throw new Error('至少启用一个数据库访问范围')
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
    managedDatabaseName.value = selectFirstReadyDatabase(managedDiscovery.value)
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
    managedDatabaseName.value = selectFirstReadyDatabase(managedDiscovery.value)
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
  if (!editForm.name.trim() || (editForm.database_type === 'sqlite' ? !editForm.database_file.trim() : !editForm.host.trim())) {
    message.warning('请完整填写连接配置')
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
    message.success('新的数据访问范围已保存')
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

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="数据库连接" description="统一管理主流 SQL 数据库、达梦 DM 和 Elasticsearch，并为 Agent 冻结只读数据范围。">
      <template #actions>
        <AdminGuideLink section="database" />
        <NButton secondary :loading="loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" @click="openWizard"><template #icon><NIcon :component="Plus" /></template>创建数据库连接</NButton>
      </template>
    </PageHeader>
    <div v-if="error" class="error-panel" style="margin-bottom:16px">{{ error }}</div>
    <section class="surface panel-flush">
      <div v-if="loading" class="loading-stack" style="padding:20px"><div v-for="item in 4" :key="item" class="skeleton-line" /></div>
      <div v-else-if="!connections.length" class="empty-state"><div><NIcon :component="Database" size="30" /><h3>暂无数据库连接</h3><p>先将 agent-database-mcp 容器加入目标数据库网络，再通过向导完成配置。</p></div></div>
      <div v-else class="connection-list">
        <article v-for="item in connections" :key="item.id" class="connection-row">
          <div><strong>{{ item.name }}</strong><span>{{ databaseTypeLabel(item.database_type) }}</span><span class="mono">{{ item.database_type === 'sqlite' ? item.maintenance_database : `${item.host}:${item.port} / ${item.maintenance_database}` }}</span></div>
          <div><span>{{ item.environment }}</span><small>{{ item.scope_count }} 个数据访问范围</small></div>
          <StatusTag :status="item.status" />
          <span class="muted">{{ formatDate(item.updated_at) }}</span>
          <div class="row-actions"><NButton size="small" secondary @click="openManager(item)"><template #icon><NIcon :component="Settings" /></template>管理</NButton><NButton size="small" secondary :loading="testing" @click="testSaved(item)"><template #icon><NIcon :component="TestPipe" /></template>测试</NButton><NButton size="small" quaternary type="error" :disabled="item.status==='disabled'" @click="disable(item)"><template #icon><NIcon :component="Trash" /></template>停用</NButton></div>
        </article>
      </div>
    </section>

    <NModal v-model:show="wizardOpen" preset="card" title="创建数据库连接" style="width:min(1120px,calc(100vw - 32px))" :mask-closable="false">
      <nav class="db-steps" aria-label="数据库连接创建步骤"><span v-for="(title,index) in steps" :key="title" :class="{active:index===wizardStep,complete:index<wizardStep}">{{ index + 1 }}. {{ title }}</span></nav>
      <div class="wizard-body">
        <NForm v-if="wizardStep===0" label-placement="top"><div class="form-grid">
          <NFormItem label="数据库类型" required><NSelect v-model:value="form.database_type" :options="databaseTypeOptions" @update:value="applyDatabaseTypeDefaults" /></NFormItem>
          <NFormItem label="连接名称" required><NInput v-model:value="form.name" placeholder="业务知识库" /></NFormItem>
          <NFormItem label="环境"><NSelect v-model:value="form.environment" :options="[{label:'开发',value:'development'},{label:'测试',value:'test'},{label:'生产',value:'production'}]" /></NFormItem>
          <NFormItem v-if="form.database_type !== 'sqlite'" label="主机 / 容器名" required><NInput v-model:value="form.host" placeholder="business-database" /></NFormItem>
          <NFormItem v-if="form.database_type !== 'sqlite'" label="端口"><NInputNumber v-model:value="form.port" aria-label="端口" :min="1" :max="65535" /></NFormItem>
          <NFormItem v-if="form.database_type !== 'sqlite'" :label="form.database_type === 'elasticsearch' ? '集群显示名' : '维护库'"><NInput v-model:value="form.maintenance_database" /></NFormItem>
          <NFormItem v-if="form.database_type === 'oracle'" label="Oracle Service Name"><NInput v-model:value="form.service_name" /></NFormItem>
          <NFormItem v-if="form.database_type === 'elasticsearch'" label="URL 路径前缀"><NInput v-model:value="form.url_path_prefix" placeholder="/elastic" /></NFormItem>
          <NFormItem v-if="form.database_type === 'sqlite'" class="span-2" label="SQLite 文件" required><NInput v-model:value="form.database_file" placeholder="business/business.db" /></NFormItem>
          <NFormItem v-if="form.database_type !== 'sqlite'" label="SSL 模式"><NSelect v-model:value="form.ssl_mode" :options="['disable','prefer','require','verify-ca','verify-full'].map(value=>({label:value,value}))" /></NFormItem>
          <NFormItem label="连接超时（秒）"><NInputNumber v-model:value="form.connect_timeout_seconds" :min="1" :max="60" /></NFormItem>
          <NAlert class="span-2" type="info" :bordered="false">{{ form.database_type === 'sqlite' ? 'SQLite 文件路径相对于 data/database-files，运行时只读打开。' : '容器间访问请填写目标数据库容器名，不要填写 127.0.0.1。平台不会修改 Docker 网络。' }}</NAlert>
        </div></NForm>
        <NForm v-else-if="wizardStep===1" label-placement="top"><div class="form-grid credential-grid">
          <NFormItem label="数据库用户名" :required="form.database_type !== 'sqlite'"><NInput v-model:value="form.username" autocomplete="off" :disabled="form.database_type === 'sqlite'" /></NFormItem>
          <NFormItem label="数据库密码" :required="form.database_type !== 'sqlite'"><NInput v-model:value="form.password" type="password" show-password-on="click" autocomplete="new-password" :disabled="form.database_type === 'sqlite'" /></NFormItem>
          <NAlert class="span-2" type="info" :bordered="false">密码通过内网提交并加密保存，保存后前端不再回显；模型、Trace 和 Artifact 均不会获得密码。</NAlert>
          <NAlert v-if="form.database_type === 'elasticsearch'" class="span-2" type="warning" :bordered="false">Elasticsearch 账号需要 cluster monitor，并对允许发现的索引具有 read、view_index_metadata、monitor 权限；这些权限均为只读。</NAlert>
          <NAlert v-if="form.database_type === 'dm'" class="span-2" type="warning" :bordered="false">达梦连接依赖与离线环境 CPU 架构及 Python 3.12 匹配的官方 dmPython 驱动，制作离线包前必须放入 drivers/dm。</NAlert>
        </div></NForm>
        <div v-else-if="wizardStep===2" class="test-stage">
          <div class="test-toolbar"><div><h3>连接测试与资源发现</h3><p>一次检查连接，并读取所有可访问数据库、Schema、表、视图和字段。</p></div><NButton type="primary" :loading="testing" @click="testTemporary"><template #icon><NIcon :component="TestPipe" /></template>开始测试</NButton></div>
          <div v-if="discovery" class="discovery-result"><div class="result-summary"><StatusTag :status="discovery.status" /><strong>{{ discovery.server.version }}</strong><span>{{ discovery.latency_ms }} ms</span><span>{{ discovery.databases.length }} 个数据库</span></div><div class="check-grid"><div v-for="check in discovery.checks" :key="check.name"><strong>✓ {{ check.name }}</strong><span>{{ check.detail || '通过' }}</span></div></div><NAlert v-for="warning in discovery.warnings" :key="warning" type="warning" :bordered="false">{{ warning }}</NAlert></div>
          <div v-else class="empty-state compact"><div><NIcon :component="TestPipe" size="28" /><h3>等待测试</h3><p>使用上一步填写的用户名和密码测试；测试不会保存当前密码或连接配置。</p></div></div>
        </div>
        <div v-else class="access-stage">
          <NAlert type="info" :bordered="false">每个数据库单独配置访问范围。Agent 只能读取这里选择的表和视图，不能在任务中切换到其他数据库。</NAlert>
          <div class="resource-workbench">
            <aside class="database-picker">
              <header><strong>可访问数据库</strong><span>{{ discovery?.databases.length || 0 }} 个</span></header>
              <button
                v-for="database in discovery?.databases || []"
                :key="database.name"
                type="button"
                :disabled="database.status !== 'READY'"
                :class="{ active: wizardDatabaseName === database.name }"
                @click="wizardDatabaseName = database.name"
              >
                <span><strong>{{ database.name }}</strong><small>{{ databaseObjectCount(database) }} 个对象</small></span>
                <NCheckbox
                  v-if="scopeConfigs[database.name]"
                  v-model:checked="scopeConfigs[database.name].enabled"
                  :disabled="database.status !== 'READY'"
                  aria-label="启用数据库访问"
                  @click.stop
                />
                <StatusTag v-else :status="database.status" />
              </button>
            </aside>
            <section v-if="wizardDatabase && scopeConfigs[wizardDatabase.name]" class="access-editor">
              <div class="access-policy-panel">
                <header><strong>权限与限制</strong><span>应用于 {{ wizardDatabase.name }}</span></header>
                <div class="scope-policy">
                  <NCheckbox v-model:checked="scopeConfigs[wizardDatabase.name].allow_describe">查看结构</NCheckbox>
                  <NCheckbox v-model:checked="scopeConfigs[wizardDatabase.name].allow_preview">预览</NCheckbox>
                  <NCheckbox v-model:checked="scopeConfigs[wizardDatabase.name].allow_query">查询</NCheckbox>
                  <NCheckbox v-model:checked="scopeConfigs[wizardDatabase.name].allow_aggregate">聚合</NCheckbox>
                  <label>最大行数 <NInputNumber v-model:value="scopeConfigs[wizardDatabase.name].max_rows" :min="1" :max="10000" size="small" /></label>
                  <label>超时 ms <NInputNumber v-model:value="scopeConfigs[wizardDatabase.name].statement_timeout_ms" :min="100" :max="300000" size="small" /></label>
                  <label>每分钟 <NInputNumber v-model:value="scopeConfigs[wizardDatabase.name].requests_per_minute" :min="1" :max="10000" size="small" /></label>
                </div>
              </div>
              <DatabaseObjectBrowser
                v-model:selected-keys="selectedObjects"
                :database="wizardDatabase"
                selectable
                :disabled="!scopeConfigs[wizardDatabase.name].enabled"
              />
            </section>
          </div>
        </div>
      </div>
      <template #footer><div class="wizard-actions"><NButton @click="wizardOpen=false">取消</NButton><span /><NButton v-if="wizardStep>0" @click="wizardStep-=1">上一步</NButton><NButton v-if="wizardStep<3" type="primary" @click="next">下一步</NButton><NButton v-else type="primary" :loading="saving" @click="save">保存数据库连接</NButton></div></template>
    </NModal>

    <NModal :show="managerOpen" preset="card" :title="activeConnection ? `管理连接 · ${activeConnection.name}` : '管理数据库连接'" style="width:min(1180px,calc(100vw - 32px))" :mask-closable="false" @update:show="(value:boolean)=>{if(!value)closeManager()}">
      <div v-if="managerLoading" class="loading-stack manager-loading"><div v-for="item in 6" :key="item" class="skeleton-line" /></div>
      <template v-else-if="activeConnection">
        <div class="manager-summary">
          <div><span>当前状态</span><StatusTag :status="activeConnection.status" /></div>
          <div><span>Connector Revision</span><strong class="mono">{{ activeConnection.current_revision_id.slice(0,8) }}</strong></div>
          <div><span>数据库范围</span><strong>{{ activeConnection.scopes.length }} 个访问范围</strong></div>
          <div><span>凭据</span><strong>{{ activeConnection.credential.masked_username || '未配置' }}</strong></div>
        </div>
        <NTabs v-model:value="managerTab" type="line" animated>
          <NTabPane name="overview" tab="连接配置">
            <div class="manager-pane">
              <NAlert type="info" :bordered="false">数据库类型创建后不可更换。修改端点配置会先用现有凭据真实测试，成功后创建新的不可变 Connector Revision。</NAlert>
              <NForm label-placement="top"><div class="form-grid">
                <NFormItem label="数据库类型"><NInput :value="databaseTypeLabel(editForm.database_type)" disabled /></NFormItem>
                <NFormItem label="连接名称"><NInput v-model:value="editForm.name" /></NFormItem>
                <NFormItem label="环境"><NSelect v-model:value="editForm.environment" :options="[{label:'开发',value:'development'},{label:'测试',value:'test'},{label:'生产',value:'production'}]" /></NFormItem>
                <NFormItem v-if="editForm.database_type !== 'sqlite'" label="主机 / 容器名"><NInput v-model:value="editForm.host" /></NFormItem>
                <NFormItem v-if="editForm.database_type !== 'sqlite'" label="端口"><NInputNumber v-model:value="editForm.port" aria-label="端口" :min="1" :max="65535" /></NFormItem>
                <NFormItem v-if="editForm.database_type !== 'sqlite'" label="维护库"><NInput v-model:value="editForm.maintenance_database" /></NFormItem>
                <NFormItem v-if="editForm.database_type === 'oracle'" label="Oracle Service Name"><NInput v-model:value="editForm.service_name" /></NFormItem>
                <NFormItem v-if="editForm.database_type === 'elasticsearch'" label="URL 路径前缀"><NInput v-model:value="editForm.url_path_prefix" /></NFormItem>
                <NFormItem v-if="editForm.database_type === 'sqlite'" label="SQLite 文件"><NInput v-model:value="editForm.database_file" /></NFormItem>
                <NFormItem v-if="editForm.database_type !== 'sqlite'" label="SSL 模式"><NSelect v-model:value="editForm.ssl_mode" :options="['disable','prefer','require','verify-ca','verify-full'].map(value=>({label:value,value}))" /></NFormItem>
                <NFormItem label="连接超时（秒）"><NInputNumber v-model:value="editForm.connect_timeout_seconds" :min="1" :max="60" /></NFormItem>
              </div></NForm>
              <div class="manager-actions"><NButton :loading="testing" @click="testManaged"><template #icon><NIcon :component="TestPipe" /></template>使用已保存凭据测试</NButton><span /><NButton v-if="activeConnection.enabled" type="error" secondary :loading="managerSaving" @click="setManagedEnabled(false)">停用连接</NButton><NButton v-else type="success" secondary :loading="managerSaving" @click="setManagedEnabled(true)">重新启用</NButton><NButton type="primary" :loading="managerSaving" @click="saveManagedConnection">保存配置</NButton></div>
            </div>
          </NTabPane>
          <NTabPane name="access" tab="数据访问">
            <div class="manager-pane access-manager-pane">
              <div class="scope-toolbar">
                <div><strong>数据访问范围</strong><p>已有配置按行展示，展开后查看具体表和视图。刷新资源不会修改已生效的访问范围。</p></div>
                <div><NButton :loading="testing" @click="testManaged">测试并读取资源</NButton><NButton type="primary" secondary :loading="testing" @click="discoverManaged">刷新资源</NButton></div>
              </div>

              <section v-if="activeConnection.scopes.length" class="saved-range-section">
                <header><strong>已配置范围</strong><span>{{ activeConnection.scopes.length }} 个</span></header>
                <div class="saved-range-list">
                  <details v-for="scope in activeConnection.scopes" :key="scope.id" class="saved-range-row">
                    <summary>
                      <span class="range-name"><strong>{{ scope.name }}</strong><small>{{ scope.database }}</small></span>
                      <span><strong>{{ Object.keys(scope.definition.schemas).length }}</strong><small>Schema</small></span>
                      <span><strong>{{ rangeObjectCount(scope) }}</strong><small>数据库对象</small></span>
                      <span><strong>{{ scope.definition.permissions.query ? '可查询' : '仅查看结构' }}</strong><small>版本 {{ scope.revision }}</small></span>
                      <span class="range-expand">查看详情</span>
                    </summary>
                    <div class="range-details">
                      <div class="scope-facts"><span>结构 {{ scope.definition.permissions.describe ? '允许' : '禁止' }}</span><span>预览 {{ scope.definition.permissions.preview ? '允许' : '禁止' }}</span><span>查询 {{ scope.definition.permissions.query ? '允许' : '禁止' }}</span><span>最大 {{ scope.definition.limits.max_rows }} 行</span><span>超时 {{ scope.definition.limits.statement_timeout_ms }} ms</span></div>
                      <div class="saved-schema-list"><div v-for="(schema,schemaName) in scope.definition.schemas" :key="schemaName"><strong>{{ schemaName }}</strong><span>表：{{ summarizeNames(schema.tables) }}</span><span>视图：{{ summarizeNames(schema.views) }}</span></div></div>
                      <small class="config-digest">配置摘要 {{ scope.digest.slice(0,12) }}</small>
                    </div>
                  </details>
                </div>
              </section>
              <div v-else class="empty-state compact"><div><NIcon :component="Database" size="28" /><h3>尚未设置数据访问范围</h3><p>先读取数据库资源，再选择允许 Agent 访问的表和视图。</p></div></div>

              <template v-if="managedDiscovery">
                <NAlert v-for="warning in managedDiscovery.warnings" :key="warning" type="warning" :bordered="false">{{ warning }}</NAlert>
                <section class="resource-section">
                  <header><div><strong>数据库资源</strong><span>选择数据库后可搜索表、视图和字段</span></div><NButton v-if="managedDatabase?.status === 'READY'" type="primary" @click="openScopeCreator(managedDatabase.name)">配置访问范围</NButton></header>
                  <div class="resource-workbench">
                    <aside class="database-picker">
                      <header><strong>数据库</strong><span>{{ managedDiscovery.databases.length }} 个</span></header>
                      <button
                        v-for="database in managedDiscovery.databases"
                        :key="database.name"
                        type="button"
                        :class="{ active: managedDatabaseName === database.name }"
                        @click="managedDatabaseName = database.name"
                      >
                        <span><strong>{{ database.name }}</strong><small>{{ databaseObjectCount(database) }} 个对象</small></span>
                        <StatusTag :status="database.status" />
                      </button>
                    </aside>
                    <div class="resource-browser-wrap">
                      <p v-if="managedDatabase?.error" class="error-text">{{ managedDatabase.error }}</p>
                      <DatabaseObjectBrowser v-else-if="managedDatabase" :database="managedDatabase" />
                    </div>
                  </div>
                </section>
              </template>
              <div v-else class="resource-placeholder"><strong>尚未读取数据库资源</strong><span>点击“测试并读取资源”，平台会列出当前账号可访问的数据库、表、视图和字段。</span></div>
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

    <NModal :show="scopeOpen" preset="card" :title="`配置数据访问范围 · ${scopeDatabase || ''}`" style="width:min(1120px,calc(100vw - 32px))" :mask-closable="false" @update:show="(value:boolean)=>{scopeOpen=value}">
      <div v-if="scopeDatabase && managedDatabase" class="scope-stage">
        <NAlert type="info" :bordered="false">一个访问范围只对应一个数据库。保存后 Agent 只能访问这里选择的表和视图，不能临时切换数据库。</NAlert>
        <NForm label-placement="top"><div class="form-grid scope-basics"><NFormItem label="范围名称"><NInput v-model:value="newScope.name" /></NFormItem><NFormItem label="最大返回行数"><NInputNumber v-model:value="newScope.max_rows" :min="1" :max="10000" /></NFormItem><NFormItem label="查询超时 ms"><NInputNumber v-model:value="newScope.statement_timeout_ms" :min="100" :max="300000" /></NFormItem><NFormItem label="每分钟调用次数"><NInputNumber v-model:value="newScope.requests_per_minute" :min="1" :max="10000" /></NFormItem></div></NForm>
        <div class="scope-policy"><NCheckbox v-model:checked="newScope.allow_describe">查看结构</NCheckbox><NCheckbox v-model:checked="newScope.allow_preview">预览</NCheckbox><NCheckbox v-model:checked="newScope.allow_query">查询</NCheckbox><NCheckbox v-model:checked="newScope.allow_aggregate">聚合</NCheckbox></div>
        <DatabaseObjectBrowser v-model:selected-keys="scopeSelectedObjects" :database="managedDatabase" selectable />
      </div>
      <template #footer><div class="wizard-actions"><NButton @click="scopeOpen=false">取消</NButton><span /><NButton type="primary" :loading="managerSaving" @click="saveManagedScope">保存访问范围</NButton></div></template>
    </NModal>
  </div>
</template>

<style scoped>
.connection-list{display:grid}
.connection-row{display:grid;grid-template-columns:minmax(220px,1.5fr) minmax(150px,.7fr) 110px 150px auto;gap:16px;align-items:center;padding:16px 20px;border-bottom:1px solid var(--line)}
.connection-row:last-child{border-bottom:0}.connection-row>div{display:grid;gap:4px}.connection-row span,.connection-row small{font-size:12px}
.row-actions{display:flex!important;grid-auto-flow:column;flex-wrap:wrap;justify-content:end}
.db-steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.db-steps span{padding:11px 13px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}.db-steps .active{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}.db-steps .complete{color:#63c174}
.wizard-body{min-height:480px;padding-top:22px}.credential-grid{max-width:720px}.test-stage,.scope-stage,.access-stage{display:grid;gap:14px}
.test-toolbar,.result-summary,.wizard-actions{display:flex;align-items:center;gap:14px}.test-toolbar{justify-content:space-between}.test-toolbar h3,.test-toolbar p{margin:0}.test-toolbar p{margin-top:5px;color:var(--muted);font-size:13px}
.discovery-result{display:grid;gap:14px}.check-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.check-grid>div{display:grid;gap:4px;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.check-grid span{color:var(--muted);font-size:12px}
.resource-workbench{display:grid;grid-template-columns:220px minmax(0,1fr);min-height:460px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface)}
.database-picker{display:grid;align-content:start;border-right:1px solid var(--line);background:var(--surface-subtle)}
.database-picker>header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 14px;border-bottom:1px solid var(--line)}.database-picker>header span{color:var(--muted);font-size:11px}
.database-picker>button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;padding:12px 14px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;text-align:left;cursor:pointer}.database-picker>button:hover{background:var(--surface)}.database-picker>button.active{box-shadow:inset 3px 0 0 var(--accent);background:var(--surface)}.database-picker>button:disabled{cursor:not-allowed;opacity:.55}.database-picker>button>span:first-child{display:grid;min-width:0;gap:3px}.database-picker>button strong,.database-picker>button small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.database-picker>button small{color:var(--muted);font-size:10px}
.access-editor,.resource-browser-wrap{display:grid;align-content:start;min-width:0;padding:14px;gap:12px}.access-policy-panel{border:1px solid var(--line);border-radius:9px;overflow:hidden}.access-policy-panel>header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-bottom:1px solid var(--line)}.access-policy-panel>header span{color:var(--muted);font-size:11px}
.scope-policy{display:flex;flex-wrap:wrap;align-items:center;gap:14px;padding:12px 14px;background:var(--surface-subtle)}.scope-policy label{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}.scope-policy label :deep(.n-input-number){width:104px}
.wizard-actions span{flex:1}.manager-loading{min-height:420px;padding:24px}.manager-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}.manager-summary>div{display:grid;gap:7px;padding:13px 14px;border:1px solid var(--line);border-radius:8px;background:var(--surface-subtle)}.manager-summary span{color:var(--muted);font-size:11px}
.manager-pane{display:grid;gap:18px;min-height:440px;padding:14px 2px}.access-manager-pane{align-content:start}.manager-actions{display:flex;align-items:center;gap:10px}.manager-actions>span{flex:1}
.scope-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px}.scope-toolbar p{margin:5px 0 0;color:var(--muted);font-size:12px}.scope-toolbar>div:last-child{display:flex;gap:8px}
.saved-range-section{display:grid;border:1px solid var(--line);border-radius:9px;overflow:hidden}.saved-range-section>header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface-subtle)}.saved-range-section>header span{color:var(--muted);font-size:11px}
.saved-range-list{display:grid}.saved-range-row{border-top:1px solid var(--line)}.saved-range-row:first-child{border-top:0}.saved-range-row>summary{display:grid;grid-template-columns:minmax(220px,1.7fr) minmax(70px,.45fr) minmax(90px,.55fr) minmax(110px,.7fr) auto;gap:14px;align-items:center;padding:11px 14px;list-style:none;cursor:pointer}.saved-range-row>summary::-webkit-details-marker{display:none}.saved-range-row>summary:hover{background:var(--surface-subtle)}.saved-range-row>summary>span{display:grid;gap:2px}.saved-range-row>summary strong{overflow:hidden;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.saved-range-row>summary small{color:var(--muted);font-size:10px}.range-expand{display:block!important;color:var(--accent);font-size:11px;white-space:nowrap}.saved-range-row[open] .range-expand{color:var(--muted)}
.range-details{display:grid;gap:10px;padding:12px 14px 14px;border-top:1px solid var(--line);background:var(--surface-subtle)}.scope-facts{display:flex;flex-wrap:wrap;gap:6px}.scope-facts span{padding:4px 7px;border-radius:5px;background:var(--surface);color:var(--muted);font-size:10px}.saved-schema-list{display:grid;gap:7px}.saved-schema-list>div{display:grid;grid-template-columns:140px minmax(0,1fr) minmax(0,1fr);gap:10px;padding:7px 0;border-top:1px solid var(--line)}.saved-schema-list span{overflow-wrap:anywhere;color:var(--muted);font-size:11px}.config-digest{color:var(--muted);font-size:10px}
.resource-section{display:grid;gap:10px}.resource-section>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.resource-section>header>div{display:grid;gap:3px}.resource-section>header span{color:var(--muted);font-size:11px}.resource-section .resource-workbench{min-height:420px}.resource-placeholder{display:grid;place-items:center;gap:5px;min-height:180px;padding:24px;border:1px dashed var(--line);border-radius:9px;color:var(--muted);text-align:center}.resource-placeholder span{max-width:560px;font-size:12px}
.error-text{margin:0;color:var(--danger);font-size:12px}.credential-pane{max-width:780px}.credential-status{display:grid;grid-template-columns:130px 1fr 130px 1fr;gap:10px;align-items:center;padding:14px;border:1px solid var(--line);border-radius:8px}.credential-status span{color:var(--muted);font-size:12px}.scope-basics{grid-template-columns:repeat(4,1fr)}
@media(max-width:900px){.connection-row{grid-template-columns:1fr 1fr}.check-grid,.manager-summary{grid-template-columns:1fr 1fr}.scope-basics{grid-template-columns:1fr 1fr}.resource-workbench{grid-template-columns:1fr}.database-picker{grid-template-columns:repeat(2,minmax(0,1fr));max-height:210px;overflow:auto;border-right:0;border-bottom:1px solid var(--line)}.database-picker>header{grid-column:1/-1}.saved-range-row>summary{grid-template-columns:minmax(180px,1.4fr) repeat(2,minmax(70px,.5fr)) auto}.saved-range-row>summary>span:nth-child(4){display:none}}
@media(max-width:680px){.db-steps{grid-template-columns:1fr 1fr}.connection-row,.manager-summary,.scope-basics{grid-template-columns:1fr}.scope-policy{align-items:flex-start;flex-direction:column}.scope-toolbar,.resource-section>header{align-items:flex-start;flex-direction:column}.scope-toolbar>div:last-child{flex-wrap:wrap}.credential-status{grid-template-columns:1fr}.manager-actions{flex-wrap:wrap}.manager-actions>span{display:none}.database-picker{grid-template-columns:1fr}.saved-range-row>summary{grid-template-columns:minmax(0,1fr) auto}.saved-range-row>summary>span:nth-child(2),.saved-range-row>summary>span:nth-child(3),.saved-range-row>summary>span:nth-child(4){display:none}.saved-schema-list>div{grid-template-columns:1fr}.resource-workbench{min-height:0}}
</style>
