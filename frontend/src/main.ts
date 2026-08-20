import { createPinia } from 'pinia'
import { createApp } from 'vue'
import {
  NAlert,
  NButton,
  NIcon,
  NInput,
  NMenu,
  NSelect,
  NTag,
} from 'naive-ui'

import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)

const naiveComponents = {
  NAlert,
  NButton,
  NIcon,
  NInput,
  NMenu,
  NSelect,
  NTag,
}

for (const [name, component] of Object.entries(naiveComponents)) {
  app.component(name, component)
}

app.use(createPinia()).use(router).mount('#app')
