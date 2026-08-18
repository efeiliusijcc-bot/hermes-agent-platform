<script setup lang="ts">
import { computed } from 'vue'
import { NInputNumber, NSwitch } from 'naive-ui'

import { normalizeSchemaFields } from '@/utils/executionStudio'

const props = defineProps<{
  schema: Record<string, unknown>
  values: Record<string, unknown>
  errors: Record<string, string>
  disabled?: boolean
  uiSchema?: Record<string, unknown>
}>()

const emit = defineEmits<{ 'update:values': [value: Record<string, unknown>] }>()
const fields = computed(() => {
  const values = normalizeSchemaFields(props.schema)
  const order = Array.isArray(props.uiSchema?.order) ? props.uiSchema.order.map(String) : []
  return [...values].sort((left, right) => {
    const leftIndex = order.indexOf(left.key)
    const rightIndex = order.indexOf(right.key)
    return (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex)
  })
})

function uiField(key: string): Record<string, unknown> {
  const values = props.uiSchema?.fields
  if (!values || typeof values !== 'object' || Array.isArray(values)) return {}
  const field = (values as Record<string, unknown>)[key]
  return field && typeof field === 'object' && !Array.isArray(field) ? field as Record<string, unknown> : {}
}

function update(key: string, value: unknown) {
  emit('update:values', { ...props.values, [key]: value })
}
</script>

<template>
  <div v-if="fields.length" class="schema-form">
    <div v-for="field in fields" :key="field.key" class="schema-field">
      <label :for="`schema-${field.key}`">
        {{ String(uiField(field.key).label || field.label) }}
        <span v-if="field.required" class="required-mark">必填</span>
      </label>
      <p v-if="uiField(field.key).help || field.description" class="schema-helper">{{ String(uiField(field.key).help || field.description) }}</p>
      <NSelect
        v-if="field.enumValues.length"
        :value="values[field.key]"
        :options="field.enumValues.map((value) => ({ label: String(value), value }))"
        :disabled="disabled"
        clearable
        @update:value="update(field.key, $event)"
      />
      <NSwitch
        v-else-if="field.type === 'boolean'"
        :value="Boolean(values[field.key])"
        :disabled="disabled"
        @update:value="update(field.key, $event)"
      >
        <template #checked>开启</template>
        <template #unchecked>关闭</template>
      </NSwitch>
      <NInputNumber
        v-else-if="field.type === 'number' || field.type === 'integer'"
        :id="`schema-${field.key}`"
        :value="typeof values[field.key] === 'number' ? values[field.key] as number : null"
        :precision="field.type === 'integer' ? 0 : undefined"
        :disabled="disabled"
        clearable
        @update:value="update(field.key, $event)"
      />
      <NInput
        v-else-if="uiField(field.key).widget === 'textarea'"
        :id="`schema-${field.key}`"
        :value="String(values[field.key] ?? '')"
        type="textarea"
        :rows="Number(uiField(field.key).rows || 4)"
        :disabled="disabled || uiField(field.key).readonly === true"
        @update:value="update(field.key, $event)"
      />
      <NInput
        v-else-if="field.type === 'array' || field.type === 'object'"
        :id="`schema-${field.key}`"
        :value="String(values[field.key] ?? '')"
        type="textarea"
        :rows="3"
        :disabled="disabled"
        :placeholder="field.type === 'array' ? '[item]' : '{ key: value }'"
        @update:value="update(field.key, $event)"
      />
      <NInput
        v-else
        :id="`schema-${field.key}`"
        :value="String(values[field.key] ?? '')"
        :disabled="disabled"
        @update:value="update(field.key, $event)"
      />
      <p v-if="errors[field.key]" class="schema-error">{{ errors[field.key] }}</p>
    </div>
  </div>
  <div v-else class="schema-empty">当前 Agent 没有定义额外输入字段。</div>
</template>
