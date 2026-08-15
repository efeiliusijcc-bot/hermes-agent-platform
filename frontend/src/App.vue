<script setup lang="ts">
import { zhCN, dateZhCN, darkTheme, NConfigProvider, NDialogProvider, NMessageProvider } from 'naive-ui'

import { darkThemeOverrides } from '@/theme'
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme="darkTheme" :theme-overrides="darkThemeOverrides">
    <NDialogProvider>
      <NMessageProvider placement="top-right">
        <RouterView />
      </NMessageProvider>
    </NDialogProvider>
  </NConfigProvider>
</template>
