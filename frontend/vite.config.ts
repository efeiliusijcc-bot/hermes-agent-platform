import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY || 'http://127.0.0.1:18088',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.VITE_DEV_API_PROXY || 'http://127.0.0.1:18088',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'happy-dom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
