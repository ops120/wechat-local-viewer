<template>
  <div data-testid="orca-panel" class="orca-panel space-y-4">
    <!-- Provider identity -->
    <div class="flex items-center space-x-2">
      <img
        :src="ORCA_LOGO_URL"
        alt="OrcaRouter"
        class="orca-logo w-5 h-5 rounded"
        data-testid="orca-logo"
        @error="logoFailed = true"
        v-show="!logoFailed"
      />
      <span class="text-sm font-medium text-gray-700">OrcaRouter</span>
      <span data-testid="orca-api-base" class="text-[11px] text-gray-400">{{ apiBase }}</span>
    </div>

    <!-- Two explicit, independently usable authentication choices -->
    <div class="grid grid-cols-2 gap-2">
      <button
        type="button"
        data-testid="orca-auth-choice-api-key"
        class="px-3 py-2 rounded-lg text-xs font-medium border"
        :class="activeMethod === 'api_key'
          ? 'bg-green-50 border-green-400 text-green-700'
          : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'"
        :aria-pressed="activeMethod === 'api_key' ? 'true' : 'false'"
        @click="selectMethod('api_key')"
      >
        OrcaRouter - API<br />
        <span class="font-normal text-[10px]">粘贴已有 sk-orca-… Key</span>
      </button>
      <button
        type="button"
        data-testid="orca-auth-choice-pkce"
        class="px-3 py-2 rounded-lg text-xs font-medium border"
        :class="activeMethod === 'pkce'
          ? 'bg-green-50 border-green-400 text-green-700'
          : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'"
        :aria-pressed="activeMethod === 'pkce' ? 'true' : 'false'"
        @click="selectMethod('pkce')"
      >
        OrcaRouter - Auth<br />
        <span class="font-normal text-[10px]">浏览器授权登录</span>
      </button>
    </div>

    <!-- Credential state -->
    <div
      v-if="credentials.needs_reauth"
      data-testid="orca-needs-reauth"
      class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-2"
    >
      ⚠️ OrcaRouter 凭据已被拒绝（401）。请重新粘贴 API Key 或重新登录；系统不会自动刷新该凭据。
    </div>

    <div v-if="credentials.connected" class="text-xs text-gray-500 flex items-center justify-between">
      <span data-testid="orca-secret-masked">
        当前凭据：{{ credentials.api_key.configured ? credentials.api_key.secret_masked : credentials.pkce.secret_masked }}
        （{{ credentials.api_key.configured ? 'API Key' : 'Auth 登录' }}）
      </span>
      <button
        type="button"
        data-testid="orca-credential-clear"
        class="text-red-500 hover:text-red-600"
        @click="clearActive"
      >
        清除
      </button>
    </div>

    <!-- Choice 1: API key -->
    <div v-if="activeMethod === 'api_key'" data-testid="orca-api-key-section" class="space-y-2">
      <label class="block text-xs text-gray-500">API Key</label>
      <div class="flex items-center space-x-2">
        <input
          v-model="apiKeyInput"
          data-testid="orca-api-key-input"
          type="password"
          autocomplete="off"
          placeholder="sk-orca-…"
          class="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
        />
        <button
          type="button"
          data-testid="orca-api-key-save"
          class="px-3 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm font-medium"
          @click="saveApiKey"
        >
          保存
        </button>
      </div>
      <p class="text-[11px] text-gray-400">
        也可设置环境变量 <code>ORCA_API_KEY</code>。Key 只保存在本机后端，不会回传到浏览器。
      </p>
      <p v-if="apiKeyError" class="text-xs text-red-500" data-testid="orca-api-key-error">{{ apiKeyError }}</p>
      <a :href="ORCA_KEY_DASHBOARD_URL" target="_blank" rel="noopener noreferrer"
         class="inline-block text-[11px] text-green-600 hover:text-green-700">
        在 OrcaRouter 控制台管理 Key →
      </a>
    </div>

    <!-- Choice 2: OAuth 2.0 + PKCE (Flow B, out-of-band code) -->
    <div v-if="activeMethod === 'pkce'" data-testid="orca-pkce-section" class="space-y-2">
      <button
        type="button"
        data-testid="orca-pkce-connect"
        :disabled="busy"
        class="w-full px-3 py-2 bg-green-500 hover:bg-green-600 disabled:bg-gray-300 text-white rounded-lg text-sm font-medium"
        @click="connect"
      >
        {{ busy ? '等待授权…' : 'Connect with OrcaRouter' }}
      </button>

      <template v-if="authorizeUrl">
        <p class="text-[11px] text-gray-500">
          在浏览器中打开下面的链接并同意授权，然后把页面上显示的授权码粘贴回来：
        </p>
        <div class="flex items-center space-x-2">
          <input
            data-testid="orca-pkce-authorize-url"
            type="text"
            readonly
            :value="authorizeUrl"
            class="flex-1 px-2 py-1.5 bg-gray-50 rounded text-[11px] text-gray-500"
          />
          <a
            data-testid="orca-pkce-open"
            :href="authorizeUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="px-2 py-1.5 bg-gray-100 hover:bg-gray-200 rounded text-xs"
          >打开</a>
        </div>
        <div class="flex items-center space-x-2">
          <input
            v-model="codeInput"
            data-testid="orca-pkce-code-input"
            type="text"
            placeholder="粘贴授权码"
            class="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            @keydown.enter="exchange"
          />
          <button
            type="button"
            data-testid="orca-pkce-exchange"
            class="px-3 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm"
            @click="exchange"
          >连接</button>
        </div>
        <button
          type="button"
          data-testid="orca-pkce-cancel"
          class="text-[11px] text-gray-500 hover:text-gray-700"
          @click="cancel"
        >取消授权</button>
      </template>

      <p v-if="connectError" data-testid="orca-pkce-error" class="text-xs text-red-500">{{ connectError }}</p>
      <p v-if="connectWarning" class="text-xs text-yellow-600">{{ connectWarning }}</p>
      <p v-if="authorizing" data-testid="orca-pkce-busy" class="text-[11px] text-gray-400">
        正在等待 OrcaRouter 授权…
      </p>
    </div>

    <!-- Model: a real catalog-backed selector, never a free-text field -->
    <div class="space-y-1">
      <label class="block text-xs text-gray-500">Model</label>
      <OrcaModelSelect
        v-model="modelValue"
        capability="chat"
        :modality="modality"
        @invalid-selection="onInvalidSelection"
      />
      <p v-if="selectionNotice" data-testid="orca-selection-notice" class="text-[11px] text-yellow-600">
        {{ selectionNotice }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import OrcaModelSelect from './OrcaModelSelect.vue'
import { orcaApi } from '../orcarouter/api'
import { createOrcaConnectController } from '../orcarouter/connectController'
import {
  ORCA_API_BASE_FALLBACK,
  ORCA_LOGO_URL,
  ORCA_KEY_DASHBOARD_URL,
  type CredentialsSummary,
} from '../orcarouter/provider'

const props = withDefaults(
  defineProps<{
    modelValue: string
    /** Active OrcaRouter provider id, chosen in the settings panel. */
    provider: string
    modality?: string | null
  }>(),
  { modality: null },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:provider', value: string): void
  (e: 'update:credentials', value: CredentialsSummary): void
}>()

const ORCA_PROVIDER_API_ID = 'orcarouter'
const ORCA_PROVIDER_OAUTH_ID = 'orcarouter-oauth'

const logoFailed = ref(false)
const apiKeyInput = ref('')
const apiKeyError = ref('')
const codeInput = ref('')
const connectError = ref('')
const connectWarning = ref('')
const authorizeUrl = ref('')
const authorizing = ref(false)
const selectionNotice = ref('')

const EMPTY_ENTRY = {
  method: 'api_key' as const,
  configured: false,
  secret_masked: '',
  account_id: '',
  scope: '',
  state: 'unconfigured',
  generation: 0,
  updated_at: 0,
}

const credentials = ref<CredentialsSummary>({
  active_method: '',
  api_key: { ...EMPTY_ENTRY },
  pkce: { ...EMPTY_ENTRY, method: 'pkce' },
  connected: false,
  needs_reauth: false,
})

// Reported by the backend, so a self-hosted origin override is visible here
// instead of the UI claiming a hardcoded default.
const apiBase = ref(ORCA_API_BASE_FALLBACK)
const activeMethod = ref<'api_key' | 'pkce'>('api_key')
const busy = ref(false)
/**
 * Adopt the stored method once, on first load. Afterwards the user's explicit
 * choice wins: re-reading it on every credential refresh would yank the panel
 * back to the other method while they are mid-way through connecting.
 */
let methodInitialised = false

/**
 * One controller instance for the panel's lifetime. `pagehide` must leave it
 * usable without a remount, so nothing here tears the controller down.
 */
const controller = createOrcaConnectController({
  post: async (path, body, options) => {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
      keepalive: options?.keepalive,
    })
    if (!res.ok) {
      let detail: unknown = `HTTP ${res.status}`
      try {
        const payload = await res.json()
        detail = payload?.detail ?? detail
      } catch {
        /* keep the status line when the body is not JSON */
      }
      const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      ;(error as { detail?: unknown }).detail = detail
      throw error
    }
    return (await res.json()) as never
  },
  onChange: (state) => {
    busy.value = state.busy
    authorizing.value = state.busy
    connectError.value = state.errorMessage
    connectWarning.value = state.warning
    if (state.hint) authorizeUrl.value = state.hint
    if (state.status?.status === 'success') {
      connectError.value = ''
      codeInput.value = ''
      authorizeUrl.value = ''
    }
    void refreshCredentials()
  },
})

