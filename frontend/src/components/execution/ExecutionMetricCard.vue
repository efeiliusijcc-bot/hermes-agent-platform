<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  note?: string
  tone?: 'neutral' | 'active' | 'success' | 'danger'
}>()
</script>

<template>
  <article class="execution-metric-card" :data-tone="tone || 'neutral'">
    <span>{{ label }}</span>
    <strong>{{ value }}</strong>
    <small v-if="note">{{ note }}</small>
  </article>
</template>
