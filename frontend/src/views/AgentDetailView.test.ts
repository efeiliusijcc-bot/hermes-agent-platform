import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NIcon: { template: '<span><slot /></span>' },
  useDialog: () => ({ warning: vi.fn() }),
  useMessage: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}))

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { Agent, AgentEditorModel } from '@/types/api'
import AgentDetailView from './AgentDetailView.vue'

const agent: Agent = {
  id: 'pg-e2e-deepseek-20260819',
  name: 'PostgreSQL 双库 Agent',
  description: '数据库能力验收',
  agent_type: 'worker',
  parent_agent_id: null,
  role: '分析员',
  system_prompt: '只读分析',
  model_config: {},
  model: 'deepseek-test',
  prompt_template: '{{input}}',
  model_adapter: 'deepseek',
  runtime_type: 'deepseek',
  runtime_id: null,
  runtime_config: {},
  capability_profile: { workspace_type: 'document', required_tools: [], artifact_types: [] },
  api_enabled: true,
  status: 'active',
  response_mode: 'sync',
  input_schema: {},
  output_schema: {},
  current_version_id: 'published-version-id',
  created_at: '2026-08-19T00:00:00Z',
  updated_at: '2026-08-19T01:00:00Z',
}

const editor: AgentEditorModel = {
  mode: { management_key_required: false, read_only_without_key: false },
  agent: {
    id: agent.id,
    name: agent.name,
    description: agent.description,
    status: agent.status,
    version: 'v1',
    draft_version_id: null,
    display_version_id: 'published-version-id',
    version_source: 'published',
  },
  sections: {
    identity: { name: agent.name, description: agent.description, role: agent.role, system_prompt: agent.system_prompt },
    behavior: {
      runtime_type: 'deepseek', runtime_id: null, model: agent.model, model_adapter: 'deepseek',
      response_mode: 'sync', execution_mode: 'autonomous',
    },
    skills: [],
    capabilities: [
      {
        binding_id: 'binding-business',
        tool_alias: 'business_db_select',
        key: 'database.select',
        label: '执行只读查询',
        description: null,
        version: '1.0.0',
        state: 'READY',
        source_label: '直接绑定',
        connection_name: 'E2E PostgreSQL',
        database: 'business_db',
        scope_name: '业务库只读',
        scope_summary: 'E2E PostgreSQL · business_db · 业务库只读',
        requires_user_action: false,
        advanced: {},
      },
      {
        binding_id: 'binding-analytics',
        tool_alias: 'analytics_db_select',
        key: 'database.select',
        label: '执行只读查询',
        description: null,
        version: '1.0.0',
        state: 'READY',
        source_label: '直接绑定',
        connection_name: 'E2E PostgreSQL',
        database: 'analytics_db',
        scope_name: '分析库只读',
        scope_summary: 'E2E PostgreSQL · analytics_db · 分析库只读',
        requires_user_action: false,
        advanced: {},
      },
    ],
    input_output: { input_schema: {}, output_schema: {} },
  },
  preflight: { state: 'READY', issues: [] },
  actions: { can_test: false, can_publish: false },
}

describe('AgentDetailView published database bindings', () => {
  afterEach(() => vi.restoreAllMocks())

  it('uses the BFF published version and distinguishes database bindings by alias and scope', async () => {
    await router.push(`/agents/${agent.id}`)
    await router.isReady()
    vi.spyOn(platformApi, 'getAgent').mockResolvedValue(agent)
    vi.spyOn(platformApi, 'listAgentSkills').mockResolvedValue([])
    vi.spyOn(platformApi, 'listAgentMCPServers').mockResolvedValue([])
    vi.spyOn(platformApi, 'listAgentKnowledgeSources').mockResolvedValue([])
    vi.spyOn(platformApi, 'listSkills').mockResolvedValue([])
    vi.spyOn(platformApi, 'listMCPServers').mockResolvedValue([])
    vi.spyOn(platformApi, 'listKnowledgeSources').mockResolvedValue([])
    vi.spyOn(platformApi, 'listRuntimes').mockResolvedValue([])
    vi.spyOn(platformApi, 'listModels').mockResolvedValue([])
    vi.spyOn(platformApi, 'getAgentEditor').mockResolvedValue(editor)
    vi.spyOn(platformApi, 'listSessions').mockResolvedValue([])
    vi.spyOn(platformApi, 'listTasks').mockResolvedValue([])
    vi.spyOn(platformApi, 'listArtifacts').mockResolvedValue([])
    vi.spyOn(platformApi, 'getWorkspace').mockResolvedValue({
      agent_id: agent.id, root: `/workspace/${agent.id}`, session_count: 0, artifact_count: 0, size_bytes: 0,
    })
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue({
      items: [], total: 0, limit: 50, offset: 0,
      metrics: { total_executions: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0, success_rate: null },
    })
    vi.spyOn(platformApi, 'getAgentHealth').mockRejectedValue(new Error('not needed'))
    vi.spyOn(platformApi, 'listAgentVersions').mockResolvedValue([])

    const wrapper = mount(AgentDetailView, {
      global: {
        plugins: [createPinia(), router],
        stubs: {
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
          AgentConversationPanel: true,
          BindingDialog: true,
          NButton: { template: '<button><slot name="icon" /><slot /></button>' },
          NAlert: { template: '<div><slot /></div>' },
          NSelect: { template: '<div />' },
          NInput: { template: '<textarea />' },
          NFormItem: { template: '<label><slot /></label>' },
          NModal: { template: '<div><slot /></div>' },
          NDivider: { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('v1 · 已发布版本（只读）')
    expect(text).not.toContain('Current Version未发布')
    expect(text).toContain('business_db_select')
    expect(text).toContain('E2E PostgreSQL · business_db · 业务库只读')
    expect(text).toContain('analytics_db_select')
    expect(text).toContain('E2E PostgreSQL · analytics_db · 分析库只读')
    wrapper.unmount()
  })
})
