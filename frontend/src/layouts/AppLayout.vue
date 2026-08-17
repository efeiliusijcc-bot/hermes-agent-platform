<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { NIcon, type MenuOption } from 'naive-ui'
import {
  Apps,
  Api,
  Archive,
  ChartBar,
  Hierarchy,
  GitBranch,
  Activity,
  ChevronLeft,
  ChevronRight,
  Menu2,
  PlugConnected,
  Robot,
  ListCheck,
  Server,
  Plus,
  Settings,
} from '@vicons/tabler'

import { useSystemStore } from '@/stores/system'

const route = useRoute()
const systemStore = useSystemStore()
const collapsed = ref(false)
const mobileOpen = ref(false)

function renderIcon(icon: typeof Apps) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function renderLink(label: string, name: string) {
  return () => h(RouterLink, { to: { name } }, { default: () => label })
}

const menuOptions: MenuOption[] = [
  { label: '工作台', key: 'workspace', type: 'group', children: [
    { label: renderLink('运行总览', 'dashboard'), key: 'dashboard', icon: renderIcon(Apps) },
  ] },
  { label: 'AGENT', key: 'agent-group', type: 'group', children: [
    { label: renderLink('Agent 列表', 'agents'), key: 'agents', icon: renderIcon(Robot) },
    { label: renderLink('创建 Agent', 'agent-create'), key: 'agent-create', icon: renderIcon(Plus) },
    { label: renderLink('多 Agent 编排', 'multi-agent'), key: 'multi-agent', icon: renderIcon(GitBranch) },
  ] },
  { label: '执行', key: 'execution-group', type: 'group', children: [
    { label: renderLink('执行历史', 'executions'), key: 'executions', icon: renderIcon(ListCheck) },
    { label: renderLink('Trace Center', 'execution-trace'), key: 'execution-trace', icon: renderIcon(Activity) },
  ] },
  { label: '能力资源', key: 'resource-group', type: 'group', children: [
    { label: renderLink('Skill Registry', 'skills'), key: 'skills', icon: renderIcon(Hierarchy) },
    { label: renderLink('MCP Registry', 'mcps'), key: 'mcps', icon: renderIcon(PlugConnected) },
    { label: renderLink('Artifacts', 'artifacts'), key: 'artifacts', icon: renderIcon(Archive) },
  ] },
  { label: '平台', key: 'platform-group', type: 'group', children: [
    { label: renderLink('运行时管理', 'runtimes'), key: 'runtimes', icon: renderIcon(Server) },
    { label: renderLink('API Center', 'apis'), key: 'apis', icon: renderIcon(Api) },
    { label: renderLink('Operations', 'operations'), key: 'operations', icon: renderIcon(ChartBar) },
    { label: renderLink('Settings', 'settings'), key: 'settings', icon: renderIcon(Settings) },
  ] },
]

const activeMenuKey = computed(() => {
  const name = String(route.name || '')
  if (['agent-detail', 'agent-playground'].includes(name)) return 'agents'
  if (name === 'execution-detail') return 'executions'
  if (name === 'trace-detail') return 'execution-trace'
  return name
})

const healthTimer = ref<number | null>(null)

onMounted(() => {
  systemStore.fetchHealth().catch(() => undefined)
  healthTimer.value = window.setInterval(() => systemStore.fetchHealth().catch(() => undefined), 30_000)
})

onBeforeUnmount(() => {
  if (healthTimer.value) window.clearInterval(healthTimer.value)
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': collapsed, 'mobile-menu-open': mobileOpen }">
    <button class="mobile-menu-button" type="button" aria-label="打开导航" @click="mobileOpen = true">
      <NIcon :component="Menu2" size="22" />
    </button>
    <div class="mobile-scrim" @click="mobileOpen = false" />

    <aside class="app-sidebar">
      <div class="brand">
        <div class="brand-mark"><NIcon :component="Robot" size="22" /></div>
        <div v-show="!collapsed" class="brand-copy">
          <strong>Hermes Platform</strong>
          <span>Enterprise Agent Console</span>
        </div>
      </div>

      <NMenu
        :value="activeMenuKey"
        :options="menuOptions"
        :collapsed="collapsed"
        :collapsed-width="72"
        :collapsed-icon-size="21"
        @update:value="mobileOpen = false"
      />

      <div class="sidebar-footer">
        <div v-show="!collapsed" class="system-health" :class="{ offline: !systemStore.health }">
          <span class="health-indicator" />
          <div>
            <strong>{{ systemStore.health ? '控制面正常' : '后端未连接' }}</strong>
            <span>{{ systemStore.health ? '数据库、记忆、知识服务在线' : systemStore.error || '正在检查状态' }}</span>
          </div>
        </div>
        <button class="collapse-button" type="button" :aria-label="collapsed ? '展开导航' : '收起导航'" @click="collapsed = !collapsed">
          <NIcon :component="collapsed ? ChevronRight : ChevronLeft" size="18" />
        </button>
      </div>
    </aside>

    <div class="app-workspace">
      <header class="app-topbar">
        <div>
          <span>AI Platform</span>
          <strong>{{ route.meta.title || '控制台' }}</strong>
        </div>
        <div class="topbar-health" :class="{ offline: !systemStore.health }">
          <span class="health-indicator" />
          {{ systemStore.health ? 'Runtime online' : 'Runtime unavailable' }}
        </div>
      </header>
      <main class="app-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>
