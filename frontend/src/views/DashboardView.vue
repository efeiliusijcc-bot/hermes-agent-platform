<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Activity, AlertTriangle, PlugConnected, Plus, Robot } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { formatDate } from '@/utils/format'

interface WorkbenchModel {
  summary: { agents: number; executions: number; failed_executions: number; connections_needing_attention: number }
  recent_runs: Array<{ id: string; agent_id: string; status: string; runtime_type: string; started_at: string; finished_at: string | null }>
  needs_attention: Array<{ type: string; id: string; label: string; state: string }>
}

const router = useRouter()
const loading = ref(false)
const error = ref<string | null>(null)
const workbench = ref<WorkbenchModel | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    workbench.value = await platformApi.getConsoleWorkbench() as unknown as WorkbenchModel
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="Agent 工作台" description="查看最近运行、异常连接和需要处理的配置。">
      <template #actions><NButton secondary :loading="loading" @click="load">刷新</NButton><NButton type="primary" @click="router.push({ name: 'agent-create' })"><template #icon><NIcon :component="Plus" /></template>创建 Agent</NButton></template>
    </PageHeader>
    <div v-if="error" class="error-panel" style="margin-bottom:16px">{{ error }}</div>
    <section class="metric-grid" aria-label="平台指标">
      <MetricCard label="Agent" :value="loading ? '--' : (workbench?.summary.agents ?? 0)" note="已登记智能体" primary><template #icon><NIcon :component="Robot" /></template></MetricCard>
      <MetricCard label="执行" :value="loading ? '--' : (workbench?.summary.executions ?? 0)" note="持久化运行记录"><template #icon><NIcon :component="Activity" /></template></MetricCard>
      <MetricCard label="失败" :value="loading ? '--' : (workbench?.summary.failed_executions ?? 0)" note="需要查看真实错误"><template #icon><NIcon :component="AlertTriangle" /></template></MetricCard>
      <MetricCard label="连接异常" :value="loading ? '--' : (workbench?.summary.connections_needing_attention ?? 0)" note="离线或降级连接"><template #icon><NIcon :component="PlugConnected" /></template></MetricCard>
    </section>
    <div class="content-grid">
      <section class="surface panel-flush"><div class="section-heading"><div><h2>最近运行</h2><p>Console BFF 返回的统一页面模型</p></div><NButton text type="primary" @click="router.push({ name: 'executions' })">全部运行</NButton></div><div v-if="loading" class="loading-stack" style="padding:20px"><div v-for="item in 4" :key="item" class="skeleton-line" /></div><div v-else-if="workbench?.recent_runs.length" class="registry-list"><button v-for="item in workbench.recent_runs" :key="item.id" class="workbench-run" type="button" @click="router.push({ name:'execution-detail', params:{ id:item.id } })"><div><strong class="mono">{{ item.id }}</strong><span>{{ item.agent_id }} / {{ item.runtime_type }}</span></div><StatusTag :status="item.status" /><time>{{ formatDate(item.started_at) }}</time></button></div><div v-else class="empty-state"><div><h3>还没有运行记录</h3><p>发布 Agent 并执行任务后，结果会显示在这里。</p></div></div></section>
      <aside class="surface panel"><div class="section-heading"><div><h2>需要处理</h2><p>连接健康和配置异常</p></div></div><div v-if="workbench?.needs_attention.length" class="binding-list" style="margin-top:14px"><button v-for="item in workbench.needs_attention" :key="item.id" class="binding-row" type="button" @click="router.push({ name:'platform-connections' })"><div><strong>{{ item.label }}</strong><span>{{ item.type }}</span></div><StatusTag :status="item.state" style="margin-left:auto" /></button></div><div v-else class="version-empty">当前没有需要处理的连接异常。</div></aside>
    </div>
  </div>
</template>

<style scoped>
.registry-list{display:grid}.workbench-run{display:grid;grid-template-columns:minmax(0,1fr) 110px 150px;gap:14px;align-items:center;width:100%;padding:14px 20px;color:inherit;text-align:left;border:0;border-bottom:1px solid var(--line);background:transparent;cursor:pointer}.workbench-run:hover{background:var(--accent-soft)}.workbench-run>div{display:grid;gap:4px;min-width:0}.workbench-run span,.workbench-run time{color:var(--muted);font-size:11px}@media(max-width:760px){.workbench-run{grid-template-columns:1fr}.content-grid{grid-template-columns:1fr}}
</style>
