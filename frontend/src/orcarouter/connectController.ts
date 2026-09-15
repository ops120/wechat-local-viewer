/**
 * OrcaRouter login state machine, framework-free so it can be tested directly.
 *
 * The host keeps a single server-side "authorization in progress" slot, so
 * every terminal path must release it: success, denial, exchange error,
 * timeout, an explicit cancel, switching authentication method, closing the
 * modal, and page hide. A monotonic generation id guards every async
 * continuation, so a late response from an abandoned attempt can never
 * overwrite a newer one.
 *
 * `pagehide` is special-cased: browsers may restore the page from the
 * back-forward cache without remounting the component, so the guard that
 * suppresses the stale `finally` would leave the restored page stuck busy
 * forever. The pagehide handler therefore clears busy/hint *synchronously* and
 * sends the server cancellation with keepalive, rather than relying on the
 * invalidated request's own cleanup.
 */

import type { ConnectState } from './provider'

export interface OrcaConnectDeps {
  /** POST helper. Rejects on a non-2xx response. */
  post<T>(path: string, body?: unknown, options?: { keepalive?: boolean }): Promise<T>
  /** Called whenever observable state changes. */
  onChange?: (state: OrcaConnectControllerState) => void
}

export interface OrcaConnectControllerState {
  generation: number
  attempt: number
  busy: boolean
  hint: string
  status: ConnectState
  errorMessage: string
  warning: string
}

export interface OrcaConnectController {
  getState(): OrcaConnectControllerState
  startLogin(): Promise<ConnectState | null>
  deliverAuthorizeUrl(url: string): void
  exchange(code: string, state?: string): Promise<boolean>
  refreshStatus(): Promise<void>
  cancel(): Promise<void>
  handlePageHide(): void
  /** Marks the login complete from outside (e.g. a status poll saw success). */
  settle(connected: boolean): void
}

export function createOrcaConnectController(deps: OrcaConnectDeps): OrcaConnectController {
  let generation = 0
  let attempt = 0
  let busy = false
  let hint = ''
  let status: ConnectState = { attempt: 0, status: 'idle' }
  let errorMessage = ''
  let warning = ''

  function snapshot(): OrcaConnectControllerState {
    return { generation, attempt, busy, hint, status, errorMessage, warning }
  }

  function notify(): void {
    deps.onChange?.(snapshot())
  }

  function clearUiState(): void {
    busy = false
    hint = ''
  }

  function reset(message: string, code = ''): void {
    status = { attempt, status: 'failed', error_code: code, error_message: message }
    errorMessage = message
    clearUiState()
  }

  return {
    getState: snapshot,

    async startLogin(): Promise<ConnectState | null> {
      generation += 1
      const mine = generation
      busy = true
      errorMessage = ''
      warning = ''
      notify()

      let payload: ConnectState
      try {
        payload = await deps.post<ConnectState>('/api/orcarouter/connect/start', {})
      } catch (err) {
        if (mine !== generation) return null
        reset(errorText(err), 'start_failed')
        notify()
        return null
      }
      if (mine !== generation) return null

      attempt = Number(payload?.attempt ?? 0)
      status = payload
      hint = payload?.authorize_url ?? ''
      busy = true
      notify()
      return payload
    },

    deliverAuthorizeUrl(url: string): void {
      hint = url
      notify()
    },

    async exchange(code: string, state?: string): Promise<boolean> {
      generation += 1
      const mine = generation
      busy = true
      errorMessage = ''
      notify()

      try {
        const payload = await deps.post<{
          status: string
          credential: { account_id: string; scope: string; secret_masked: string }
        }>('/api/orcarouter/connect/exchange', { code, attempt, state })
        if (mine !== generation) return false
        status = {
          attempt,
          status: 'success',
          connected: true,
          account_id: payload?.credential?.account_id ?? '',
          scope: payload?.credential?.scope ?? '',
        }
        clearUiState()
        notify()
        return true
      } catch (err) {
        if (mine !== generation) return false
        reset(errorText(err), 'exchange_failed')
        notify()
        return false
      }
    },

    async refreshStatus(): Promise<void> {
      const mine = generation
      try {
        const payload = await deps.post<ConnectState>('/api/orcarouter/connect/status', {})
        if (mine !== generation) return
        status = payload
        if (payload?.status === 'failed' && payload?.error_message) {
          errorMessage = payload.error_message
          clearUiState()
        }
        if (payload?.warning) warning = payload.warning
        notify()
      } catch {
        /* status polling is best-effort; never surfaces as a login failure */
      }
    },

    async cancel(): Promise<void> {
      generation += 1
      attempt = 0
      status = { attempt: 0, status: 'idle' }
      clearUiState()
      notify()
      try {
        await deps.post('/api/orcarouter/connect/cancel', {})
      } catch {
        /* the local lock is already released; a failed cancel is not fatal */
      }
    },

    handlePageHide(): void {
      // Invalidate the generation and clear UI state synchronously: the guarded
      // `finally` of the in-flight request will refuse to touch state, and the
      // restored page must not stay busy.
      generation += 1
      attempt = 0
      status = { attempt: 0, status: 'idle' }
      clearUiState()
      errorMessage = ''
      warning = ''
      notify()
      // Then tell the server, with keepalive so the request survives the unload.
      void deps
        .post('/api/orcarouter/connect/cancel', {}, { keepalive: true })
        .catch(() => undefined)
    },

    settle(connected: boolean): void {
      generation += 1
      attempt = 0
      status = { attempt: 0, status: connected ? 'success' : 'idle', connected }
      clearUiState()
      notify()
    },
  }
}

export function errorText(err: unknown): string {
  if (err && typeof err === 'object') {
    const detail = (err as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string') return message
    }
    const message = (err as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return String(err)
}
