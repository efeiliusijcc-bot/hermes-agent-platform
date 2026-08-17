<script setup lang="ts">
import { onMounted } from 'vue'
import { NIcon } from 'naive-ui'
import { Adjustments, Archive, Database, Settings } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useSystemStore } from '@/stores/system'

const systemStore = useSystemStore()
onMounted(() => systemStore.fetchHealth().catch(() => undefined))
</script>

<template>
  <div>
    <PageHeader title="平台设置" description="展示平台运行边界；模型地址、模型名称和密钥统一在模型管理页面维护。">
      <template #actions><NButton secondary :loading="systemStore.loading" @click="systemStore.fetchHealth">刷新状态</NButton></template>
    </PageHeader>
    <div v-if="systemStore.error" class="error-panel" style="margin-bottom: 16px">{{ systemStore.error }}</div>
    <div class="settings-grid">
      <section class="surface panel">
        <div class="section-heading"><div><h2>运行模式</h2><p>由服务端环境变量和 Compose 配置控制</p></div><NIcon :component="Settings" size="20" /></div>
        <dl class="execution-definition-list">
          <div><dt>控制面</dt><dd><StatusTag :status="systemStore.health?.status || 'unknown'" /></dd></div>
          <div><dt>执行模式</dt><dd>Sync JSON / SSE Stream / Async Queue</dd></div>
          <div><dt>模型配置</dt><dd><RouterLink :to="{ name: 'models' }">进入模型管理</RouterLink></dd></div>
          <div><dt>基础设施</dt><dd>在服务端 `.env` 或部署清单中完成</dd></div>
          <div><dt>密钥策略</dt><dd>前端不读取、不回显服务端密钥</dd></div>
        </dl>
      </section>
      <section class="surface panel">
        <div class="section-heading"><div><h2>数据服务</h2><p>当前健康检查返回的实际组件状态</p></div><NIcon :component="Database" size="20" /></div>
        <dl class="execution-definition-list">
          <div><dt>PostgreSQL</dt><dd><StatusTag :status="systemStore.health?.database || 'unknown'" /></dd></div>
          <div><dt>Memory</dt><dd><StatusTag :status="systemStore.health?.memory || 'unknown'" /></dd></div>
          <div><dt>Knowledge</dt><dd><StatusTag :status="systemStore.health?.knowledge || 'unknown'" /></dd></div>
          <div><dt>Task Queue</dt><dd><StatusTag :status="systemStore.health?.queue || 'unknown'" /></dd></div>
        </dl>
      </section>
      <section class="surface panel">
        <div class="section-heading"><div><h2>Artifact 存储</h2><p>文件通过后端受控接口下载</p></div><NIcon :component="Archive" size="20" /></div>
        <dl class="execution-definition-list">
          <div><dt>Storage</dt><dd><StatusTag :status="systemStore.health?.artifact_storage || 'unknown'" /></dd></div>
          <div><dt>下载地址</dt><dd class="mono">/api/artifacts/{artifact_id}/download</dd></div>
          <div><dt>完整性</dt><dd>每个产物登记 size 与 SHA-256</dd></div>
        </dl>
      </section>
      <section class="surface panel">
        <div class="section-heading"><div><h2>安全边界</h2><p>控制台当前可验证的约束</p></div><NIcon :component="Adjustments" size="20" /></div>
        <ul class="settings-boundaries">
          <li>MCP 注册权限固定为 read_only。</li>
          <li>API Key 仅创建时展示一次，后续只显示前缀。</li>
          <li>Agent 发布后，生产配置通过 Version 管理。</li>
          <li>模型写操作需要单独的 MODEL_MANAGEMENT_API_KEY。</li>
          <li>完整管理员登录与 RBAC 尚未提供，控制台仍应由可信网关保护。</li>
        </ul>
      </section>
    </div>
  </div>
</template>
