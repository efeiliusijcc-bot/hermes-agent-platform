<script setup lang="ts">
import { computed } from 'vue'
import { NDrawer, NDrawerContent } from 'naive-ui'

import StatusTag from '@/components/StatusTag.vue'
import { formatDate } from '@/utils/format'
import { formatCount, formatDurationMs, formatJson } from '@/utils/executionStudio'
import type { Artifact, ExecutionStep, ExecutionTrace } from '@/types/api'

const props = defineProps<{
  show: boolean
  node: ExecutionStep | null
  trace: ExecutionTrace | null
}>()

const emit = defineEmits<{ 'update:show': [value: boolean] }>()

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

const artifact = computed<Artifact | null>(() => {
  if (!props.node || !props.trace || props.node.step_type !== 'artifact') return null
  const id = String(objectValue(props.node.output_data).artifact_id || '')
  return props.trace.artifacts.find((item) => item.id === id) || null
})

const skillIds = computed(() => {
  const value = objectValue(props.node?.output_data).skill_ids
  return Array.isArray(value) ? value.map(String) : []
})

const mcpId = computed(() => String(objectValue(props.node?.output_data).mcp_id || '--'))
const tool = computed(() => props.node?.step_name.startsWith('MCP Call:') ? props.node.step_name.slice(9).trim() : '--')
const promptTokens = computed(() => objectValue(props.node?.output_data).prompt_tokens ?? null)
const completionTokens = computed(() => objectValue(props.node?.output_data).completion_tokens ?? null)
</script>

<template>
  <NDrawer :show="show" width="min(520px, 100vw)" placement="right" @update:show="emit('update:show', $event)">
    <NDrawerContent :title="node?.step_name || 'Trace 节点'" closable>
      <template v-if="node">
        <div class="trace-drawer-summary">
          <StatusTag :status="node.status" />
          <span class="mono">{{ node.step_type }}</span>
          <span class="mono">{{ formatDurationMs(node.latency_ms) }}</span>
        </div>

        <NAlert v-if="node.error" type="error" :title="node.error" class="trace-drawer-error" />

        <dl v-if="node.step_type === 'skill'" class="trace-node-definition">
          <div><dt>Skill Name</dt><dd>{{ skillIds.length ? skillIds.join(', ') : '未加载 Skill' }}</dd></div>
          <div><dt>Version</dt><dd>当前 Trace 未记录</dd></div>
          <div><dt>Load Time</dt><dd>{{ formatDurationMs(node.latency_ms) }}</dd></div>
        </dl>

        <dl v-else-if="node.step_type === 'mcp'" class="trace-node-definition">
          <div><dt>MCP</dt><dd class="mono">{{ mcpId }}</dd></div>
          <div><dt>Tool</dt><dd class="mono">{{ tool }}</dd></div>
          <div><dt>Latency</dt><dd>{{ formatDurationMs(node.latency_ms) }}</dd></div>
        </dl>

        <dl v-else-if="node.step_type === 'runtime'" class="trace-node-definition">
          <div><dt>Runtime</dt><dd class="mono">{{ trace?.runtime_type || '--' }}</dd></div>
          <div><dt>Runtime Version</dt><dd class="mono">{{ trace?.runtime_version || '--' }}</dd></div>
          <div><dt>Runtime ID</dt><dd class="mono">{{ trace?.runtime_id || '环境变量默认端点' }}</dd></div>
          <div><dt>Latency</dt><dd>{{ formatDurationMs(node.latency_ms) }}</dd></div>
        </dl>

        <dl v-else-if="node.step_type === 'model' || node.step_key.startsWith('hermes_runtime') || node.step_key.startsWith('pi_runtime')" class="trace-node-definition">
          <div><dt>Model</dt><dd class="mono">{{ trace?.model || '--' }}</dd></div>
          <div><dt>Adapter</dt><dd>{{ trace?.model_adapter || '--' }}</dd></div>
          <div><dt>Prompt Tokens</dt><dd>{{ promptTokens === null ? '当前 Trace 未记录' : formatCount(Number(promptTokens)) }}</dd></div>
          <div><dt>Completion Tokens</dt><dd>{{ completionTokens === null ? '当前 Trace 未记录' : formatCount(Number(completionTokens)) }}</dd></div>
          <div><dt>Execution Token</dt><dd>{{ formatCount(trace?.token_usage) }}</dd></div>
          <div><dt>Latency</dt><dd>{{ formatDurationMs(node.latency_ms) }}</dd></div>
        </dl>

        <dl v-else-if="node.step_type === 'artifact'" class="trace-node-definition">
          <div><dt>Artifact ID</dt><dd class="mono">{{ artifact?.id || objectValue(node.output_data).artifact_id || '--' }}</dd></div>
          <div><dt>Filename</dt><dd>{{ artifact?.filename || objectValue(node.output_data).filename || '--' }}</dd></div>
          <div><dt>Storage</dt><dd class="mono">{{ artifact?.storage_type || '--' }} / {{ artifact?.storage_path || '--' }}</dd></div>
          <div><dt>SHA-256</dt><dd class="mono">{{ artifact?.sha256 || '--' }}</dd></div>
        </dl>

        <dl class="trace-node-definition">
          <div><dt>Step Key</dt><dd class="mono">{{ node.step_key }}</dd></div>
          <div><dt>Started</dt><dd>{{ formatDate(node.started_at) }}</dd></div>
          <div><dt>Finished</dt><dd>{{ formatDate(node.finished_at) }}</dd></div>
        </dl>

        <section class="trace-payload-section"><h3>Input</h3><pre class="json-viewer">{{ formatJson(node.input_data) }}</pre></section>
        <section class="trace-payload-section"><h3>Output</h3><pre class="json-viewer">{{ formatJson(node.output_data) }}</pre></section>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
