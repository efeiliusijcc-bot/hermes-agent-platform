<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  note?: string
  primary?: boolean
}>()
</script>

<template>
  <article class="metric surface" :class="{ 'metric-primary': primary }">
    <div class="metric-icon"><slot name="icon" /></div>
    <div class="metric-value">{{ value }}</div>
    <div class="metric-label">{{ label }}</div>
    <div v-if="note" class="metric-note">{{ note }}</div>
  </article>
</template>
