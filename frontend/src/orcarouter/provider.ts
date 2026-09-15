/**
 * OrcaRouter provider constants shared by the settings UI and the chat client.
 *
 * Both entries are first-class named providers: they are never derived from a
 * generic "custom base URL" field, and they are shown as two explicit choices
 * rather than one button that sometimes prompts for a key and sometimes opens
 * a browser.
 */

export const ORCA_PROVIDER_API = 'orcarouter'
export const ORCA_PROVIDER_OAUTH = 'orcarouter-oauth'

export const ORCA_PROVIDERS = [
  { id: ORCA_PROVIDER_API, label: 'OrcaRouter - API', method: 'api_key' as const },
  { id: ORCA_PROVIDER_OAUTH, label: 'OrcaRouter - Auth', method: 'pkce' as const },
]

export type OrcaProviderId = typeof ORCA_PROVIDER_API | typeof ORCA_PROVIDER_OAUTH
export type CredentialMethod = 'api_key' | 'pkce'

/**
 * Display fallback only. The backend resolves the origins (honouring
 * ORCA_BASE_URL / ORCA_AUTH_BASE_URL / ORCA_API_BASE_URL) and reports them in
 * GET /api/orcarouter/status, which is what the UI shows. Never derive one
 * origin from the other, and never build a request URL from these.
 */
export const ORCA_API_BASE_FALLBACK = 'https://api.orcarouter.ai/v1'
export const ORCA_KEY_DASHBOARD_URL = 'https://www.orcarouter.ai/console/authorized-apps'
export const ORCA_LOGO_URL = 'https://www.orcarouter.ai/orca-logo-classic.png'

export type Capability = 'chat' | 'embedding' | 'image' | 'video' | 'rerank'

export interface ModelOption {
  id: string
  name: string
  context_length: number | null
  max_completion_tokens: number | null
  input_modalities: string[]
  supported_endpoint_types: string[]
  reasoning_efforts: string[]
  source: string
}

export interface ModelOptionsPayload {
  capability: Capability
  modality: string | null
  source: 'live' | 'cache' | 'seed' | string
  degraded: boolean
  detail: string
  count: number
  options: ModelOption[]
}

export interface CredentialEntry {
  method: CredentialMethod
  configured: boolean
  secret_masked: string
  account_id: string
  scope: string
  state: 'unconfigured' | 'ok' | 'needs_reauth' | string
  generation: number
  updated_at: number
}

export interface CredentialsSummary {
  active_method: string
  api_key: CredentialEntry
  pkce: CredentialEntry
  connected: boolean
  needs_reauth: boolean
}

export interface ConnectState {
  attempt: number
  status: 'idle' | 'pending' | 'exchanging' | 'success' | 'failed'
  authorize_url?: string
  app_name?: string
  scope?: string
  error_code?: string
  error_message?: string
  warning?: string
  expires_in?: number
  connected?: boolean
  account_id?: string
}

export interface OrcaStatus {
  providers: Array<{ id: string; label: string; method: string }>
  credentials: CredentialsSummary
  auth_base: string
  api_base: string
  authorize_url: string
  key_dashboard_url: string
  connect: ConnectState
}

export function isOrcaProvider(provider: string | undefined | null): boolean {
  return provider === ORCA_PROVIDER_API || provider === ORCA_PROVIDER_OAUTH
}
