<script setup lang="ts">
import { Book2 } from '@vicons/tabler'

import type { GuideSectionId } from '@/content/platformAdminGuide'

defineProps<{ section: GuideSectionId }>()
</script>

<template>
  <NButton secondary tag="a" :href="`/help/platform-management?section=${section}`">
    <template #icon><NIcon :component="Book2" /></template>
    查看使用手册
  </NButton>
</template>
