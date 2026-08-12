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
        {
          path: 'agents/:id/playground',
          name: 'agent-playground',
          component: () => import('@/views/PlaygroundView.vue'),
          meta: { title: '执行台' },
        },
        { path: 'skills', name: 'skills', component: () => import('@/views/SkillListView.vue'), meta: { title: 'Skill 管理' } },
        { path: 'mcps', name: 'mcps', component: () => import('@/views/MCPListView.vue'), meta: { title: 'MCP 管理' } },
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
