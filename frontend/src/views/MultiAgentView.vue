<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { GitBranch, PlayerPlay, Plus, Refresh, UserCheck, Users } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import TeamRunWorkspace from '@/components/orchestration/TeamRunWorkspace.vue'
import { platformApi } from '@/api/platform'
import type { Agent, AgentTask, AgentTeam, Workflow, WorkflowNode, WorkflowRun } from '@/types/api'

const loading = ref(false)
const runLoading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const agents = ref<Agent[]>([])
const teams = ref<AgentTeam[]>([])
const workflows = ref<Workflow[]>([])
const runs = ref<WorkflowRun[]>([])
const runTasks = ref<AgentTask[]>([])
const selectedTeamId = ref<string | null>(null)
const selectedRunId = ref<string | null>(null)
const pollTimer = ref<number | null>(null)
const router = useRouter()
let runRequestSerial = 0

const teamForm = reactive({ name: '', description: '', ownerAgentId: '' })
const memberForm = reactive({ agentId: '', role: '', priority: 50 })
const workflowForm = reactive({ name: '', agentIds: [] as string[], humanApproval: false })
const runForm = reactive({ workflowId: '', input: '', priority: 5 })

const managerOptions = computed(() => agents.value
  .filter((agent) => agent.agent_type === 'manager' && agent.status === 'active')
  .map((agent) => ({ label: `${agent.name} · ${agent.runtime_type}`, value: agent.id })))
const selectedTeam = computed(() => teams.value.find((team) => team.id === selectedTeamId.value) || null)
const memberOptions = computed(() => {
  const existing = new Set(selectedTeam.value?.members.map((member) => member.agent_id) || [])
  return agents.value
    .filter((agent) => agent.status === 'active' && !existing.has(agent.id))
    .map((agent) => ({ label: `${agent.name} · ${agent.agent_type}`, value: agent.id }))
})
const workflowAgentOptions = computed(() => (selectedTeam.value?.members || []).map((member) => ({
  label: `${member.agent_name} · ${member.role}`,
  value: member.agent_id,
})))
const teamWorkflows = computed(() => workflows.value.filter((workflow) => workflow.team_id === selectedTeamId.value))
const workflowOptions = computed(() => [
  { label: '直接按团队并行执行', value: '' },
  ...teamWorkflows.value.filter((item) => item.status === 'active').map((item) => ({ label: item.name, value: item.id })),
])

