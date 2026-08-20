<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NCheckbox, NInput, NVirtualList } from 'naive-ui'

import type { DatabaseDiscovery } from '@/types/api'

type DatabaseNode = DatabaseDiscovery['databases'][number]
type ObjectType = 'all' | 'table' | 'view'

const props = withDefaults(defineProps<{
  database: DatabaseNode
  selectable?: boolean
  selectedKeys?: string[]
  disabled?: boolean
}>(), {
  selectable: false,
  selectedKeys: () => [],
  disabled: false,
})

const emit = defineEmits<{
  'update:selectedKeys': [value: string[]]
}>()

const searchInput = ref('')
const search = ref('')
const objectType = ref<ObjectType>('all')
let searchTimer: number | null = null

function objectKey(schema: string, type: 'table' | 'view', name: string) {
  return JSON.stringify([props.database.name, schema, type, name])
}

const objectRows = computed(() => props.database.schemas.flatMap((schema) => [
  ...schema.tables.map((item) => ({ ...item, type: 'table' as const })),
  ...schema.views.map((item) => ({ ...item, type: 'view' as const })),
].map((item) => ({
  ...item,
  key: objectKey(schema.name, item.type, item.name),
  schema: schema.name,
  columnPreview: item.columns.slice(0, 4).map((column) => column.name).join('、'),
}))))

const rows = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  return objectRows.value.filter((item) => {
    if (objectType.value !== 'all' && item.type !== objectType.value) return false
    if (!keyword) return true
    return item.schema.toLocaleLowerCase().includes(keyword)
      || item.name.toLocaleLowerCase().includes(keyword)
      || item.columns.some((column) => column.name.toLocaleLowerCase().includes(keyword))
  })
})

const selectedSet = computed(() => new Set(props.selectedKeys))
const visibleKeys = computed(() => rows.value.map((item) => item.key))
const totalTables = computed(() => props.database.schemas.reduce((total, schema) => total + schema.tables.length, 0))
const totalViews = computed(() => props.database.schemas.reduce((total, schema) => total + schema.views.length, 0))
const selectedCount = computed(() => props.selectedKeys.filter((value) => {
  try {
    const [database] = JSON.parse(value) as [string]
    return database === props.database.name
  } catch {
    return false
  }
}).length)

function toggle(key: string, checked: boolean) {
  const next = new Set(props.selectedKeys)
  if (checked) next.add(key)
  else next.delete(key)
  emit('update:selectedKeys', Array.from(next))
}

function selectVisible() {
  emit('update:selectedKeys', Array.from(new Set([...props.selectedKeys, ...visibleKeys.value])))
}

function clearVisible() {
  const visible = new Set(visibleKeys.value)
  emit('update:selectedKeys', props.selectedKeys.filter((value) => !visible.has(value)))
}

watch(searchInput, (value) => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    search.value = value
    searchTimer = null
  }, 150)
})

onBeforeUnmount(() => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
})

function setObjectType(value: ObjectType) {
  objectType.value = value
}
</script>

<template>
  <section class="object-browser" aria-label="数据库对象浏览器">
    <header class="browser-summary">
      <div>
        <strong>{{ database.name }}</strong>
        <span>{{ database.schemas.length }} 个 Schema，{{ totalTables }} 张表，{{ totalViews }} 个视图</span>
      </div>
      <span v-if="selectable" class="selection-count">已选择 {{ selectedCount }} 个对象</span>
    </header>

    <div class="browser-toolbar">
      <NInput v-model:value="searchInput" clearable aria-label="搜索数据库对象" placeholder="搜索 Schema、表、视图或字段" />
      <div class="type-filter" aria-label="对象类型筛选">
        <button type="button" data-filter="all" :class="{ active: objectType === 'all' }" @click="setObjectType('all')">全部</button>
        <button type="button" data-filter="table" :class="{ active: objectType === 'table' }" @click="setObjectType('table')">表</button>
        <button type="button" data-filter="view" :class="{ active: objectType === 'view' }" @click="setObjectType('view')">视图</button>
      </div>
      <template v-if="selectable">
        <NButton size="small" secondary :disabled="disabled || !visibleKeys.length" @click="selectVisible">选择当前结果</NButton>
        <NButton size="small" quaternary :disabled="disabled || !visibleKeys.length" @click="clearVisible">清空当前结果</NButton>
      </template>
    </div>

    <div class="object-scroll" :class="{ disabled }">
      <NVirtualList v-if="rows.length" :items="rows" :item-size="58" key-field="key" class="object-virtual-list">
        <template #default="{ item }">
          <div :key="item.key" class="db-object-row">
            <NCheckbox
              v-if="selectable"
              :checked="selectedSet.has(item.key)"
              :disabled="disabled"
              @update:checked="(checked: boolean) => toggle(item.key, checked)"
            >
              <strong>{{ item.name }}</strong>
            </NCheckbox>
            <strong v-else>{{ item.name }}</strong>
            <span class="schema-name">{{ item.schema }}</span>
            <span class="object-kind">{{ item.type === 'table' ? '表' : '视图' }}</span>
            <span class="column-count">{{ item.columns.length }} 个字段</span>
            <span class="column-preview">{{ item.columnPreview || '未读取字段' }}</span>
          </div>
        </template>
      </NVirtualList>
      <div v-else class="browser-empty">
        <strong>没有匹配的数据库对象</strong>
        <span>请调整搜索词或对象类型。</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.object-browser{display:grid;min-width:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface)}
.browser-summary{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border-bottom:1px solid var(--line)}
.browser-summary>div{display:grid;gap:4px}.browser-summary span{color:var(--muted);font-size:12px}.selection-count{white-space:nowrap;color:var(--ink)!important;font-weight:600}
.browser-toolbar{display:grid;grid-template-columns:minmax(220px,1fr) auto auto auto;gap:8px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line);background:var(--surface-subtle)}
.type-filter{display:flex;padding:3px;border:1px solid var(--line);border-radius:7px;background:var(--surface)}
.type-filter button{min-width:48px;padding:5px 10px;border:0;border-radius:5px;background:transparent;color:var(--muted);font:inherit;font-size:12px;cursor:pointer}
.type-filter button.active{background:var(--accent-soft);color:var(--ink)}
.type-filter button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.object-scroll{height:430px;padding:8px 12px 12px}.object-scroll.disabled{opacity:.55}.object-virtual-list{height:100%}
.db-object-row{display:grid;grid-template-columns:minmax(150px,1.2fr) minmax(90px,.65fr) 48px 72px;gap:4px 8px;align-items:center;min-width:0;height:52px;margin:3px 0;padding:7px 10px;border-radius:7px;background:var(--surface-subtle)}
.db-object-row>strong,.db-object-row :deep(.n-checkbox__label){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.db-object-row>strong,.db-object-row :deep(.n-checkbox__label strong){font-size:12px}.schema-name,.object-kind,.column-count{overflow:hidden;color:var(--muted);font-size:11px;text-overflow:ellipsis;white-space:nowrap}
.object-kind{justify-self:end}.column-count{justify-self:end}.column-preview{grid-column:1/-1;overflow:hidden;color:var(--muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.browser-empty{display:grid;place-items:center;gap:5px;min-height:180px;color:var(--muted);text-align:center}.browser-empty span{font-size:12px}
@media(max-width:760px){.browser-summary{align-items:flex-start;flex-direction:column}.browser-toolbar{grid-template-columns:1fr 1fr}.browser-toolbar :deep(.n-input){grid-column:1/-1}.object-scroll{height:360px}.db-object-row{grid-template-columns:minmax(130px,1fr) 48px 68px}.schema-name{display:none}}
</style>
