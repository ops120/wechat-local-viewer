/**
 * OrcaRouter API client. Talks only to this project's own `/api/orcarouter/*`
 * endpoints — the API key never reaches the browser, so these responses carry
 * masked secrets and model metadata only.
 */

import type { ConnectState, CredentialsSummary, ModelOption, ModelOptionsPayload, OrcaStatus } from './provider'

async function request<T>(
  path: string,
  init?: RequestInit & { keepalive?: boolean },
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    keepalive: init?.keepalive,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail: unknown = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body?.detail ?? detail
    } catch {
      /* non-JSON error body: keep the status line */
    }
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    ;(error as { detail?: unknown }).detail = detail
    throw error
  }
  return (await res.json()) as T
}

function post<T>(path: string, body?: unknown, options?: { keepalive?: boolean }): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
    keepalive: options?.keepalive,
  })
}

export const orcaApi = {
  status(): Promise<OrcaStatus> {
    return request<OrcaStatus>('/api/orcarouter/status')
  },

  saveApiKey(apiKey: string): Promise<{ status: string; credentials: CredentialsSummary }> {
    return post('/api/orcarouter/credentials', { api_key: apiKey })
  },

  clearCredential(method: 'api_key' | 'pkce'): Promise<{ status: string; credentials: CredentialsSummary }> {
    return request(`/api/orcarouter/credentials/${method}`, { method: 'DELETE' })
  },

  setActiveMethod(method: 'api_key' | 'pkce'): Promise<{ status: string; credentials: CredentialsSummary }> {
    return post('/api/orcarouter/credentials/active', { method })
  },

  models(capability: string, modality?: string | null): Promise<ModelOptionsPayload> {
    const q = new URLSearchParams({ capability })
    if (modality) q.set('modality', modality)
    return request<ModelOptionsPayload>(`/api/orcarouter/models?${q}`)
  },

  refreshModels(capability: string, modality?: string | null): Promise<ModelOptionsPayload> {
    const q = new URLSearchParams({ capability })
    if (modality) q.set('modality', modality)
    return post<ModelOptionsPayload>(`/api/orcarouter/models/refresh?${q}`)
  },

  connectStart: () => post<ConnectState>('/api/orcarouter/connect/start', {}),
  connectStatus: () => request<ConnectState>('/api/orcarouter/connect/status'),
  connectExchange: (code: string, attempt?: number, state?: string) =>
    post<{ status: string; credential: { account_id: string; scope: string; secret_masked: string } }>(
      '/api/orcarouter/connect/exchange',
      { code, attempt, state },
    ),
  connectCancel: (keepalive = false) => post('/api/orcarouter/connect/cancel', {}, { keepalive }),
}

export type { ModelOption, ModelOptionsPayload }