function humanError(value: unknown): string {
  if (value && typeof value === 'object' && 'response' in value) {
    const detail = (value as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (detail) return detail
  }
  return value instanceof Error ? value.message : '操作失败'
}

async function loadAll(silent = false) {
  if (!silent) loading.value = true
  try {
    const [agentValues, teamValues, workflowValues] = await Promise.all([
      platformApi.listAgents(),
      platformApi.listAgentTeams(),
      platformApi.listWorkflows(),
    ])
    agents.value = agentValues
    teams.value = teamValues
    workflows.value = workflowValues
    if (!selectedTeamId.value || !teamValues.some((team) => team.id === selectedTeamId.value)) {
      selectedTeamId.value = teamValues[0]?.id || null
    }
    await loadRunState(true)
    error.value = ''
  } catch (value) {
    error.value = humanError(value)
  } finally {
    loading.value = false
  }
}

async function loadRunState(silent = false) {
  const teamId = selectedTeamId.value
  const serial = ++runRequestSerial
  if (!teamId) {
    runs.value = []
    runTasks.value = []
    selectedRunId.value = null
    return
  }
  if (!silent || !runs.value.length) runLoading.value = true
  try {
    const runValues = await platformApi.listWorkflowRuns({ team_id: teamId })
    if (serial !== runRequestSerial || teamId !== selectedTeamId.value) return
    runs.value = [...runValues].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    const nextRunId = runs.value.some((run) => run.id === selectedRunId.value)
      ? selectedRunId.value
      : runs.value[0]?.id || null
    if (nextRunId !== selectedRunId.value) runTasks.value = []
    selectedRunId.value = nextRunId
    const taskValues = nextRunId ? await platformApi.listWorkflowRunTasks(nextRunId) : []
    if (serial !== runRequestSerial || teamId !== selectedTeamId.value) return
    runTasks.value = taskValues
    error.value = ''
  } catch (value) {
    if (serial === runRequestSerial) error.value = humanError(value)
  } finally {
    if (serial === runRequestSerial) runLoading.value = false
  }
}

async function selectRun(runId: string) {
  const serial = ++runRequestSerial
  selectedRunId.value = runId
  runTasks.value = []
  runLoading.value = true
  try {
    const taskValues = await platformApi.listWorkflowRunTasks(runId)
    if (serial !== runRequestSerial || selectedRunId.value !== runId) return
    runTasks.value = taskValues
    error.value = ''
  } catch (value) {
    if (serial === runRequestSerial) error.value = humanError(value)
  } finally {
    if (serial === runRequestSerial) runLoading.value = false
  }
}

async function createTeam() {
  if (!teamForm.name.trim() || !teamForm.ownerAgentId) return
  actionLoading.value = true
  try {
    const team = await platformApi.createAgentTeam({
      name: teamForm.name.trim(),
      description: teamForm.description.trim() || null,
      owner_agent_id: teamForm.ownerAgentId,
      status: 'active',
    })
    teamForm.name = ''
    teamForm.description = ''
    selectedTeamId.value = team.id
    await loadAll(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function addMember() {
  if (!selectedTeamId.value || !memberForm.agentId || !memberForm.role.trim()) return
  actionLoading.value = true
  try {
    await platformApi.upsertTeamMember(selectedTeamId.value, memberForm.agentId, {
      role: memberForm.role.trim(),
      priority: memberForm.priority,
    })
    memberForm.agentId = ''
    memberForm.role = ''
    memberForm.priority = 50
    await loadAll(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function removeMember(agentId: string) {
  if (!selectedTeamId.value) return
  actionLoading.value = true
  try {
    await platformApi.removeTeamMember(selectedTeamId.value, agentId)
    await loadAll(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function createWorkflow() {
  if (!selectedTeamId.value || !workflowForm.name.trim() || !workflowForm.agentIds.length) return
  const nodes: WorkflowNode[] = workflowForm.agentIds.map((agentId, index) => ({
    key: `step-${index + 1}`,
    type: 'agent' as const,
    name: selectedTeam.value?.members.find((member) => member.agent_id === agentId)?.role || `步骤 ${index + 1}`,
    agent_id: agentId,
    depends_on: index ? [`step-${index}`] : [],
    config: {},
  }))
  if (workflowForm.humanApproval) {
    nodes.push({
      key: 'human-approval',
      type: 'human_approval',
      name: '人工审批',
      agent_id: selectedTeam.value?.owner_agent_id || null,
      depends_on: [nodes[nodes.length - 1].key],
      config: {},
    })
  }
  actionLoading.value = true
  try {
    await platformApi.createWorkflow({
      team_id: selectedTeamId.value,
      name: workflowForm.name.trim(),
      status: 'active',
      nodes,
    })
    workflowForm.name = ''
    workflowForm.agentIds = []
    workflowForm.humanApproval = false
    await loadAll(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function startRun() {
  if (!selectedTeamId.value || !runForm.input.trim()) return
  actionLoading.value = true
  try {
    const payload = {
      input: runForm.input.trim(),
      session_id: `console-${Date.now()}`,
      priority: runForm.priority,
    }
    const run = runForm.workflowId
      ? await platformApi.runWorkflow(runForm.workflowId, payload)
      : await platformApi.runAgentTeam(selectedTeamId.value, payload)
    selectedRunId.value = run.id
    runForm.input = ''
    await loadRunState(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function review(task: AgentTask, approved: boolean) {
  actionLoading.value = true
  try {
    await platformApi.reviewHumanTask(task.id, approved, approved ? '控制台审批通过' : '控制台审批拒绝')
    await loadRunState(true)
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

watch(selectedTeamId, () => {
  runForm.workflowId = ''
  workflowForm.agentIds = []
  selectedRunId.value = null
  runs.value = []
  runTasks.value = []
  void loadRunState(true)
})

function openExecution(executionId: string) {
  void router.push({ name: 'execution-detail', params: { id: executionId } })
}

function openTrace(executionId: string) {
  void router.push({ name: 'trace-detail', params: { id: executionId } })
}

onMounted(async () => {
  await loadAll()
  pollTimer.value = window.setInterval(() => loadRunState(true), 3000)
})
onBeforeUnmount(() => {
  if (pollTimer.value) window.clearInterval(pollTimer.value)
})
</script>

<template>
  <section class="multi-agent-page">
    <PageHeader eyebrow="ORCHESTRATION" title="多 Agent 编排" description="管理 Agent Team、Workflow DAG 与并发执行。">
      <template #actions>
        <NButton :loading="loading" @click="loadAll()"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
      </template>
    </PageHeader>

    <NAlert v-if="error" type="error" closable class="page-alert" @close="error = ''">{{ error }}</NAlert>

    <div class="orchestration-metrics">
      <article><NIcon :component="Users" /><div><strong>{{ teams.length }}</strong><span>Agent Teams</span></div></article>
      <article><NIcon :component="GitBranch" /><div><strong>{{ workflows.length }}</strong><span>Workflows</span></div></article>
      <article><NIcon :component="PlayerPlay" /><div><strong>{{ runs.filter((run) => ['pending','running','human_review'].includes(run.status)).length }}</strong><span>活跃运行</span></div></article>
      <article><NIcon :component="UserCheck" /><div><strong>{{ runTasks.filter((task) => task.status === 'human_review').length }}</strong><span>待人工审批</span></div></article>
    </div>

    <div class="orchestration-grid">
      <section class="control-panel team-panel">
        <header><div><span>01</span><h2>团队</h2></div><small>Manager + Workers</small></header>
        <NSelect v-model:value="selectedTeamId" :options="teams.map((team) => ({ label: team.name, value: team.id }))" placeholder="选择 Agent Team" />
        <div v-if="selectedTeam" class="team-members">
          <div v-for="member in selectedTeam.members" :key="member.agent_id" class="member-row">
            <div class="member-avatar">{{ member.agent_name.slice(0, 1).toUpperCase() }}</div>
            <div><strong>{{ member.agent_name }}</strong><span>{{ member.role }} · {{ member.runtime_type }}</span></div>
            <StatusTag :status="member.agent_type" />
            <NButton v-if="member.agent_id !== selectedTeam.owner_agent_id" text type="error" @click="removeMember(member.agent_id)">移除</NButton>
          </div>
        </div>
        <NDivider>添加成员</NDivider>
        <div class="compact-form">
          <NSelect v-model:value="memberForm.agentId" :options="memberOptions" placeholder="选择 Agent" />
          <NInput v-model:value="memberForm.role" placeholder="团队职责，例如：市场分析" />
          <NInputNumber v-model:value="memberForm.priority" :min="0" :max="100" />
          <NButton type="primary" :disabled="!selectedTeamId" :loading="actionLoading" @click="addMember"><template #icon><NIcon :component="Plus" /></template>加入团队</NButton>
        </div>
        <NDivider>新建团队</NDivider>
        <div class="compact-form">
          <NInput v-model:value="teamForm.name" placeholder="团队名称" />
          <NSelect v-model:value="teamForm.ownerAgentId" :options="managerOptions" placeholder="Manager Agent" />
          <NInput v-model:value="teamForm.description" type="textarea" :rows="2" placeholder="团队职责说明" />
          <NButton secondary :loading="actionLoading" @click="createTeam">创建 Agent Team</NButton>
        </div>
      </section>

      <section class="control-panel workflow-panel">
        <header><div><span>02</span><h2>Workflow DAG</h2></div><small>依赖顺序与审批节点</small></header>
        <div v-if="teamWorkflows.length" class="workflow-list">
          <article v-for="workflow in teamWorkflows" :key="workflow.id">
            <div><strong>{{ workflow.name }}</strong><span>{{ workflow.nodes.length }} nodes</span></div>
            <StatusTag :status="workflow.status" />
            <div class="node-strip">
              <template v-for="(node, index) in workflow.nodes" :key="node.key">
                <span>{{ node.name }}</span><i v-if="index < workflow.nodes.length - 1">→</i>
              </template>
            </div>
          </article>
        </div>
        <NEmpty v-else description="当前团队还没有 Workflow" />
        <NDivider>创建线性 DAG</NDivider>
        <div class="compact-form">
          <NInput v-model:value="workflowForm.name" placeholder="Workflow 名称" />
          <NSelect v-model:value="workflowForm.agentIds" multiple :options="workflowAgentOptions" placeholder="按执行顺序选择 Agent" />
          <NCheckbox v-model:checked="workflowForm.humanApproval">末尾增加人工审批节点</NCheckbox>
          <NButton type="primary" :loading="actionLoading" @click="createWorkflow"><template #icon><NIcon :component="GitBranch" /></template>创建 Workflow</NButton>
        </div>
      </section>

      <section class="control-panel run-panel">
        <header><div><span>03</span><h2>执行任务</h2></div><small>并行调度与 Manager 汇总</small></header>
        <div class="compact-form">
          <NSelect v-model:value="runForm.workflowId" :options="workflowOptions" placeholder="选择执行方式" />
          <NInput v-model:value="runForm.input" type="textarea" :rows="5" maxlength="100000" show-count placeholder="输入需要团队协作完成的任务" />
          <div class="priority-row"><span>优先级</span><NInputNumber v-model:value="runForm.priority" :min="0" :max="9" /></div>
          <NButton type="primary" size="large" :loading="actionLoading" @click="startRun"><template #icon><NIcon :component="PlayerPlay" /></template>启动多 Agent 执行</NButton>
        </div>
      </section>

      <TeamRunWorkspace
        :runs="runs"
        :tasks="runTasks"
        :agents="agents"
        :selected-run-id="selectedRunId"
        :loading="runLoading"
        @select-run="selectRun"
        @refresh="loadRunState()"
        @review="review"
        @open-execution="openExecution"
        @open-trace="openTrace"
      />
    </div>
  </section>
</template>

<style scoped>
.multi-agent-page { display: grid; gap: 20px; }
.page-alert { margin-top: -8px; }
.orchestration-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.orchestration-metrics article { display: flex; align-items: center; gap: 14px; padding: 18px; border: 1px solid var(--border-color); border-radius: 14px; background: var(--surface); }
.orchestration-metrics .n-icon { color: var(--brand); font-size: 23px; }
.orchestration-metrics strong { display: block; font-size: 24px; line-height: 1; }
.orchestration-metrics span { display: block; margin-top: 6px; color: var(--text-muted); font-size: 12px; }
.orchestration-grid { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: 16px; align-items: start; }
.control-panel { padding: 20px; border: 1px solid var(--border-color); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow-sm); }
.control-panel > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.control-panel > header div { display: flex; align-items: center; gap: 10px; }
.control-panel > header span { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; color: var(--brand); background: var(--brand-soft); font-size: 11px; font-weight: 800; }
.control-panel h2 { margin: 0; font-size: 16px; }
.control-panel header small { color: var(--text-muted); }
.team-members, .workflow-list { display: grid; gap: 8px; margin-top: 14px; }
.member-row { display: grid; grid-template-columns: 36px 1fr auto auto; align-items: center; gap: 10px; padding: 10px; border-radius: 10px; background: var(--surface-subtle); }
.member-avatar { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; color: white; background: var(--brand); font-weight: 800; }
.member-row strong, .member-row span { display: block; }
.member-row span { margin-top: 3px; color: var(--text-muted); font-size: 11px; }
.compact-form { display: grid; gap: 10px; }
.workflow-list article { padding: 13px; border: 1px solid var(--border-color); border-radius: 11px; }
.workflow-list article > div:first-child { display: inline-flex; gap: 8px; align-items: baseline; }
.workflow-list article > div:first-child span { color: var(--text-muted); font-size: 11px; }
.workflow-list .status-tag { float: right; }
.node-strip { display: flex; align-items: center; gap: 6px; margin-top: 12px; overflow-x: auto; }
.node-strip span { flex: none; padding: 5px 8px; border-radius: 7px; background: var(--brand-soft); color: var(--brand-strong); font-size: 11px; }
.node-strip i { color: var(--text-muted); font-style: normal; }
.priority-row { display: flex; align-items: center; justify-content: space-between; color: var(--text-muted); font-size: 12px; }
.mono { font-family: var(--font-mono); }
@media (max-width: 1000px) { .orchestration-metrics { grid-template-columns: repeat(2, 1fr); } .orchestration-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .orchestration-metrics { grid-template-columns: 1fr; } .member-row { grid-template-columns: 34px 1fr auto; } .member-row .n-button { grid-column: 2 / -1; justify-self: start; } }
</style>
