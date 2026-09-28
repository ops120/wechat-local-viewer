<template>
  <div ref="root" class="orca-model-select relative">
    <!-- Trigger -->
    <button
      type="button"
      data-testid="orca-model-trigger"
      :aria-expanded="open ? 'true' : 'false'"
      aria-haspopup="listbox"
      :disabled="disabled"
      class="orca-model-trigger w-full px-3 py-2 bg-gray-100 rounded-lg text-sm text-left flex items-center justify-between focus:outline-none focus:ring-2 focus:ring-green-500 disabled:opacity-60"
      @click="toggle"
    >
      <span class="truncate" :class="selected ? 'text-gray-800' : 'text-gray-400'">
        {{ selected ? selected.id : loading ? '加载模型目录…' : '请选择模型' }}
      </span>
      <span class="text-gray-400 ml-2 shrink-0">{{ open ? '▲' : '▼' }}</span>
    </button>

    <!-- Panel -->
    <div
      v-if="open"
      ref="panel"
      data-testid="orca-model-panel"
      role="listbox"
      class="orca-model-panel absolute right-0 z-50 w-full bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden"
      :class="dropUp ? 'bottom-full mb-1' : 'top-full mt-1'"
      :style="{ backgroundColor: '#ffffff', borderWidth: '1px', borderStyle: 'solid' }"
    >
      <div class="p-2 border-b border-gray-100">
        <input
          v-model="query"
          data-testid="orca-model-search"
          type="text"
          placeholder="搜索模型…"
          class="w-full px-2 py-1.5 bg-gray-100 rounded text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          @keydown.escape="close"
        />
      </div>

      <div class="px-3 py-1.5 flex items-center justify-between bg-gray-50">
        <span data-testid="orca-model-source" class="text-[11px] text-gray-500">
          {{ sourceLabel }}
        </span>
        <button
          type="button"
          data-testid="orca-model-refresh"
          class="text-[11px] text-green-600 hover:text-green-700"
          @click.stop="refresh"
        >
          刷新
        </button>
      </div>

      <div class="max-h-56 overflow-y-auto" data-testid="orca-model-options">
        <p v-if="loading" class="px-3 py-3 text-xs text-gray-400">正在加载模型目录…</p>
        <p v-else-if="error" class="px-3 py-3 text-xs text-red-500">{{ error }}</p>
        <p v-else-if="visibleOptions.length === 0" class="px-3 py-3 text-xs text-gray-400">
          当前能力下没有可用模型
        </p>
        <button
          v-for="option in visibleOptions"
          :key="option.id"
          type="button"
          role="option"
          :aria-selected="option.id === modelValue ? 'true' : 'false'"
          class="orca-model-option w-full text-left px-3 py-2 hover:bg-green-50 flex items-center justify-between"
          :class="option.id === modelValue ? 'bg-green-50' : ''"
          @click="choose(option.id)"
        >
          <span class="min-w-0">
            <span class="block text-sm text-gray-800 truncate">{{ option.id }}</span>
            <span v-if="option.name" class="block text-[11px] text-gray-400 truncate">{{ option.name }}</span>
          </span>
          <span v-if="option.reasoning_efforts && option.reasoning_efforts.length"
                class="text-[10px] text-gray-400 ml-2 shrink-0">
            {{ option.reasoning_efforts.join('/') }}
          </span>
        </button>
      </div>

      <p v-if="degraded" data-testid="orca-model-degraded" class="px-3 py-2 text-[11px] text-yellow-600 border-t border-gray-100">
        ⚠️ 目录降级：{{ detail || '使用已验证的内置列表' }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { orcaApi } from '../orcarouter/api'
import { filterModelOptions, isModelStillAllowed, type FilterCapability } from '../orcarouter/modelSelection'
import type { ModelOption } from '../orcarouter/provider'

const props = withDefaults(
  defineProps<{
    modelValue: string
    capability?: string
    modality?: string | null
    disabled?: boolean
  }>(),
  { capability: 'chat', modality: null, disabled: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'invalid-selection', value: string): void
  (e: 'options-loaded', options: ModelOption[]): void
}>()

const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const dropUp = ref(false)
const query = ref('')
const loading = ref(false)
const error = ref('')
const options = ref<ModelOption[]>([])
const source = ref<string>('seed')
const degraded = ref(true)
const detail = ref('')

const selected = computed(() => options.value.find((o) => o.id === props.modelValue) ?? null)

const visibleOptions = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return options.value
  return options.value.filter(
    (o) => o.id.toLowerCase().includes(q) || (o.name ?? '').toLowerCase().includes(q),
  )
})

const sourceLabel = computed(() => {
  if (source.value === 'live') return `实时目录 · ${options.value.length} 个模型`
  if (source.value === 'cache') return `最近一次目录 · ${options.value.length} 个模型`
  return `内置已验证列表 · ${options.value.length} 个模型`
})

async function load(force = false) {
  // Keep the panel open while options reload: the capability may have changed
  // underneath an open dropdown and the user should see the new list.
  loading.value = true
  error.value = ''
  try {
    const payload = force
      ? await orcaApi.refreshModels(props.capability, props.modality)
      : await orcaApi.models(props.capability, props.modality)
    // The backend already filters by capability; re-applying the same rule here
    // keeps the guarantee even if a cached payload predates a capability change.
    options.value = filterModelOptions(
      payload.options,
      props.capability as FilterCapability,
      props.modality,
    )
    source.value = payload.source
    degraded.value = payload.degraded
    detail.value = payload.detail
    // A selection that no longer survives the current capability filter is
    // cleared rather than silently kept.
    if (props.modelValue && !isModelStillAllowed(options.value, props.modelValue, props.capability as FilterCapability, props.modality)) {
      emit('update:modelValue', '')
      emit('invalid-selection', props.modelValue)
    }
    emit('options-loaded', options.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) {
    query.value = ''
    // The settings panel is a scrollable modal, so a dropdown anchored at the
    // bottom of the form would open into clipped space. Choose the side with
    // room, then bring the panel into view.
    const rect = root.value?.getBoundingClientRect()
    if (rect) {
      const below = window.innerHeight - rect.bottom
      const above = rect.top
      dropUp.value = below < 280 && above > below
    }
    void nextTick(() => panel.value?.scrollIntoView({ block: 'nearest' }))
  }
}

function close() {
  open.value = false
}

function choose(id: string) {
  emit('update:modelValue', id)
  close()
}

function onDocumentClick(event: MouseEvent) {
  if (!open.value) return
  const target = event.target as Node | null
  if (root.value && target && !root.value.contains(target)) close()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

function refresh() {
  void load(true)
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
  void load()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})

// Any change of capability or modality recomputes the option list.
watch(
  () => [props.capability, props.modality],
  () => {
    void load()
  },
)

defineExpose({ reload: load, isOpen: () => open.value, options: () => options.value })
</script>
