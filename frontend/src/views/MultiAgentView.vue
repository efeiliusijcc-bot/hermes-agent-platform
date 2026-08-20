<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { NIcon, NModal } from 'naive-ui'
import { useRouter } from 'vue-router'
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronRight,
  GitBranch,
  PlayerPlay,
  Plus,
  Refresh,
  Search,
  Trash,
  UserCheck,
  Users,
  X,
} from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import TeamRunWorkspace from '@/components/orchestration/TeamRunWorkspace.vue'
import { platformApi } from '@/api/platform'
import type { Agent, AgentTask, AgentTeam, Workflow, WorkflowNode, WorkflowRun } from '@/types/api'

const loading = ref(false)
const runLoading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const notice = ref('')
const agents = ref<Agent[]>([])
const teams = ref<AgentTeam[]>([])
const workflows = ref<Workflow[]>([])
const runs = ref<WorkflowRun[]>([])
const runTasks = ref<AgentTask[]>([])
const selectedTeamId = ref<string | null>(null)
const selectedRunId = ref<string | null>(null)
const selectedWorkflowId = ref<string | null>(null)
const pollTimer = ref<number | null>(null)
const router = useRouter()
let runRequestSerial = 0
let pollInFlight = false

const teamForm = reactive({ name: '', description: '', ownerAgentId: '' })
const memberForm = reactive({ agentId: '', role: '', priority: 50 })
const workflowForm = reactive({ name: '', agentIds: [] as string[], humanApproval: false })
const runForm = reactive({ workflowId: '', input: '', priority: 5 })
const activeTab = ref<'members' | 'workflows' | 'run' | 'results'>('members')
const teamQuery = ref('')
const memberQuery = ref('')
const teamModalOpen = ref(false)
const memberModalOpen = ref(false)
const workflowModalOpen = ref(false)
const workflowStep = ref<1 | 2 | 3>(1)
const workflowCandidateId = ref('')

const managerOptions = computed(() => agents.value
  .filter((agent) => agent.agent_type === 'manager' && agent.status === 'active')
  .map((agent) => ({ label: `${agent.name} · ${agent.runtime_type}`, value: agent.id })))
