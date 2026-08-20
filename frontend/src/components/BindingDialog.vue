<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NModal } from 'naive-ui'

const props = defineProps<{
  show: boolean
  title: string
  description: string
  options: Array<{ label: string; value: string }>
  selected: string[]
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  save: [selected: string[]]
}>()

const value = ref<string[]>([])

watch(
  () => [props.show, props.selected] as const,
  () => { value.value = [...props.selected] },
  { deep: true, immediate: true },
)

const selectedCount = computed(() => value.value.length)
</script>

<template>
  <NModal :show="show" preset="card" :title="title" style="width: min(560px, calc(100vw - 32px))" :mask-closable="!loading" @update:show="emit('update:show', $event)">
    <p class="muted" style="margin: 0 0 16px; font-size: 12px; line-height: 1.6">{{ description }}</p>
    <NSelect v-model:value="value" multiple filterable clearable :options="options" placeholder="选择需要绑定的资源" />
    <p class="muted" style="margin: 10px 0 0; font-size: 11px">已选择 {{ selectedCount }} 项。保存时只提交发生变化的绑定。</p>
    <template #footer>
      <div style="display: flex; justify-content: flex-end; gap: 10px">
        <NButton :disabled="loading" @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" :loading="loading" @click="emit('save', value)">保存绑定</NButton>
      </div>
    </template>
  </NModal>
</template>
