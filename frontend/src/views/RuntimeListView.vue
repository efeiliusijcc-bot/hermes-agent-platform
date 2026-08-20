<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Code, Cpu, Heartbeat, Refresh, Server } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import AdminGuideLink from '@/components/AdminGuideLink.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { Agent, AgentRuntime, RuntimeHealth } from '@/types/api'
import { formatDate } from '@/utils/format'

const loading = ref(false)
const checking = ref<string | null>(null)
const error = ref('')
const runtimes = ref<AgentRuntime[]>([])
const agents = ref<Agent[]>([])
const health = ref<Record<string, RuntimeHealth>>({})

const onlineCount = computed(() => runtimes.value.filter((item) => item.status === 'online').length)
const deepseekAgents = computed(() => agents.value.filter((item) => item.runtime_type === 'deepseek').length)

function agentCount(runtime: AgentRuntime): number {
  const sameType = runtimes.value.filter((item) => item.type === runtime.type)
  return agents.value.filter((agent) => {
    if (agent.runtime_type !== runtime.type) return false
    const runtimeId = agent.runtime_id
    return runtimeId === runtime.id || (!runtimeId && sameType.length === 1)
  }).length
}

async function load() {
  loading.value = true
  try {
    const [runtimeValues, agentValues] = await Promise.all([
      platformApi.listRuntimes(),
      platformApi.listAgents(),
    ])
    runtimes.value = runtimeValues
    agents.value = agentValues
    error.value = ''
  } catch (value) {
    error.value = getApiErrorMessage(value)
  } finally {
    loading.value = false
  }
}

async function check(runtime: AgentRuntime) {
  checking.value = runtime.id
  try {
    health.value[runtime.id] = await platformApi.checkRuntime(runtime.id)
    runtimes.value = await platformApi.listRuntimes()
    error.value = ''
  } catch (value) {
    error.value = getApiErrorMessage(value)
  } finally {
    checking.value = null
  }
}

async function checkAll() {
  await load()
  for (const runtime of runtimes.value.filter((item) => item.status !== 'disabled')) {
    await check(runtime)
  }
}

onMounted(load)
</script>

<template>
  <section class="runtime-page">
    <PageHeader eyebrow="RUNTIME REGISTRY" title="运行时管理" description="统一查看 Hermes、Pi 与 DeepSeek Harness 的版本、健康状态和 Agent 使用情况。">
      <template #actions>
        <AdminGuideLink section="runtimes" />
        <NButton :loading="loading || checking !== null" @click="checkAll">
          <template #icon><NIcon :component="Refresh" /></template>检查全部
        </NButton>
      </template>
    </PageHeader>

    <NAlert v-if="error" type="error" closable @close="error = ''">{{ error }}</NAlert>

    <div class="runtime-metrics">
      <article><NIcon :component="Server" /><div><strong>{{ runtimes.length }}</strong><span>注册实例</span></div></article>
      <article><NIcon :component="Heartbeat" /><div><strong>{{ onlineCount }}</strong><span>在线 Runtime</span></div></article>
      <article><NIcon :component="Code" /><div><strong>{{ deepseekAgents }}</strong><span>Coding Agents</span></div></article>
    </div>

    <div v-if="loading" class="runtime-grid">
      <article v-for="index in 2" :key="index" class="runtime-card"><div class="skeleton-line" /><div class="skeleton-line" /></article>
    </div>
    <div v-else-if="runtimes.length" class="runtime-grid">
      <article v-for="runtime in runtimes" :key="runtime.id" class="runtime-card">
        <header>
          <div class="runtime-icon"><NIcon :component="runtime.type === 'pi' ? Cpu : runtime.type === 'deepseek' ? Code : Server" /></div>
          <div><span>{{ runtime.type === 'pi' ? 'PI AGENT CORE' : runtime.type === 'deepseek' ? 'DEEPSEEK HARNESS' : 'HERMES AGENT' }}</span><h2>{{ runtime.name }}</h2></div>
          <StatusTag :status="runtime.status" />
        </header>
        <dl>
          <div><dt>类型</dt><dd class="mono">{{ runtime.type }}</dd></div>
          <div><dt>版本</dt><dd class="mono">{{ runtime.version }}</dd></div>
          <div><dt>Endpoint</dt><dd class="mono endpoint">{{ runtime.endpoint }}</dd></div>
          <div><dt>Agents</dt><dd>{{ agentCount(runtime) }}</dd></div>
          <div><dt>最近检查</dt><dd>{{ runtime.last_health_at ? formatDate(runtime.last_health_at) : '尚未检查' }}</dd></div>
          <div><dt>延迟</dt><dd>{{ health[runtime.id] ? `${health[runtime.id].latency_ms} ms` : '--' }}</dd></div>
        </dl>
        <NAlert v-if="runtime.last_error" type="error" :bordered="false">{{ runtime.last_error }}</NAlert>
        <footer>
          <span class="mono">{{ runtime.id }}</span>
          <NButton secondary :loading="checking === runtime.id" :disabled="runtime.status === 'disabled'" @click="check(runtime)">健康检查</NButton>
        </footer>
      </article>
    </div>
    <NEmpty v-else description="还没有注册 Runtime；启动平台后会自动登记 Hermes、Pi 与已配置的 DeepSeek Harness。" />
  </section>
</template>

<style scoped>
.runtime-page { display: grid; gap: 20px; }
.runtime-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.runtime-metrics article { display: flex; align-items: center; gap: 14px; padding: 18px; border: 1px solid var(--border-color); border-radius: 14px; background: var(--surface); }
.runtime-metrics .n-icon { color: var(--brand); font-size: 24px; }
.runtime-metrics strong, .runtime-metrics span { display: block; }
.runtime-metrics strong { font-size: 25px; line-height: 1; }
.runtime-metrics span { margin-top: 6px; color: var(--text-muted); font-size: 12px; }
.runtime-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.runtime-card { display: grid; gap: 18px; padding: 20px; border: 1px solid var(--border-color); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow-sm); }
.runtime-card header { display: grid; grid-template-columns: 42px 1fr auto; align-items: center; gap: 12px; }
.runtime-icon { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 12px; color: var(--brand); background: var(--brand-soft); font-size: 22px; }
.runtime-card header span { color: var(--text-muted); font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.runtime-card h2 { margin: 3px 0 0; font-size: 17px; }
.runtime-card dl { display: grid; gap: 10px; margin: 0; }
.runtime-card dl div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 12px; padding-bottom: 9px; border-bottom: 1px solid var(--border-color); }
.runtime-card dt { color: var(--text-muted); font-size: 12px; }
.runtime-card dd { margin: 0; font-size: 12px; text-align: right; }
.endpoint { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-card footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.runtime-card footer span { overflow: hidden; color: var(--text-muted); font-size: 10px; text-overflow: ellipsis; }
.mono { font-family: var(--font-mono); }
@media (max-width: 900px) { .runtime-grid { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .runtime-metrics { grid-template-columns: 1fr; } }
</style>
