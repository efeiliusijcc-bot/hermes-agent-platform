<script setup lang="ts">
import { zhCN, dateZhCN, NConfigProvider, NDialogProvider, NMessageProvider } from 'naive-ui'

import { lightThemeOverrides } from '@/theme'
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="lightThemeOverrides">
    <NDialogProvider>
      <NMessageProvider placement="top-right">
        <RouterView />
      </NMessageProvider>
    </NDialogProvider>
  </NConfigProvider>
</template>
