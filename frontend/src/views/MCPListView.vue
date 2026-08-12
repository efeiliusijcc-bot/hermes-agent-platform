<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NIcon, useDialog, useMessage } from 'naive-ui'
import { Database, Files, Plus, PlugConnected, Search } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'
import type { MCPServer } from '@/types/api'

const resourceStore = useResourceStore()
const message = useMessage()
const dialog = useDialog()
const query = ref('')
const showCreate = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const editingId = ref<string | null>(null)
const form = reactive({ id: '', name: '', kind: 'filesystem' as 'filesystem' | 'database', endpoint: 'http://mcp-gateway:8090/mcp' })
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword ? resourceStore.mcpServers.filter((item) => [item.id, item.name, item.endpoint, item.config.kind, item.status].some((value) => value.toLowerCase().includes(keyword))) : resourceStore.mcpServers
})

async function create() {
  saving.value = true
  try {
    const payload = { name: form.name, endpoint: form.endpoint, permission: 'read_only' as const, config: { kind: form.kind, read_only: true as const } }
    if (editingId.value) await platformApi.updateMCPServer(editingId.value, payload)
    else await platformApi.createMCPServer({ id: form.id, ...payload })
    await resourceStore.fetchMCPServers()
    showCreate.value = false
    message.success(editingId.value ? 'MCP 已更新，状态已重置' : 'MCP 已注册')
    editingId.value = null
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { saving.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { id: '', name: '', kind: 'filesystem', endpoint: 'http://mcp-gateway:8090/mcp' })
  showCreate.value = true
}

function edit(server: MCPServer) {
  editingId.value = server.id
  Object.assign(form, { id: server.id, name: server.name, kind: server.config.kind, endpoint: server.endpoint })
  showCreate.value = true
}

async function test(server: MCPServer) {
  testingId.value = server.id
  try {
    const result = await platformApi.testMCPServer(server.id)
    await resourceStore.fetchMCPServers()
    message[result.status === 'online' ? 'success' : 'error'](`${result.detail}，${result.latency_ms} ms`)
  } catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) } finally { testingId.value = null }
}

function remove(server: MCPServer) {
  dialog.warning({ title: '删除 MCP', content: `确认删除 ${server.name}（${server.id}）？已绑定时后端会拒绝删除。`, positiveText: '删除', negativeText: '取消', async onPositiveClick() {
    try { await platformApi.deleteMCPServer(server.id); await resourceStore.fetchMCPServers(); message.success('MCP 已删除') }
    catch (error) { message.error(getApiErrorMessage(error), { duration: 7000 }) }
  } })
}

onMounted(() => resourceStore.fetchAll().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="MCP 管理" description="动态注册平台 MCP Gateway 下的只读 filesystem/database 能力，并执行真实连接测试。">
      <template #actions><NButton type="primary" @click="openCreate"><template #icon><NIcon :component="Plus" /></template>创建 MCP</NButton></template>
    </PageHeader>
    <NAlert type="info" :bordered="false" style="margin-bottom: 16px">所有注册项必须指向后端配置的 MCP_GATEWAY_ENDPOINT，Agent 不能绕过平台网关。</NAlert>
    <div class="toolbar"><NInput v-model:value="query" class="search" clearable placeholder="搜索 MCP"><template #prefix><NIcon :component="Search" /></template></NInput><div class="toolbar-spacer" /><span class="muted" style="font-size: 11px">{{ filtered.length }} 项</span></div>
    <section class="surface resource-list">
      <div v-if="resourceStore.loading" class="loading-stack" style="padding: 18px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div v-else-if="filtered.length === 0" class="empty-state"><div><div class="empty-state-icon"><NIcon :component="PlugConnected" size="24" /></div><h3>暂无 MCP</h3><p>创建平台网关下的只读能力。</p></div></div>
      <article v-for="server in filtered" v-else :key="server.id" class="resource-row">
        <span class="resource-icon"><NIcon :component="server.config.kind === 'database' ? Database : Files" size="19" /></span>
        <div class="resource-main"><strong>{{ server.name }}</strong><span class="mono">{{ server.id }}</span></div>
        <div class="resource-description truncate"><span class="mono">{{ server.endpoint }}</span><br /><span class="muted">{{ formatDate(server.updated_at) }}</span></div>
        <div class="resource-meta resource-actions"><NTag size="small" :type="server.status === 'online' ? 'success' : server.status === 'offline' ? 'error' : 'default'" :bordered="false">{{ server.status }}</NTag><NButton size="tiny" @click="edit(server)">编辑</NButton><NButton size="tiny" :loading="testingId === server.id" @click="test(server)">测试</NButton><NButton size="tiny" type="error" text @click="remove(server)">删除</NButton></div>
      </article>
    </section>

    <NModal v-model:show="showCreate" preset="card" style="width: min(560px, 92vw)" :title="editingId ? '编辑 MCP' : '创建 MCP'">
      <NForm label-placement="top" @submit.prevent="create">
        <div class="form-grid"><NFormItem label="MCP ID"><NInput v-model:value="form.id" :disabled="Boolean(editingId)" placeholder="filesystem-mcp" /></NFormItem><NFormItem label="名称"><NInput v-model:value="form.name" placeholder="只读文件能力" /></NFormItem></div>
        <NFormItem label="能力类型"><NSelect v-model:value="form.kind" :options="[{ label: 'filesystem', value: 'filesystem' }, { label: 'database', value: 'database' }]" /></NFormItem>
        <NFormItem label="Gateway Endpoint"><NInput v-model:value="form.endpoint" /></NFormItem>
        <NAlert type="warning" :bordered="false">权限固定为 read_only，后端还会校验 Endpoint 必须等于平台网关。</NAlert>
        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px"><NButton @click="showCreate = false">取消</NButton><NButton attr-type="submit" type="primary" :loading="saving">{{ editingId ? '保存' : '创建' }}</NButton></div>
      </NForm>
    </NModal>
  </div>
</template>