async function refreshCredentials() {
  try {
    const status = await orcaApi.status()
    credentials.value = status.credentials
    if (status.api_base) apiBase.value = status.api_base
    emit('update:credentials', status.credentials)
    if (
      !methodInitialised &&
      (status.credentials.active_method === 'api_key' || status.credentials.active_method === 'pkce')
    ) {
      activeMethod.value = status.credentials.active_method
      methodInitialised = true
    }
  } catch {
    /* status is advisory; a failure must not break the form */
  }
}

function selectMethod(method: 'api_key' | 'pkce') {
  activeMethod.value = method
  methodInitialised = true
  // Switching authentication method releases any in-flight authorization.
  void controller.cancel()
  authorizeUrl.value = ''
  connectError.value = ''
  connectWarning.value = ''
  codeInput.value = ''
  emit('update:provider', method === 'pkce' ? ORCA_PROVIDER_OAUTH_ID : ORCA_PROVIDER_API_ID)
}

async function saveApiKey() {
  apiKeyError.value = ''
  try {
    const payload = await orcaApi.saveApiKey(apiKeyInput.value)
    credentials.value = payload.credentials
    emit('update:credentials', payload.credentials)
    // The raw key is not kept in component state after it is stored.
    apiKeyInput.value = ''
  } catch (err) {
    apiKeyError.value = err instanceof Error ? err.message : String(err)
  }
}