const selectedTeam = computed(() => teams.value.find((team) => team.id === selectedTeamId.value) || null)
const filteredTeams = computed(() => {
  const keyword = teamQuery.value.trim().toLowerCase()
  if (!keyword) return teams.value
  return teams.value.filter((team) => [team.name, team.description || '', team.id]
    .some((value) => value.toLowerCase().includes(keyword)))
})
const memberCandidates = computed(() => {
  const keyword = memberQuery.value.trim().toLowerCase()
  const existing = new Set(selectedTeam.value?.members.map((member) => member.agent_id) || [])
  return agents.value.filter((agent) => {
    if (existing.has(agent.id)) return false
    if (agent.status !== 'active') return false
    return !keyword || [agent.name, agent.id, agent.role, agent.runtime_type, agent.model]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})
const teamWorkflows = computed(() => workflows.value.filter((workflow) => workflow.team_id === selectedTeamId.value))
const selectedWorkflow = computed(() => teamWorkflows.value.find((workflow) => workflow.id === selectedWorkflowId.value)
  || teamWorkflows.value[0]
  || null)
const workflowDraftMembers = computed(() => workflowForm.agentIds.map((agentId) => selectedTeam.value?.members
  .find((member) => member.agent_id === agentId)).filter((member): member is NonNullable<typeof member> => Boolean(member)))
const availableWorkflowMembers = computed(() => (selectedTeam.value?.members || [])
  .filter((member) => !workflowForm.agentIds.includes(member.agent_id)))
const workflowOptions = computed(() => [
  { label: '直接按团队并行执行', value: '' },
  ...teamWorkflows.value.filter((item) => item.status === 'active').map((item) => ({ label: item.name, value: item.id })),
])
const hasActiveRun = computed(() => runs.value.some((run) => ['pending', 'running', 'human_review'].includes(run.status)))

function stopPolling() {
  if (pollTimer.value !== null) window.clearTimeout(pollTimer.value)
  pollTimer.value = null
}

function schedulePolling(delay = 3000) {
  stopPolling()
  if (!hasActiveRun.value || document.hidden) return
  pollTimer.value = window.setTimeout(async () => {
    if (pollInFlight) return schedulePolling()
    pollInFlight = true
    try {
      await loadRunState(true)
    } finally {
      pollInFlight = false
      schedulePolling()
    }
  }, delay)
}

function handleVisibilityChange() {
  if (document.hidden) {
    stopPolling()
  } else if (hasActiveRun.value) {
    schedulePolling(0)
  }
}

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
  if (!teamForm.name.trim() || !teamForm.ownerAgentId) {
    error.value = '请填写团队名称并选择 Manager'
    return
  }
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
    teamForm.ownerAgentId = ''
    teamModalOpen.value = false
    selectedTeamId.value = team.id
    activeTab.value = 'members'
    await loadAll(true)
    notice.value = 'Agent Team 已创建'
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function addMember() {
  if (!selectedTeamId.value || !memberForm.agentId || !memberForm.role.trim()) {
    error.value = '请选择 Agent 并填写团队职责'
    return
  }
  actionLoading.value = true
  try {
    await platformApi.upsertTeamMember(selectedTeamId.value, memberForm.agentId, {
      role: memberForm.role.trim(),
      priority: memberForm.priority,
    })
    memberForm.agentId = ''
    memberForm.role = ''
    memberForm.priority = 50
    memberQuery.value = ''
    memberModalOpen.value = false
    await loadAll(true)
    notice.value = '成员已加入团队'
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
    notice.value = '成员已移除'
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

async function createWorkflow() {
  if (!selectedTeamId.value || !workflowForm.name.trim() || !workflowForm.agentIds.length) {
    error.value = '请填写 Workflow 名称并至少添加一个 Agent 节点'
    return
  }
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
    const workflow = await platformApi.createWorkflow({
      team_id: selectedTeamId.value,
      name: workflowForm.name.trim(),
      status: 'active',
      nodes,
    })
    workflowForm.name = ''
    workflowForm.agentIds = []
    workflowForm.humanApproval = false
    workflowCandidateId.value = ''
    workflowStep.value = 1
    workflowModalOpen.value = false
    await loadAll(true)
    selectedWorkflowId.value = workflow.id
    notice.value = 'Workflow DAG 已创建'
  } catch (value) {
    error.value = humanError(value)
  } finally {
    actionLoading.value = false
  }
}

function openTeamModal() {
  teamForm.name = ''
  teamForm.description = ''
  teamForm.ownerAgentId = ''
  teamModalOpen.value = true
}

function openMemberModal() {
  memberForm.agentId = ''
  memberForm.role = ''
  memberForm.priority = 50
  memberQuery.value = ''
  memberModalOpen.value = true
}

function chooseMember(agent: Agent) {
  memberForm.agentId = agent.id
  if (!memberForm.role) memberForm.role = agent.role || (agent.agent_type === 'manager' ? '协作 Manager' : '协作 Worker')
}

function openWorkflowModal() {
  workflowForm.name = ''
  workflowForm.agentIds = []
  workflowForm.humanApproval = false
  workflowCandidateId.value = ''
  workflowStep.value = 1
  workflowModalOpen.value = true
}

function addWorkflowNode() {
  if (!workflowCandidateId.value || workflowForm.agentIds.includes(workflowCandidateId.value)) return
  workflowForm.agentIds.push(workflowCandidateId.value)
  workflowCandidateId.value = ''
}

function moveWorkflowNode(index: number, direction: -1 | 1) {
  const next = index + direction
  if (next < 0 || next >= workflowForm.agentIds.length) return
  const [agentId] = workflowForm.agentIds.splice(index, 1)
  workflowForm.agentIds.splice(next, 0, agentId)
}

function removeWorkflowNode(index: number) {
  workflowForm.agentIds.splice(index, 1)
}

function nextWorkflowStep() {
  if (workflowStep.value === 1 && !workflowForm.name.trim()) {
    error.value = '请先填写 Workflow 名称'
    return
  }
  if (workflowStep.value === 2 && !workflowForm.agentIds.length) {
    error.value = '请至少添加一个 Agent 节点'
    return
  }
  if (workflowStep.value < 3) workflowStep.value = (workflowStep.value + 1) as 2 | 3
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
  selectedWorkflowId.value = null
  activeTab.value = 'members'
  void loadRunState(true)
})
watch(hasActiveRun, (active) => {
  if (active) schedulePolling()
  else stopPolling()
})

function openExecution(executionId: string) {
  void router.push({ name: 'execution-detail', params: { id: executionId } })
}

function openTrace(executionId: string) {
  void router.push({ name: 'trace-detail', params: { id: executionId } })
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  await loadAll()
  schedulePolling()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  stopPolling()
})
</script>

<template>
  <section class="multi-agent-page">
    <PageHeader eyebrow="ORCHESTRATION" title="团队编排" description="组织 Agent Team、设计 Workflow DAG，并在同一工作台运行和查看结果。">
      <template #actions>
        <NButton :loading="loading" @click="loadAll()"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
      </template>
    </PageHeader>

    <NAlert v-if="error" type="error" closable class="page-alert" @close="error = ''">{{ error }}</NAlert>
    <NAlert v-if="notice" type="success" closable class="page-alert" @close="notice = ''">{{ notice }}</NAlert>

    <div class="orchestration-metrics">
      <article><NIcon :component="Users" /><div><strong>{{ teams.length }}</strong><span>Agent Teams</span></div></article>
      <article><NIcon :component="GitBranch" /><div><strong>{{ workflows.length }}</strong><span>Workflows</span></div></article>
      <article><NIcon :component="PlayerPlay" /><div><strong>{{ runs.filter((run) => ['pending','running','human_review'].includes(run.status)).length }}</strong><span>活跃运行</span></div></article>
      <article><NIcon :component="UserCheck" /><div><strong>{{ runTasks.filter((task) => task.status === 'human_review').length }}</strong><span>待人工审批</span></div></article>
    </div>

    <div class="orchestration-shell">
      <aside class="team-directory" aria-label="Agent Team 列表">
        <div class="directory-heading">
          <div><strong>Agent Teams</strong><span>{{ teams.length }} 个团队</span></div>
          <NButton type="primary" size="small" aria-label="创建团队" @click="openTeamModal"><template #icon><NIcon :component="Plus" /></template>新建</NButton>
        </div>
        <NInput v-model:value="teamQuery" clearable placeholder="搜索团队名称或 ID">
          <template #prefix><NIcon :component="Search" /></template>
        </NInput>
        <div v-if="loading && !teams.length" class="team-list-loading">
          <span v-for="index in 4" :key="index" />
        </div>
        <div v-else-if="filteredTeams.length" class="team-list" role="listbox" aria-label="选择 Agent Team">
          <button
            v-for="team in filteredTeams"
            :key="team.id"
            type="button"
            role="option"
            :aria-selected="selectedTeamId === team.id"
            :class="{ active: selectedTeamId === team.id }"
            @click="selectedTeamId = team.id"
          >
            <span class="team-list-icon"><NIcon :component="Users" /></span>
            <span class="team-list-copy"><strong>{{ team.name }}</strong><small>{{ team.members.length }} 位成员 · {{ workflows.filter((item) => item.team_id === team.id).length }} 个 Workflow</small></span>
            <NIcon :component="ChevronRight" />
          </button>
        </div>
        <div v-else class="directory-empty">
          <NIcon :component="Users" />
          <strong>{{ teamQuery ? '没有匹配的团队' : '还没有 Agent Team' }}</strong>
          <span>{{ teamQuery ? '换个关键词试试' : '创建团队并指定 Manager 后开始编排' }}</span>
        </div>
      </aside>

      <main v-if="selectedTeam" class="team-workbench">
        <header class="team-summary">
          <div class="team-summary-main">
            <span class="team-avatar"><NIcon :component="Users" /></span>
            <div><span class="section-label">当前团队</span><h2>{{ selectedTeam.name }}</h2><p>{{ selectedTeam.description || '暂无团队职责说明' }}</p></div>
          </div>
          <div class="team-summary-actions">
            <StatusTag :status="selectedTeam.status" />
            <NButton secondary @click="openMemberModal"><template #icon><NIcon :component="Plus" /></template>新增成员</NButton>
            <NButton type="primary" @click="openWorkflowModal"><template #icon><NIcon :component="GitBranch" /></template>创建 Workflow</NButton>
          </div>
        </header>

        <nav class="workbench-tabs" aria-label="团队编排工作区">
          <button type="button" :class="{ active: activeTab === 'members' }" @click="activeTab = 'members'"><NIcon :component="Users" />团队成员 <span>{{ selectedTeam.members.length }}</span></button>
          <button type="button" :class="{ active: activeTab === 'workflows' }" @click="activeTab = 'workflows'"><NIcon :component="GitBranch" />Workflow DAG <span>{{ teamWorkflows.length }}</span></button>
          <button type="button" :class="{ active: activeTab === 'run' }" @click="activeTab = 'run'"><NIcon :component="PlayerPlay" />执行任务</button>
          <button type="button" :class="{ active: activeTab === 'results' }" @click="activeTab = 'results'"><NIcon :component="UserCheck" />运行结果 <span>{{ runs.length }}</span></button>
        </nav>

        <section v-if="activeTab === 'members'" class="workbench-section members-section">
          <div class="section-heading"><div><h3>团队成员</h3><p>Manager 负责拆解与汇总，Worker 按职责完成具体节点。</p></div><NButton type="primary" @click="openMemberModal"><template #icon><NIcon :component="Plus" /></template>新增成员</NButton></div>
          <div class="members-grid">
            <article v-for="member in selectedTeam.members" :key="member.agent_id" class="member-card">
              <div class="member-card-top"><span class="member-avatar">{{ member.agent_name.slice(0, 1).toUpperCase() }}</span><StatusTag :status="member.agent_type" /></div>
              <div><h4>{{ member.agent_name }}</h4><p>{{ member.role }}</p></div>
              <dl><div><dt>Runtime</dt><dd>{{ member.runtime_type }}</dd></div><div><dt>优先级</dt><dd>{{ member.priority }}</dd></div></dl>
              <footer><span class="mono">{{ member.agent_id }}</span><NButton v-if="member.agent_id !== selectedTeam.owner_agent_id" text type="error" @click="removeMember(member.agent_id)"><template #icon><NIcon :component="Trash" /></template>移除</NButton><span v-else class="owner-note">团队所有者</span></footer>
            </article>
          </div>
        </section>

        <section v-else-if="activeTab === 'workflows'" class="workbench-section workflow-section">
          <div class="section-heading"><div><h3>Workflow DAG</h3><p>左侧选择流程，右侧查看节点依赖和执行顺序。</p></div><NButton type="primary" @click="openWorkflowModal"><template #icon><NIcon :component="Plus" /></template>创建 Workflow</NButton></div>
          <div v-if="teamWorkflows.length" class="workflow-workspace">
            <div class="workflow-directory" role="listbox" aria-label="Workflow 列表">
              <button v-for="workflow in teamWorkflows" :key="workflow.id" type="button" role="option" :aria-selected="selectedWorkflow?.id === workflow.id" :class="{ active: selectedWorkflow?.id === workflow.id }" @click="selectedWorkflowId = workflow.id">
                <span><strong>{{ workflow.name }}</strong><small>{{ workflow.nodes.length }} 个节点</small></span><StatusTag :status="workflow.status" />
              </button>
            </div>
            <div v-if="selectedWorkflow" class="dag-canvas">
              <header><div><span class="section-label">流程预览</span><h4>{{ selectedWorkflow.name }}</h4></div><StatusTag :status="selectedWorkflow.status" /></header>
              <div class="dag-flow">
                <template v-for="(node, index) in selectedWorkflow.nodes" :key="node.key">
                  <article class="dag-node" :class="`node-${node.type}`">
                    <span class="dag-node-order">{{ index + 1 }}</span>
                    <div><small>{{ node.type === 'human_approval' ? '人工审批' : 'Agent 节点' }}</small><strong>{{ node.name }}</strong><span>{{ node.agent_id ? agents.find((agent) => agent.id === node.agent_id)?.name || node.agent_id : '无绑定 Agent' }}</span></div>
                    <p>{{ node.depends_on.length ? `依赖 ${node.depends_on.join(', ')}` : '入口节点，无前置依赖' }}</p>
                  </article>
                  <div v-if="index < selectedWorkflow.nodes.length - 1" class="dag-connector"><span /><NIcon :component="ArrowDown" /></div>
                </template>
              </div>
            </div>
          </div>
          <div v-else class="workbench-empty"><NIcon :component="GitBranch" /><h4>当前团队还没有 Workflow</h4><p>创建一个节点清晰、顺序可核对的 DAG。</p><NButton type="primary" @click="openWorkflowModal">创建第一个 Workflow</NButton></div>
        </section>

        <section v-else-if="activeTab === 'run'" class="workbench-section run-section">
          <div class="section-heading"><div><h3>执行团队任务</h3><p>选择直接并行或指定 Workflow，Manager 将负责最终汇总。</p></div></div>
          <div class="run-builder">
            <label><span>执行方式</span><NSelect v-model:value="runForm.workflowId" :options="workflowOptions" placeholder="选择执行方式" /></label>
            <label><span>任务内容</span><NInput v-model:value="runForm.input" type="textarea" :rows="8" maxlength="100000" show-count placeholder="说明目标、输入材料和期望输出" /></label>
            <div class="run-footer"><label><span>优先级</span><NInputNumber v-model:value="runForm.priority" :min="0" :max="9" /></label><NButton type="primary" size="large" :loading="actionLoading" :disabled="!runForm.input.trim()" @click="startRun"><template #icon><NIcon :component="PlayerPlay" /></template>启动多 Agent 执行</NButton></div>
          </div>
        </section>

        <TeamRunWorkspace
          v-else
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
      </main>

      <div v-else class="team-workbench team-workbench-empty"><div><NIcon :component="Users" /><h2>选择或创建一个 Agent Team</h2><p>团队是成员、Workflow 和运行历史的组织边界。</p><NButton type="primary" @click="openTeamModal">创建 Agent Team</NButton></div></div>
    </div>

    <NModal v-model:show="teamModalOpen" preset="card" title="创建 Agent Team" style="width:min(780px,calc(100vw - 32px))" :mask-closable="!actionLoading">
      <div class="team-modal-layout">
        <aside><span class="modal-symbol"><NIcon :component="Users" /></span><h3>先确定团队边界</h3><p>团队名称用于识别业务场景，Manager 是团队所有者，负责拆解任务和汇总结果。</p><ul><li><NIcon :component="Check" />创建后再添加 Worker</li><li><NIcon :component="Check" />每个团队仅有一个 Manager</li><li><NIcon :component="Check" />Workflow 只使用本团队成员</li></ul></aside>
        <div class="modal-form">
          <label><span>团队名称 <em>必填</em></span><NInput v-model:value="teamForm.name" maxlength="80" placeholder="例如：内网情报编报团队" /></label>
          <label><span>Manager Agent <em>必填</em></span><NSelect v-model:value="teamForm.ownerAgentId" filterable :options="managerOptions" placeholder="选择一个可用的 Manager" /></label>
          <label><span>团队职责说明</span><NInput v-model:value="teamForm.description" type="textarea" :rows="4" placeholder="说明团队负责什么、输出什么，以及主要协作边界" /></label>
        </div>
      </div>
      <template #footer><div class="modal-actions"><NButton :disabled="actionLoading" @click="teamModalOpen = false">取消</NButton><NButton type="primary" :loading="actionLoading" :disabled="!teamForm.name.trim() || !teamForm.ownerAgentId" @click="createTeam">创建团队</NButton></div></template>
    </NModal>

    <NModal v-model:show="memberModalOpen" preset="card" title="新增团队成员" style="width:min(980px,calc(100vw - 32px))" :mask-closable="!actionLoading">
      <div class="member-picker-layout">
        <section class="agent-picker">
          <div class="picker-heading"><div><strong>选择 Agent</strong><span>仅显示 active 且尚未加入当前团队的 Agent</span></div><NInput v-model:value="memberQuery" clearable placeholder="搜索名称、ID、Runtime 或模型"><template #prefix><NIcon :component="Search" /></template></NInput></div>
          <div v-if="memberCandidates.length" class="agent-picker-list">
            <button v-for="agent in memberCandidates" :key="agent.id" type="button" :class="{ active: memberForm.agentId === agent.id }" @click="chooseMember(agent)">
              <span class="member-avatar">{{ agent.name.slice(0, 1).toUpperCase() }}</span>
              <span class="agent-picker-copy"><strong>{{ agent.name }}</strong><small>{{ agent.runtime_type }} · {{ agent.model }}<br><span class="mono">{{ agent.id }}</span></small></span>
              <StatusTag :status="agent.agent_type" />
              <NIcon v-if="memberForm.agentId === agent.id" :component="Check" class="selected-check" />
            </button>
          </div>
          <div v-else class="picker-empty">没有可加入的 Agent</div>
        </section>
        <section class="member-config">
          <div><span class="section-label">成员配置</span><h3>{{ agents.find((agent) => agent.id === memberForm.agentId)?.name || '请先选择 Agent' }}</h3><p>职责会显示在团队和 DAG 节点中，优先级用于调度时排序。</p></div>
          <label><span>团队职责 <em>必填</em></span><NInput v-model:value="memberForm.role" :disabled="!memberForm.agentId" placeholder="例如：事实核验、材料分析" /></label>
          <label><span>调度优先级</span><NInputNumber v-model:value="memberForm.priority" :min="0" :max="100" :disabled="!memberForm.agentId" style="width:100%" /></label>
        </section>
      </div>
      <template #footer><div class="modal-actions"><NButton :disabled="actionLoading" @click="memberModalOpen = false">取消</NButton><NButton type="primary" :loading="actionLoading" :disabled="!memberForm.agentId || !memberForm.role.trim()" @click="addMember">加入团队</NButton></div></template>
    </NModal>

    <NModal v-model:show="workflowModalOpen" preset="card" title="创建 Workflow DAG" style="width:min(1040px,calc(100vw - 32px))" :mask-closable="!actionLoading">
      <div class="workflow-wizard-nav" aria-label="Workflow 创建进度">
        <button type="button" :class="{ active: workflowStep === 1, complete: workflowStep > 1 }" @click="workflowStep = 1"><span>1</span><div><strong>基础信息</strong><small>命名并说明用途</small></div></button>
        <i />
        <button type="button" :class="{ active: workflowStep === 2, complete: workflowStep > 2 }" :disabled="!workflowForm.name.trim()" @click="workflowStep = 2"><span>2</span><div><strong>节点编排</strong><small>添加并调整顺序</small></div></button>
        <i />
        <button type="button" :class="{ active: workflowStep === 3 }" :disabled="!workflowForm.name.trim() || !workflowForm.agentIds.length" @click="workflowStep = 3"><span>3</span><div><strong>检查并保存</strong><small>核对依赖关系</small></div></button>
      </div>

      <section v-if="workflowStep === 1" class="wizard-stage wizard-basics">
        <div class="wizard-intro"><span class="modal-symbol"><NIcon :component="GitBranch" /></span><h3>这个流程解决什么任务？</h3><p>名称应体现业务用途。保存后会归属当前 Team，并可在执行任务时直接选择。</p></div>
        <div class="modal-form"><label><span>Workflow 名称 <em>必填</em></span><NInput v-model:value="workflowForm.name" maxlength="100" placeholder="例如：材料分析与交叉核验" /></label><div class="team-context"><span>所属团队</span><strong>{{ selectedTeam?.name }}</strong><small>{{ selectedTeam?.members.length || 0 }} 位可编排成员</small></div></div>
      </section>

      <section v-else-if="workflowStep === 2" class="wizard-stage node-builder">
        <aside class="node-palette"><div><strong>添加 Agent 节点</strong><span>节点将按右侧顺序串行执行</span></div><NSelect v-model:value="workflowCandidateId" filterable :options="availableWorkflowMembers.map((member) => ({ label: `${member.agent_name} · ${member.role}`, value: member.agent_id }))" placeholder="选择团队成员" /><NButton block :disabled="!workflowCandidateId" @click="addWorkflowNode"><template #icon><NIcon :component="Plus" /></template>添加到流程</NButton><NCheckbox v-model:checked="workflowForm.humanApproval">在流程末尾增加人工审批</NCheckbox><p>当前版本创建线性 DAG。节点依赖会按排序自动生成。</p></aside>
        <div class="draft-flow">
          <div v-if="workflowDraftMembers.length" class="draft-node-list">
            <template v-for="(member, index) in workflowDraftMembers" :key="member.agent_id">
              <article class="draft-node"><span class="dag-node-order">{{ index + 1 }}</span><div><small>Agent 节点</small><strong>{{ member.role }}</strong><span>{{ member.agent_name }} · {{ member.runtime_type }}</span></div><div class="node-actions"><NButton quaternary circle size="small" :disabled="index === 0" aria-label="上移节点" @click="moveWorkflowNode(index, -1)"><NIcon :component="ArrowUp" /></NButton><NButton quaternary circle size="small" :disabled="index === workflowDraftMembers.length - 1" aria-label="下移节点" @click="moveWorkflowNode(index, 1)"><NIcon :component="ArrowDown" /></NButton><NButton quaternary circle size="small" type="error" aria-label="删除节点" @click="removeWorkflowNode(index)"><NIcon :component="X" /></NButton></div></article>
              <div v-if="index < workflowDraftMembers.length - 1 || workflowForm.humanApproval" class="draft-connector"><span />依赖上一步</div>
            </template>
            <article v-if="workflowForm.humanApproval" class="draft-node approval-node"><span class="dag-node-order"><NIcon :component="UserCheck" /></span><div><small>人工审批</small><strong>审批后继续</strong><span>由团队 Manager 处理</span></div></article>
          </div>
          <div v-else class="builder-empty"><NIcon :component="GitBranch" /><h4>从左侧添加第一个节点</h4><p>添加后可以调整顺序或移除节点。</p></div>
        </div>
      </section>

      <section v-else class="wizard-stage review-stage">
        <div class="review-summary"><span class="modal-symbol"><NIcon :component="Check" /></span><div><span class="section-label">准备保存</span><h3>{{ workflowForm.name }}</h3><p>{{ selectedTeam?.name }} · {{ workflowForm.agentIds.length + (workflowForm.humanApproval ? 1 : 0) }} 个节点</p></div></div>
        <div class="review-flow"><template v-for="(member, index) in workflowDraftMembers" :key="member.agent_id"><article><span>{{ index + 1 }}</span><div><small>Agent 节点</small><strong>{{ member.role }}</strong><p>{{ member.agent_name }}</p></div></article><div v-if="index < workflowDraftMembers.length - 1 || workflowForm.humanApproval" class="review-arrow"><NIcon :component="ArrowDown" /><span>依赖 step-{{ index + 1 }}</span></div></template><article v-if="workflowForm.humanApproval" class="approval-node"><span><NIcon :component="UserCheck" /></span><div><small>人工审批</small><strong>审批后继续</strong><p>流程末尾审批节点</p></div></article></div>
      </section>

      <template #footer><div class="modal-actions wizard-actions"><NButton :disabled="actionLoading" @click="workflowModalOpen = false">取消</NButton><span /><NButton v-if="workflowStep > 1" :disabled="actionLoading" @click="workflowStep = (workflowStep - 1) as 1 | 2">上一步</NButton><NButton v-if="workflowStep < 3" type="primary" @click="nextWorkflowStep">继续</NButton><NButton v-else type="primary" :loading="actionLoading" @click="createWorkflow">保存 Workflow</NButton></div></template>
    </NModal>
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
.orchestration-shell { display: grid; grid-template-columns: 286px minmax(0, 1fr); min-height: 680px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow-sm); }
.team-directory { display: flex; min-height: 0; flex-direction: column; gap: 14px; padding: 18px 14px; border-right: 1px solid var(--border-color); background: var(--surface-subtle); }
.directory-heading, .section-heading, .team-summary, .team-summary-main, .team-summary-actions, .member-card-top, .modal-actions, .picker-heading, .review-summary { display: flex; align-items: center; }
.directory-heading { justify-content: space-between; gap: 12px; }
.directory-heading strong, .directory-heading span { display: block; }
.directory-heading strong { font-size: 14px; }
.directory-heading span { margin-top: 3px; color: var(--text-muted); font-size: 11px; }
.team-list { display: grid; gap: 6px; min-height: 0; overflow-y: auto; padding-right: 2px; }
.team-list button { display: grid; grid-template-columns: 34px minmax(0,1fr) 16px; align-items: center; gap: 10px; width: 100%; padding: 11px; border: 1px solid transparent; border-radius: 11px; color: var(--text-primary); background: transparent; text-align: left; cursor: pointer; transition: background-color .16s ease, border-color .16s ease, transform .16s ease; }
.team-list button:hover { border-color: var(--border-color); background: var(--surface); }
.team-list button:active { transform: translateY(1px); }
.team-list button.active { border-color: color-mix(in srgb, var(--brand) 45%, var(--border-color)); background: var(--brand-soft); }
.team-list button > .n-icon { color: var(--text-muted); }
.team-list-icon, .team-avatar, .modal-symbol { display: grid; place-items: center; border-radius: 10px; color: var(--brand); background: var(--brand-soft); }
.team-list-icon { width: 34px; height: 34px; }
.team-list-copy { min-width: 0; }
.team-list-copy strong, .team-list-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.team-list-copy strong { font-size: 12px; }
.team-list-copy small { margin-top: 4px; color: var(--text-muted); font-size: 10px; }
.directory-empty, .workbench-empty, .team-workbench-empty > div, .builder-empty { display: grid; place-items: center; align-content: center; text-align: center; }
.directory-empty { flex: 1; gap: 7px; padding: 28px 10px; color: var(--text-muted); }
.directory-empty .n-icon { font-size: 28px; }
.directory-empty strong { color: var(--text-primary); font-size: 12px; }
.directory-empty span { font-size: 10px; }
.team-list-loading { display: grid; gap: 8px; }
.team-list-loading span { height: 58px; border-radius: 10px; background: var(--surface); animation: pulse 1.2s ease-in-out infinite alternate; }
.team-workbench { min-width: 0; }
.team-summary { justify-content: space-between; gap: 18px; padding: 22px 24px; border-bottom: 1px solid var(--border-color); }
.team-summary-main { min-width: 0; gap: 14px; }
.team-avatar { flex: none; width: 46px; height: 46px; font-size: 22px; }
.team-summary h2 { margin: 2px 0 4px; font-size: 20px; }
.team-summary p { max-width: 720px; margin: 0; overflow: hidden; color: var(--text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.team-summary-actions { flex: none; gap: 8px; }
.section-label { color: var(--text-muted); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.workbench-tabs { display: flex; gap: 4px; padding: 0 18px; overflow-x: auto; border-bottom: 1px solid var(--border-color); }
.workbench-tabs button { display: inline-flex; flex: none; align-items: center; gap: 7px; padding: 14px 12px 12px; border: 0; border-bottom: 2px solid transparent; color: var(--text-muted); background: transparent; font: inherit; font-size: 12px; cursor: pointer; }
.workbench-tabs button:hover { color: var(--text-primary); }
.workbench-tabs button.active { border-bottom-color: var(--brand); color: var(--text-primary); }
.workbench-tabs button span { display: grid; place-items: center; min-width: 19px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--surface-subtle); font-size: 9px; }
.workbench-section { min-height: 520px; padding: 24px; }
.section-heading { justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.section-heading h3 { margin: 0 0 5px; font-size: 16px; }
.section-heading p { margin: 0; color: var(--text-muted); font-size: 11px; }
.members-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.member-card { display: grid; gap: 14px; padding: 17px; border: 1px solid var(--border-color); border-radius: 13px; background: var(--surface-subtle); }
.member-card-top { justify-content: space-between; }
.member-avatar { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border-radius: 9px; color: var(--brand); background: var(--brand-soft); font-weight: 800; }
.member-card h4 { margin: 0 0 4px; font-size: 14px; }
.member-card p { margin: 0; color: var(--text-muted); font-size: 11px; }
.member-card dl { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 0; }
.member-card dl div { padding: 9px 10px; border-radius: 8px; background: var(--surface); }
.member-card dt, .member-card dd { margin: 0; }
.member-card dt { color: var(--text-muted); font-size: 9px; text-transform: uppercase; }
.member-card dd { margin-top: 4px; font-size: 11px; }
.member-card footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
.member-card footer > span:first-child { overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.owner-note { flex: none; color: var(--text-muted); font-size: 10px; }
.workflow-workspace { display: grid; grid-template-columns: 270px minmax(0,1fr); min-height: 440px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 13px; }
.workflow-directory { display: grid; align-content: start; gap: 5px; padding: 10px; overflow-y: auto; border-right: 1px solid var(--border-color); background: var(--surface-subtle); }
.workflow-directory button { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 8px; padding: 11px; border: 1px solid transparent; border-radius: 9px; color: var(--text-primary); background: transparent; text-align: left; cursor: pointer; }
.workflow-directory button:hover, .workflow-directory button.active { border-color: var(--border-color); background: var(--surface); }
.workflow-directory button.active { border-color: color-mix(in srgb, var(--brand) 45%, var(--border-color)); }
.workflow-directory strong, .workflow-directory small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-directory strong { font-size: 11px; }
.workflow-directory small { margin-top: 4px; color: var(--text-muted); font-size: 9px; }
.dag-canvas { min-width: 0; padding: 18px 22px; background: radial-gradient(circle at 1px 1px,color-mix(in srgb,var(--border-color) 70%,transparent) 1px,transparent 0); background-size: 20px 20px; }
.dag-canvas > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.dag-canvas h4 { margin: 3px 0 0; font-size: 14px; }
.dag-flow { display: grid; justify-items: center; max-width: 620px; margin: 0 auto; }
.dag-node, .draft-node { display: grid; grid-template-columns: 34px minmax(0,1fr); align-items: center; gap: 12px; width: min(100%,560px); padding: 13px; border: 1px solid var(--border-color); border-radius: 12px; background: color-mix(in srgb,var(--surface) 94%,transparent); box-shadow: var(--shadow-sm); }
.dag-node-order { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; color: var(--brand); background: var(--brand-soft); font-size: 11px; font-weight: 800; }
.dag-node small, .dag-node strong, .dag-node span, .draft-node small, .draft-node strong, .draft-node span { display: block; }
.dag-node small, .draft-node small { color: var(--text-muted); font-size: 9px; }
.dag-node strong, .draft-node strong { margin: 2px 0; font-size: 12px; }
.dag-node span, .draft-node span { color: var(--text-muted); font-size: 10px; }
.dag-node p { grid-column: 2; margin: 4px 0 0; color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
.node-human_approval { border-color: color-mix(in srgb,#d6a84c 55%,var(--border-color)); }
.dag-connector { display: grid; justify-items: center; height: 34px; color: var(--text-muted); font-size: 12px; }
.dag-connector span { width: 1px; height: 20px; background: var(--border-color); }
.workbench-empty { min-height: 420px; gap: 8px; color: var(--text-muted); }
.workbench-empty .n-icon { font-size: 34px; }
.workbench-empty h4 { margin: 5px 0 0; color: var(--text-primary); }
.workbench-empty p { margin: 0 0 10px; font-size: 11px; }
.run-builder { display: grid; gap: 18px; max-width: 880px; }
.run-builder > label, .modal-form label, .member-config label { display: grid; gap: 7px; }
.run-builder label > span, .modal-form label > span, .member-config label > span { font-size: 11px; font-weight: 700; }
.run-footer { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.run-footer label { display: grid; gap: 7px; color: var(--text-muted); font-size: 11px; }
.team-workbench-empty { min-height: 680px; }
.team-workbench-empty > div { height: 100%; gap: 9px; color: var(--text-muted); }
.team-workbench-empty .n-icon { font-size: 38px; }
.team-workbench-empty h2 { margin: 5px 0 0; color: var(--text-primary); font-size: 18px; }
.team-workbench-empty p { margin: 0 0 10px; font-size: 11px; }
.team-modal-layout { display: grid; grid-template-columns: 240px minmax(0,1fr); gap: 28px; }
.team-modal-layout > aside { padding: 20px; border-radius: 13px; background: var(--surface-subtle); }
.modal-symbol { width: 44px; height: 44px; font-size: 22px; }
.team-modal-layout h3, .wizard-intro h3, .member-config h3, .review-summary h3 { margin: 14px 0 7px; font-size: 16px; }
.team-modal-layout p, .wizard-intro p, .member-config p, .review-summary p { margin: 0; color: var(--text-muted); font-size: 11px; line-height: 1.65; }
.team-modal-layout ul { display: grid; gap: 9px; margin: 18px 0 0; padding: 0; list-style: none; }
.team-modal-layout li { display: flex; align-items: center; gap: 7px; font-size: 10px; }
.team-modal-layout li .n-icon { color: var(--brand); }
.modal-form { display: grid; align-content: start; gap: 18px; padding: 5px 0; }
.modal-form em, .member-config em { color: var(--error-color); font-style: normal; font-size: 9px; }
.modal-actions { justify-content: flex-end; gap: 9px; }
.member-picker-layout { display: grid; grid-template-columns: minmax(0,1.6fr) minmax(260px,.8fr); min-height: 480px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 13px; }
.agent-picker { display: grid; grid-template-rows: auto minmax(0,1fr); min-width: 0; padding: 16px; }
.picker-heading { justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.picker-heading > div { min-width: 170px; }
.picker-heading strong, .picker-heading span { display: block; }
.picker-heading strong { font-size: 13px; }
.picker-heading span { margin-top: 4px; color: var(--text-muted); font-size: 9px; }
.picker-heading .n-input { max-width: 310px; }
.agent-picker-list { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-content: start; gap: 8px; max-height: 410px; overflow-y: auto; }
.agent-picker-list button { position: relative; display: grid; grid-template-columns: 38px minmax(0,1fr) auto; align-items: center; gap: 10px; min-width: 0; padding: 12px; border: 1px solid var(--border-color); border-radius: 10px; color: var(--text-primary); background: var(--surface-subtle); text-align: left; cursor: pointer; }
.agent-picker-list button:hover, .agent-picker-list button.active { border-color: color-mix(in srgb,var(--brand) 55%,var(--border-color)); background: var(--brand-soft); }
.agent-picker-copy { min-width: 0; }
.agent-picker-copy strong, .agent-picker-copy small { display: block; overflow: hidden; text-overflow: ellipsis; }
.agent-picker-copy strong { font-size: 11px; white-space: nowrap; }
.agent-picker-copy small { margin-top: 4px; color: var(--text-muted); font-size: 9px; line-height: 1.5; }
.selected-check { position: absolute; right: 7px; bottom: 6px; color: var(--brand); }
.picker-empty { display: grid; place-items: center; min-height: 260px; color: var(--text-muted); font-size: 11px; }
.member-config { display: grid; align-content: start; gap: 18px; padding: 22px; border-left: 1px solid var(--border-color); background: var(--surface-subtle); }
.member-config h3 { margin-top: 4px; }
.workflow-wizard-nav { display: grid; grid-template-columns: 1fr 48px 1fr 48px 1fr; align-items: center; padding: 4px 0 20px; border-bottom: 1px solid var(--border-color); }
.workflow-wizard-nav button { display: flex; align-items: center; gap: 10px; padding: 0; border: 0; color: var(--text-muted); background: transparent; text-align: left; cursor: pointer; }
.workflow-wizard-nav button:disabled { cursor: not-allowed; opacity: .45; }
.workflow-wizard-nav button > span { display: grid; place-items: center; flex: none; width: 30px; height: 30px; border: 1px solid var(--border-color); border-radius: 9px; font-size: 10px; }
.workflow-wizard-nav button strong, .workflow-wizard-nav button small { display: block; }
.workflow-wizard-nav button strong { color: var(--text-primary); font-size: 11px; }
.workflow-wizard-nav button small { margin-top: 3px; font-size: 9px; }
.workflow-wizard-nav button.active > span, .workflow-wizard-nav button.complete > span { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }
.workflow-wizard-nav > i { height: 1px; background: var(--border-color); }
.wizard-stage { min-height: 430px; padding: 24px 0 4px; }
.wizard-basics { display: grid; grid-template-columns: minmax(260px,.8fr) minmax(0,1.2fr); gap: 32px; align-items: start; }
.wizard-intro { padding: 18px; }
.team-context { display: grid; grid-template-columns: 100px 1fr auto; align-items: center; gap: 12px; margin-top: 8px; padding: 14px; border-radius: 10px; background: var(--surface-subtle); }
.team-context > span, .team-context small { color: var(--text-muted); font-size: 10px; }
.team-context strong { font-size: 11px; }
.node-builder { display: grid; grid-template-columns: 270px minmax(0,1fr); gap: 18px; }
.node-palette { display: grid; align-content: start; gap: 12px; padding: 17px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--surface-subtle); }
.node-palette strong, .node-palette span { display: block; }
.node-palette strong { font-size: 12px; }
.node-palette span, .node-palette p { margin: 4px 0 0; color: var(--text-muted); font-size: 9px; line-height: 1.6; }
.draft-flow { min-height: 390px; padding: 16px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 12px; background: radial-gradient(circle at 1px 1px,color-mix(in srgb,var(--border-color) 70%,transparent) 1px,transparent 0); background-size: 20px 20px; }
.draft-node-list { display: grid; justify-items: center; }
.draft-node { grid-template-columns: 34px minmax(0,1fr) auto; }
.node-actions { display: flex; align-items: center; gap: 2px; }
.draft-connector { display: grid; justify-items: center; gap: 2px; height: 38px; color: var(--text-muted); font-size: 8px; }
.draft-connector span { width: 1px; height: 23px; background: var(--border-color); }
.draft-node-list > .draft-connector:last-of-type { display: none; }
.approval-node { border-color: color-mix(in srgb,#d6a84c 55%,var(--border-color)); }
.builder-empty { min-height: 350px; gap: 7px; color: var(--text-muted); }
.builder-empty .n-icon { font-size: 31px; }
.builder-empty h4 { margin: 4px 0 0; color: var(--text-primary); }
.builder-empty p { margin: 0; font-size: 10px; }
.review-stage { display: grid; grid-template-columns: 280px minmax(0,1fr); gap: 28px; align-items: start; }
.review-summary { align-items: flex-start; gap: 14px; padding: 18px; border-radius: 12px; background: var(--surface-subtle); }
.review-summary h3 { margin: 4px 0; }
.review-flow { display: grid; justify-items: center; max-height: 430px; overflow-y: auto; padding: 12px; }
.review-flow article { display: grid; grid-template-columns: 34px minmax(0,1fr); align-items: center; gap: 10px; width: min(100%,520px); padding: 12px; border: 1px solid var(--border-color); border-radius: 11px; background: var(--surface); }
.review-flow article > span { display: grid; place-items: center; width: 29px; height: 29px; border-radius: 8px; color: var(--brand); background: var(--brand-soft); font-size: 10px; font-weight: 800; }
.review-flow small, .review-flow strong, .review-flow p { display: block; }
.review-flow small { color: var(--text-muted); font-size: 8px; }
.review-flow strong { margin: 2px 0; font-size: 11px; }
.review-flow p { margin: 0; color: var(--text-muted); font-size: 9px; }
.review-arrow { display: grid; justify-items: center; gap: 1px; height: 38px; color: var(--text-muted); font-size: 8px; }
.review-arrow .n-icon { font-size: 15px; }
.wizard-actions > span { flex: 1; }
.mono { font-family: var(--font-mono); }
@keyframes pulse { from { opacity: .45; } to { opacity: .9; } }
@media (prefers-reduced-motion: reduce) { .team-list button, .team-list-loading span { transition: none; animation: none; } }
@media (max-width: 1180px) { .orchestration-metrics { grid-template-columns: repeat(2,1fr); } .orchestration-shell { grid-template-columns: 1fr; } .team-directory { max-height: 290px; border-right: 0; border-bottom: 1px solid var(--border-color); } .team-list { grid-template-columns: repeat(2,minmax(0,1fr)); } .members-grid, .agent-picker-list { grid-template-columns: 1fr; } .team-summary { align-items: flex-start; } .team-summary-actions { flex-wrap: wrap; justify-content: flex-end; } .workflow-workspace, .team-modal-layout, .member-picker-layout, .wizard-basics, .node-builder, .review-stage { grid-template-columns: 1fr; } .workflow-directory { grid-template-columns: repeat(2,minmax(0,1fr)); max-height: 220px; border-right: 0; border-bottom: 1px solid var(--border-color); } .member-config { border-top: 1px solid var(--border-color); border-left: 0; } }
@media (max-width: 620px) { .orchestration-metrics { grid-template-columns: 1fr; } .team-list { grid-template-columns: 1fr; } .team-summary { align-items: flex-start; flex-direction: column; padding: 18px; } .team-summary-actions { width: 100%; justify-content: flex-start; } .team-summary-actions .n-button { flex: 1; } .workbench-tabs { padding: 0 10px; } .workbench-section { padding: 18px 14px; } .members-grid, .workflow-directory { grid-template-columns: 1fr; } .section-heading { align-items: flex-start; flex-direction: column; } .run-footer { align-items: stretch; flex-direction: column; } .workflow-wizard-nav { grid-template-columns: repeat(3,1fr); gap: 6px; } .workflow-wizard-nav > i { display: none; } .workflow-wizard-nav button { align-items: flex-start; } .workflow-wizard-nav button small { display: none; } .picker-heading { align-items: stretch; flex-direction: column; } .team-context { grid-template-columns: 1fr; } .draft-node { grid-template-columns: 30px minmax(0,1fr); } .node-actions { grid-column: 2; } }
</style>
