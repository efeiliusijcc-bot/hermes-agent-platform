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
  BoxModel,
  Plus,
  Settings,
  Key,
  Lock,
} from '@vicons/tabler'

import { useSystemStore } from '@/stores/system'
import { useManagementStore } from '@/stores/management'

const route = useRoute()
const systemStore = useSystemStore()
const managementStore = useManagementStore()
const collapsed = ref(false)
const mobileOpen = ref(false)
const keyDialogOpen = ref(false)
const managementKey = ref('')

function renderIcon(icon: typeof Apps) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function renderLink(label: string, name: string) {
  return () => h(RouterLink, { to: { name } }, { default: () => label })
}

const menuOptions: MenuOption[] = [
  { label: '工作台', key: 'workspace', type: 'group', children: [
    { label: renderLink('工作台', 'dashboard'), key: 'dashboard', icon: renderIcon(Apps) },
  ] },
  { label: '智能体', key: 'agent-group', type: 'group', children: [
    { label: renderLink('智能体列表', 'agents'), key: 'agents', icon: renderIcon(Robot) },
    { label: renderLink('创建智能体', 'agent-create'), key: 'agent-create', icon: renderIcon(Plus) },
    { label: renderLink('团队编排', 'multi-agent'), key: 'multi-agent', icon: renderIcon(GitBranch) },
  ] },
  { label: '资源', key: 'resource-group', type: 'group', children: [
    { label: renderLink('Skill', 'skills'), key: 'skills', icon: renderIcon(Hierarchy) },
    { label: renderLink('MCP 兼容资源', 'mcps'), key: 'mcps', icon: renderIcon(PlugConnected) },
    { label: renderLink('数据与产物', 'artifacts'), key: 'artifacts', icon: renderIcon(Archive) },
  ] },
  { label: '运行', key: 'execution-group', type: 'group', children: [
    { label: renderLink('执行历史', 'executions'), key: 'executions', icon: renderIcon(ListCheck) },
    { label: renderLink('执行 Trace', 'execution-trace'), key: 'execution-trace', icon: renderIcon(Activity) },
  ] },
  { label: '平台管理', key: 'platform-group', type: 'group', children: [
    { label: renderLink('连接与能力', 'platform-connections'), key: 'platform-connections', icon: renderIcon(PlugConnected) },
    { label: renderLink('模型管理', 'models'), key: 'models', icon: renderIcon(BoxModel) },
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

function unlockManagement() {
  if (!managementKey.value.trim()) return
  managementStore.unlock(managementKey.value)
  managementKey.value = ''
  keyDialogOpen.value = false
}

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
        <NButton v-if="managementStore.unlocked" size="small" quaternary @click="managementStore.lock()">
          <template #icon><NIcon :component="Lock" /></template>
          锁定管理模式
        </NButton>
        <NButton v-else size="small" secondary @click="keyDialogOpen = true">
          <template #icon><NIcon :component="Key" /></template>
          管理员解锁
        </NButton>
      </header>
      <main class="app-main">
        <RouterView />
      </main>
    </div>
    <NModal v-model:show="keyDialogOpen" preset="card" title="解锁管理模式" style="width: min(460px, calc(100vw - 32px))">
      <p class="muted" style="margin: 0 0 16px; line-height: 1.6">密钥只保存在当前页面内存中，刷新或锁定后立即清除。</p>
      <NFormItem label="平台管理密钥" required>
        <NInput v-model:value="managementKey" type="password" show-password-on="click" placeholder="PLATFORM_MANAGEMENT_API_KEY" @keyup.enter="unlockManagement" />
      </NFormItem>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px">
          <NButton @click="keyDialogOpen = false">取消</NButton>
          <NButton type="primary" :disabled="!managementKey.trim()" @click="unlockManagement">解锁</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>
