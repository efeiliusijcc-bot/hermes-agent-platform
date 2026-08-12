<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowLeft, Bolt, History, PlayerPlay, Tool } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAgentStore } from '@/stores/agents'
import { useExecutionStore } from '@/stores/executions'
import { formatDate, formatDuration, truncate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const executionStore = useExecutionStore()
const agentId = computed(() => String(route.params.id))
const input = ref('')
const sessionId = ref('default')

const selectedRun = computed(() => executionStore.currentRun)
const toolCalls = computed(() => selectedRun.value?.details.mcp_calls || [])

async function load() {
  executionStore.currentRun = null
  executionStore.currentResult = null
  await Promise.all([
    agentStore.fetchAgentDetail(agentId.value),
    executionStore.fetchRuns(agentId.value),
  ]).catch(() => undefined)
  if (executionStore.runs.length) executionStore.selectRun(executionStore.runs[0])
}

async function submitRun() {
  if (!input.value.trim()) {
    message.warning('请输入需要 Agent 执行的任务')
    return
  }
  try {
    await executionStore.runAgent(agentId.value, input.value.trim(), sessionId.value.trim() || 'default')
    message.success('Agent 执行成功')
  } catch {
    message.error(executionStore.error || 'Agent 执行失败', { duration: 7000 })
  }
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2)
}

watch(agentId, load)
onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      :title="`${agentStore.currentAgent?.name || agentId} 执行台`"
      description="提交任务并查看同步执行结果。工具调用、知识召回和记忆范围以后端 ExecutionLog 为准。"
    >
      <template #actions>
        <NButton @click="router.push({ name: 'agent-detail', params: { id: agentId } })">
          <template #icon><NIcon :component="ArrowLeft" /></template>返回详情
        </NButton>
      </template>
    </PageHeader>

    <div v-if="agentStore.error || executionStore.error" class="error-panel" style="margin-bottom: 16px">
      {{ agentStore.error || executionStore.error }}
    </div>

    <div class="playground-layout">
      <section class="surface playground-input">
        <div class="section-heading"><div><h2>任务输入</h2><p>调用 `POST /api/agents/{id}/run`</p></div></div>
        <NForm label-placement="top" @submit.prevent="submitRun">
          <NFormItem label="Session ID">
            <NInput v-model:value="sessionId" maxlength="128" placeholder="default" :disabled="executionStore.running" />
          </NFormItem>
          <NFormItem label="任务内容">
            <NInput v-model:value="input" type="textarea" :rows="11" maxlength="100000" show-count placeholder="描述需要 Agent 完成的企业任务" :disabled="executionStore.running" />
          </NFormItem>
          <NAlert v-if="agentStore.currentAgent?.status !== 'active'" type="warning" :bordered="false">
            当前 Agent 状态为 {{ agentStore.currentAgent?.status }}，后端只允许 active Agent 执行。
          </NAlert>
          <div class="playground-actions">
            <span class="muted" style="font-size: 11px">同步请求最长可能等待 300 秒</span>
            <NButton type="primary" attr-type="submit" :loading="executionStore.running" :disabled="agentStore.currentAgent?.status !== 'active'">
              <template #icon><NIcon :component="PlayerPlay" /></template>{{ executionStore.running ? '等待执行完成' : '运行 Agent' }}
            </NButton>
          </div>
        </NForm>
      </section>

      <section class="surface run-panel">
        <div class="section-heading">
          <div><h2>执行结果</h2><p>最终结果和真实运行详情</p></div>
          <StatusTag v-if="selectedRun" :status="selectedRun.status" />
        </div>

        <div v-if="executionStore.running" class="empty-state">
          <div>
            <div class="empty-state-icon"><NIcon :component="Bolt" size="24" /></div>
            <h3>后端正在同步执行</h3>
            <p>当前接口不提供流式事件。界面不会伪造中间步骤，将在响应完成后读取 ExecutionLog。</p>
            <div class="loading-stack" style="width: min(420px, 70vw); margin-top: 18px"><div class="skeleton-line" /><div class="skeleton-line" /></div>
          </div>
        </div>
        <div v-else-if="selectedRun">
          <NAlert v-if="selectedRun.error" type="error" :title="selectedRun.error" style="margin-bottom: 14px" />
          <pre v-if="selectedRun.output" class="result-output">{{ selectedRun.output }}</pre>
          <div v-else class="empty-state empty-state-compact"><div><h3>本次执行没有输出</h3><p>请查看错误信息和后端运行详情。</p></div></div>

          <div class="trace-grid">
            <div class="trace-step"><strong>技能加载</strong>{{ selectedRun.details.skills_loaded?.length || 0 }} 项</div>
            <div class="trace-step"><strong>MCP 加载</strong>{{ selectedRun.details.mcp_loaded?.length || 0 }} 项</div>
            <div class="trace-step"><strong>知识召回</strong>{{ selectedRun.details.knowledge_hits?.length || 0 }} 条</div>
            <div class="trace-step"><strong>会话历史</strong>{{ selectedRun.details.memory_scope?.history_messages_loaded || 0 }} 条</div>
          </div>

          <div class="section-heading" style="margin-top: 22px">
            <div><h2>MCP 调用</h2><p>来自 `details.mcp_calls`，共 {{ toolCalls.length }} 次</p></div>
            <NIcon :component="Tool" size="19" class="muted" />
          </div>
          <div v-if="toolCalls.length" class="tool-call-list">
            <article v-for="(call, index) in toolCalls" :key="`${call.tool}-${index}`" class="tool-call">
              <div class="tool-call-head"><h4>{{ call.tool || 'unknown tool' }}</h4><StatusTag :status="call.status || 'failed'" /></div>
              <pre>{{ formatJson({ mcp_id: call.mcp_id, input: call.input, result: call.result }) }}</pre>
            </article>
          </div>
          <p v-else class="muted" style="font-size: 12px">本次执行没有记录 MCP 调用。</p>

          <NCollapse style="margin-top: 20px">
            <NCollapseItem title="查看完整执行详情" name="details">
              <pre class="prompt-block mono" style="font-size: 10px">{{ formatJson(selectedRun.details) }}</pre>
            </NCollapseItem>
          </NCollapse>
        </div>
        <div v-else class="empty-state">
          <div>
            <div class="empty-state-icon"><NIcon :component="Bolt" size="24" /></div>
            <h3>等待执行任务</h3>
            <p>左侧提交任务后，这里会显示后端响应及对应的运行记录。</p>
          </div>
        </div>
      </section>
    </div>

    <section class="surface panel run-history">
      <div class="section-heading"><div><h2>运行历史</h2><p>来自 `GET /api/agents/{id}/runs`</p></div><NIcon :component="History" class="muted" /></div>
      <div v-if="executionStore.loading" class="loading-stack"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
      <div v-else-if="executionStore.runs.length">
        <div v-for="run in executionStore.runs" :key="run.id" class="history-row" :style="selectedRun?.id === run.id ? { background: '#eef4f0' } : undefined" @click="executionStore.selectRun(run)">
          <StatusTag :status="run.status" />
          <div class="history-input truncate">{{ truncate(run.input, 120) }}</div>
          <div class="muted" style="font-size: 10px">{{ formatDuration(run.started_at, run.finished_at) }}</div>
          <div class="muted" style="font-size: 10px">{{ formatDate(run.started_at) }}</div>
        </div>
      </div>
      <div v-else class="empty-state empty-state-compact"><div><p>暂无运行记录。</p></div></div>
    </section>
  </div>
</template>