async function clearActive() {
  const method = credentials.value.api_key.configured ? 'api_key' : 'pkce'
  const payload = await orcaApi.clearCredential(method)
  credentials.value = payload.credentials
  emit('update:credentials', payload.credentials)
}

async function connect() {
  connectError.value = ''
  connectWarning.value = ''
  const payload = await controller.startLogin()
  if (payload?.authorize_url) {
    authorizeUrl.value = payload.authorize_url
    // Best-effort: browsers may block programmatic opens; the URL stays visible
    // and copyable for the ones that do.
    try {
      window.open(payload.authorize_url, '_blank', 'noopener,noreferrer')
    } catch {
      /* the visible URL is the fallback */
    }
  }
}

async function exchange() {
  connectError.value = ''
  await controller.exchange(codeInput.value)
}

async function cancel() {
  await controller.cancel()
  authorizeUrl.value = ''
  codeInput.value = ''
  connectError.value = ''
}

function onInvalidSelection(previous: string) {
  selectionNotice.value = `已选模型 ${previous} 在当前能力下不可用，已清空，请重新选择。`
}

const modelValue = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

function onPageHide() {
  // Clear busy/hint synchronously in the handler itself, then cancel server-side.
  controller.handlePageHide()
  authorizing.value = false
  busy.value = false
  authorizeUrl.value = ''
}

onMounted(() => {
  window.addEventListener('pagehide', onPageHide)
  void refreshCredentials()
  void controller.refreshStatus()
})

onBeforeUnmount(() => {
  window.removeEventListener('pagehide', onPageHide)
  // A real unmount cancels server work without writing UI state.
  void controller.cancel()
})

watch(
  () => props.provider,
  (provider) => {
    if (provider === ORCA_PROVIDER_OAUTH_ID) activeMethod.value = 'pkce'
    else if (provider === ORCA_PROVIDER_API_ID) activeMethod.value = 'api_key'
    methodInitialised = true
  },
)

defineExpose({ controller, refreshCredentials })
</script>
