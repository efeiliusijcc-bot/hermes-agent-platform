import { createPinia } from 'pinia'
import { createApp } from 'vue'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NMenu,
  NModal,
  NSelect,
  NSlider,
  NTag,
} from 'naive-ui'

import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)

const naiveComponents = {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NMenu,
  NModal,
  NSelect,
  NSlider,
  NTag,
}

for (const [name, component] of Object.entries(naiveComponents)) {
  app.component(name, component)
}

app.use(createPinia()).use(router).mount('#app')
