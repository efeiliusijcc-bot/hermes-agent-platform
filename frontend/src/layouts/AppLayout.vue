<script setup lang="ts">
import { h, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { NIcon, type MenuOption } from 'naive-ui'
import {
  Apps,
  Hierarchy,
  ChevronLeft,
  ChevronRight,
  Menu2,
  PlugConnected,
  Robot,
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
  { label: renderLink('运行总览', 'dashboard'), key: 'dashboard', icon: renderIcon(Apps) },
  { label: renderLink('Agent 管理', 'agents'), key: 'agents', icon: renderIcon(Robot) },
  { label: renderLink('Skill 管理', 'skills'), key: 'skills', icon: renderIcon(Hierarchy) },
  { label: renderLink('MCP 管理', 'mcps'), key: 'mcps', icon: renderIcon(PlugConnected) },
]

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
          <strong>Hermes</strong>
          <span>Agent Control Center</span>
        </div>
      </div>

      <NMenu
        :value="String(route.name || '')"
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

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
