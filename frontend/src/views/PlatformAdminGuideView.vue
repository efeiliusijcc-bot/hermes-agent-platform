<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Book2, Download, Menu2, Search } from '@vicons/tabler'
import { NDrawer, NDrawerContent, NIcon, NInput } from 'naive-ui'

import PageHeader from '@/components/PageHeader.vue'
import {
  guideSearchText,
  platformAdminGuide,
  renderPlatformAdminGuideMarkdown,
  type GuideSectionId,
} from '@/content/platformAdminGuide'

const route = useRoute()
const router = useRouter()
const query = ref('')
const mobileTocOpen = ref(false)
const validSections = new Set(platformAdminGuide.sections.map((section) => section.id))

const normalizedQuery = computed(() => query.value.trim().toLocaleLowerCase('zh-CN'))
const visibleSections = computed(() => {
  if (!normalizedQuery.value) return platformAdminGuide.sections
  return platformAdminGuide.sections.filter((section) => guideSearchText(section).includes(normalizedQuery.value))
})

function selectedSection(): GuideSectionId | null {
  const value = String(route.query.section || '')
  return validSections.has(value as GuideSectionId) ? value as GuideSectionId : null
}

async function scrollToSection(section: GuideSectionId, updateRoute = true) {
  if (updateRoute) await router.replace({ name: 'platform-admin-guide', query: { ...route.query, section } })
  await nextTick()
  document.getElementById(`guide-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  mobileTocOpen.value = false
}

function downloadMarkdown() {
  const blob = new Blob([renderPlatformAdminGuideMarkdown()], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'Hermes_Agent_Platform_Administration_Guide_CN.md'
  anchor.click()
  URL.revokeObjectURL(url)
}

watch(() => route.query.section, () => {
  const section = selectedSection()
  if (section) void scrollToSection(section, false)
})

onMounted(() => {
  const section = selectedSection()
  if (section) void scrollToSection(section, false)
})
</script>

<template>
  <div class="admin-guide-page">
    <PageHeader title="平台管理使用手册" :description="platformAdminGuide.description">
      <template #actions>
        <NButton class="guide-mobile-toc-button" secondary @click="mobileTocOpen = true"><template #icon><NIcon :component="Menu2" /></template>目录</NButton>
        <NButton secondary @click="downloadMarkdown"><template #icon><NIcon :component="Download" /></template>下载 Markdown</NButton>
      </template>
    </PageHeader>

    <div class="admin-guide-toolbar surface">
      <NInput v-model:value="query" clearable placeholder="搜索术语、字段、错误或操作步骤" aria-label="搜索使用手册">
        <template #prefix><NIcon :component="Search" /></template>
      </NInput>
      <span>更新日期 {{ platformAdminGuide.updated }}</span>
    </div>

    <div class="admin-guide-layout">
      <aside class="admin-guide-toc surface" aria-label="手册目录">
        <strong>目录</strong>
        <button v-for="section in platformAdminGuide.sections" :key="section.id" type="button" :class="{ active: selectedSection() === section.id }" @click="scrollToSection(section.id)">{{ section.title }}</button>
        <a href="#guide-glossary">统一术语表</a>
        <a href="#guide-statuses">状态说明</a>
        <a href="#guide-scenarios">常见场景</a>
      </aside>

      <main class="admin-guide-content">
        <section v-if="!normalizedQuery" class="guide-intro surface">
          <div class="guide-section-heading"><NIcon :component="Book2" size="22" /><div><h2>首次配置推荐顺序</h2><p>先让模型和 Runtime 可用，再逐层增加连接、资源和生产 API。</p></div></div>
          <ol class="guide-order-list">
            <li v-for="item in platformAdminGuide.recommendedOrder" :key="item.title"><button type="button" @click="scrollToSection(item.section)"><strong>{{ item.title }}</strong><span>{{ item.detail }}</span></button></li>
          </ol>
        </section>

        <div v-if="!visibleSections.length" class="guide-empty surface"><NIcon :component="Search" size="28" /><h2>没有找到相关内容</h2><p>请尝试搜索“模型名”“数据库密码”“Scope”“502”或其他更短的关键词。</p></div>

        <section v-for="section in visibleSections" :id="`guide-${section.id}`" :key="section.id" class="guide-chapter surface">
          <header><span>{{ section.menuPath }}</span><h2>{{ section.title }}</h2><p>{{ section.purpose }}</p></header>
          <div class="guide-two-column">
            <div><h3>使用前准备</h3><ul><li v-for="item in section.prerequisites" :key="item">{{ item }}</li></ul></div>
            <div><h3>成功标准</h3><ul><li v-for="item in section.success" :key="item">{{ item }}</li></ul></div>
          </div>
          <h3>字段说明</h3>
          <div class="guide-table-wrap"><table><thead><tr><th>字段</th><th>含义</th><th>推荐配置</th></tr></thead><tbody><tr v-for="field in section.fields" :key="field.name"><th>{{ field.name }}</th><td>{{ field.meaning }}</td><td>{{ field.recommendation }}</td></tr></tbody></table></div>
          <h3>操作步骤</h3>
          <ol class="guide-procedure"><li v-for="item in section.steps" :key="item">{{ item }}</li></ol>
          <h3>常见错误</h3>
          <div class="guide-table-wrap"><table><thead><tr><th>现象</th><th>常见原因</th><th>处理方法</th></tr></thead><tbody><tr v-for="item in section.errors" :key="item.symptom"><th>{{ item.symptom }}</th><td>{{ item.cause }}</td><td>{{ item.solution }}</td></tr></tbody></table></div>
          <div class="guide-security"><h3>安全注意事项</h3><ul><li v-for="item in section.security" :key="item">{{ item }}</li></ul></div>
        </section>

        <template v-if="!normalizedQuery">
          <section id="guide-glossary" class="guide-chapter surface"><header><h2>统一术语表</h2><p>配置前先统一这些概念，避免把模型、Runtime、Connector 和 Capability 混为一谈。</p></header><dl class="guide-glossary"><div v-for="item in platformAdminGuide.glossary" :key="item.term"><dt>{{ item.term }}</dt><dd>{{ item.definition }}</dd></div></dl></section>
          <section id="guide-statuses" class="guide-chapter surface"><header><h2>状态说明</h2><p>健康检查通过只代表当前探测成功，最终仍需真实端到端调用。</p></header><div class="guide-table-wrap"><table><thead><tr><th>状态</th><th>含义</th><th>建议操作</th></tr></thead><tbody><tr v-for="item in platformAdminGuide.statuses" :key="item.status"><th>{{ item.status }}</th><td>{{ item.meaning }}</td><td>{{ item.action }}</td></tr></tbody></table></div></section>
          <section id="guide-scenarios" class="guide-chapter surface"><header><h2>常见场景</h2></header><div class="guide-scenario-grid"><article v-for="scenario in platformAdminGuide.scenarios" :key="scenario.title"><h3>{{ scenario.title }}</h3><ol><li v-for="item in scenario.steps" :key="item">{{ item }}</li></ol></article></div></section>
        </template>
      </main>
    </div>

    <NDrawer v-model:show="mobileTocOpen" placement="left" width="min(86vw, 320px)">
      <NDrawerContent title="手册目录" closable>
        <nav class="guide-drawer-nav"><button v-for="section in platformAdminGuide.sections" :key="section.id" type="button" @click="scrollToSection(section.id)">{{ section.title }}</button></nav>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>
