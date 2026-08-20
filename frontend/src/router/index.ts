import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '总览' } },
        { path: 'agents', name: 'agents', component: () => import('@/views/AgentListView.vue'), meta: { title: 'Agent 管理' } },
        { path: 'agents/new', name: 'agent-create', component: () => import('@/views/AgentCreateView.vue'), meta: { title: '创建 Agent' } },
        { path: 'agents/:id', name: 'agent-detail', component: () => import('@/views/AgentDetailView.vue'), meta: { title: 'Agent 详情' } },
        { path: 'chat', name: 'agent-chat', component: () => import('@/views/AgentChatView.vue'), meta: { title: '智能体聊天' } },
        { path: 'orchestration', name: 'multi-agent', component: () => import('@/views/MultiAgentView.vue'), meta: { title: '多 Agent 编排' } },
        { path: 'runtimes', name: 'runtimes', component: () => import('@/views/RuntimeListView.vue'), meta: { title: 'Runtime 管理' } },
        { path: 'models', name: 'models', component: () => import('@/views/ModelManagementView.vue'), meta: { title: '模型管理' } },
        {
          path: 'agents/:id/run',
          alias: ['agents/:id/execute', 'agents/:id/playground'],
          name: 'agent-playground',
          component: () => import('@/views/PlaygroundView.vue'),
          meta: { title: '执行工作台' },
        },
        { path: 'skills', name: 'skills', component: () => import('@/views/SkillListView.vue'), meta: { title: 'Skill 管理' } },
        { path: 'skills/:id', name: 'skill-detail', component: () => import('@/views/SkillListView.vue'), meta: { title: 'Skill 详情' } },
        { path: 'mcp', alias: 'mcps', name: 'mcps', component: () => import('@/views/MCPListView.vue'), meta: { title: 'MCP 管理' } },
        { path: 'mcp/:id', name: 'mcp-detail', component: () => import('@/views/MCPListView.vue'), meta: { title: 'MCP 详情' } },
        { path: 'artifacts', name: 'artifacts', component: () => import('@/views/ArtifactListView.vue'), meta: { title: 'Artifact 产物' } },
        { path: 'api-center', alias: 'apis', name: 'apis', component: () => import('@/views/APIManagementView.vue'), meta: { title: 'API Center' } },
        { path: 'operations', name: 'operations', component: () => import('@/views/OperationsView.vue'), meta: { title: '运行监控' } },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '平台设置' } },
        { path: 'platform/connections', name: 'platform-connections', component: () => import('@/views/PlatformConnectionsView.vue'), meta: { title: '连接与能力' } },
        { path: 'platform/database-connections', name: 'database-connections', component: () => import('@/views/DatabaseConnectionsView.vue'), meta: { title: '数据库连接' } },
        { path: 'executions', name: 'executions', component: () => import('@/views/execution/ExecutionCenterView.vue'), meta: { title: '执行中心' } },
        { path: 'trace', name: 'execution-trace', component: () => import('@/views/trace/TraceCenterView.vue'), meta: { title: 'Trace Center' } },
        {
          path: 'executions/:id',
          name: 'execution-detail',
          component: () => import('@/views/execution/ExecutionDetailView.vue'),
          meta: { title: '执行详情' },
        },
        {
          path: 'trace/:id',
          name: 'trace-detail',
          component: () => import('@/views/trace/TraceDetailView.vue'),
          meta: { title: 'Trace 详情' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '控制中心')} | Hermes Agent`
})

export default router
