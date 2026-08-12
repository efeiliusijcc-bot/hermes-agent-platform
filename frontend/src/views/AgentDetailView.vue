<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ArrowLeft, Hierarchy, Book2, Edit, PlugConnected, TestPipe } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import BindingDialog from '@/components/BindingDialog.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const agentId = computed(() => String(route.params.id))
const dialogType = ref<'skills' | 'mcps' | 'knowledge' | null>(null)
const saving = ref(false)

const skillOptions = computed(() => resourceStore.skills.map((item) => ({ label: `${item.name} (${item.id})`, value: item.id })))
const mcpOptions = computed(() => resourceStore.mcpServers.map((item) => ({ label: `${item.name} (${item.config.kind})`, value: item.id })))
const knowledgeOptions = computed(() => resourceStore.knowledgeSources.map((item) => ({ label: `${item.name} (${item.status})`, value: item.id })))

const dialogConfig = computed(() => {
  if (dialogType.value === 'skills') return { title: '编辑 Skill 绑定', description: 'Skill 由后端校验并在 Agent 执行时加载。', options: skillOptions.value, selected: agentStore.currentSkills.map((item) => item.id) }
  if (dialogType.value === 'mcps') return { title: '编辑 MCP 绑定', description: '第一阶段只允许平台 MCP Gateway 下的只读 filesystem/database 能力。', options: mcpOptions.value, selected: agentStore.currentMCPServers.map((item) => item.id) }
  return { title: '编辑知识源绑定', description: '绑定后，运行时会先检索活跃知识源，再将召回内容写入执行上下文。', options: knowledgeOptions.value, selected: agentStore.currentKnowledgeSources.map((item) => item.id) }
})

async function load() {
  await Promise.all([
    agentStore.fetchAgentDetail(agentId.value),
    resourceStore.fetchAll(),
  ]).catch(() => undefined)
}

async function saveBindings(selected: string[]) {
  saving.value = true
  try {
    if (dialogType.value === 'skills') await agentStore.syncSkills(agentId.value, selected)
    if (dialogType.value === 'mcps') await agentStore.syncMCPServers(agentId.value, selected)
    if (dialogType.value === 'knowledge') await agentStore.syncKnowledgeSources(agentId.value, selected)
    message.success('绑定已更新')
    dialogType.value = null
  } catch (error) {
    message.error(getApiErrorMessage(error), { duration: 6000 })
    await agentStore.fetchAgentDetail(agentId.value).catch(() => undefined)
  } finally {
    saving.value = false
  }
}

watch(agentId, load)
onMounted(load)
</script>

<template>
  <div>
    <PageHeader :title="agentStore.currentAgent?.name || 'Agent 详情'" :description="agentStore.currentAgent?.description || '查看平台中保存的 Agent 配置和绑定关系。'">
      <template #actions>
        <NButton @click="router.push({ name: 'agents' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回列表</NButton>
        <NButton type="primary" :disabled="agentStore.currentAgent?.status !== 'active'" @click="router.push({ name: 'agent-playground', params: { id: agentId } })">
          <template #icon><NIcon :component="TestPipe" /></template>打开执行台
        </NButton>
      </template>
    </PageHeader>

    <div v-if="agentStore.error" class="error-panel" style="margin-bottom: 16px">{{ agentStore.error }}</div>
    <div v-if="agentStore.detailLoading" class="detail-grid">
      <div class="loading-stack"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
      <div class="skeleton-line" style="height: 300px" />
    </div>
    <div v-else-if="agentStore.currentAgent" class="detail-grid">
      <div class="detail-stack">
        <section class="surface panel">
          <div class="section-heading"><div><h2>基础配置</h2><p>来自 `GET /api/agents/{id}`</p></div><StatusTag :status="agentStore.currentAgent.status" /></div>
          <dl class="definition-list" style="margin: 20px 0 0">
            <div class="definition-item"><dt>Agent ID</dt><dd class="mono">{{ agentStore.currentAgent.id }}</dd></div>
            <div class="definition-item"><dt>角色</dt><dd>{{ agentStore.currentAgent.role }}</dd></div>
            <div class="definition-item"><dt>模型配置</dt><dd class="mono">{{ JSON.stringify(agentStore.currentAgent.model_config) }}</dd></div>
            <div class="definition-item"><dt>更新时间</dt><dd>{{ formatDate(agentStore.currentAgent.updated_at) }}</dd></div>
          </dl>
          <NAlert type="warning" :bordered="false" style="margin-top: 18px">
            当前后端未提供 `PATCH /api/agents/{id}`，因此此页面不显示虚假的基础配置编辑入口。
          </NAlert>
        </section>

        <section class="surface panel">
          <div class="section-heading"><div><h2>System Prompt</h2><p>执行时与 Role、能力、知识和记忆共同组成最终输入</p></div></div>
          <pre class="prompt-block">{{ agentStore.currentAgent.system_prompt }}</pre>
        </section>
      </div>

      <aside class="detail-stack">
        <section class="surface panel">
          <div class="section-heading">
            <div><h2>Skill</h2><p>{{ agentStore.currentSkills.length }} 个已绑定</p></div>
            <NButton text type="primary" @click="dialogType = 'skills'"><template #icon><NIcon :component="Edit" /></template>编辑</NButton>
          </div>
          <div v-if="agentStore.currentSkills.length" class="binding-list">
            <div v-for="skill in agentStore.currentSkills" :key="skill.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="Hierarchy" /></span><div><strong>{{ skill.name }}</strong><span>{{ skill.id }}</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定 Skill</p>
        </section>

        <section class="surface panel">
          <div class="section-heading">
            <div><h2>MCP</h2><p>{{ agentStore.currentMCPServers.length }} 个只读能力</p></div>
            <NButton text type="primary" @click="dialogType = 'mcps'"><template #icon><NIcon :component="Edit" /></template>编辑</NButton>
          </div>
          <div v-if="agentStore.currentMCPServers.length" class="binding-list">
            <div v-for="server in agentStore.currentMCPServers" :key="server.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="PlugConnected" /></span><div><strong>{{ server.name }}</strong><span>{{ server.config.kind }} / read-only</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定 MCP</p>
        </section>

        <section class="surface panel">
          <div class="section-heading">
            <div><h2>Knowledge</h2><p>{{ agentStore.currentKnowledgeSources.length }} 个知识源</p></div>
            <NButton text type="primary" @click="dialogType = 'knowledge'"><template #icon><NIcon :component="Edit" /></template>编辑</NButton>
          </div>
          <div v-if="agentStore.currentKnowledgeSources.length" class="binding-list">
            <div v-for="source in agentStore.currentKnowledgeSources" :key="source.id" class="binding-row">
              <span class="binding-icon"><NIcon :component="Book2" /></span><div><strong>{{ source.name }}</strong><span>{{ source.status }}</span></div>
            </div>
          </div>
          <p v-else class="muted" style="font-size: 12px">未绑定知识源</p>
        </section>
      </aside>
    </div>

    <BindingDialog
      :show="dialogType !== null"
      :title="dialogConfig.title"
      :description="dialogConfig.description"
      :options="dialogConfig.options"
      :selected="dialogConfig.selected"
      :loading="saving"
      @update:show="dialogType = $event ? dialogType : null"
      @save="saveBindings"
    />
  </div>
</template>
