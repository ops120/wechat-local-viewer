import { describe, expect, it, vi } from 'vitest'
import { createOrcaConnectController, errorText } from '../connectController'

interface Call {
  path: string
  body: unknown
  keepalive?: boolean
}

function harness(handlers: Record<string, (body: unknown) => unknown> = {}) {
  const calls: Call[] = []
  const post = vi.fn(async (path: string, body?: unknown, options?: { keepalive?: boolean }) => {
    calls.push({ path, body, keepalive: options?.keepalive })
    const handler = handlers[path]
    if (handler) return handler(body) as never
    return {} as never
  })
  const controller = createOrcaConnectController({ post })
  return { controller, calls, post }
}

const START_URL =
  'https://www.orcarouter.ai/auth?callback_url=oob&code_challenge=abc&code_challenge_method=S256&state=xyz'

describe('startLogin', () => {
  it('delivers the authorize URL and marks the panel busy', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => ({
        attempt: 1,
        status: 'pending',
        authorize_url: START_URL,
        scope: 'api',
      }),
    })

    const payload = await controller.startLogin()
    const state = controller.getState()

    expect(payload?.authorize_url).toBe(START_URL)
    expect(state.hint).toBe(START_URL)
    expect(state.busy).toBe(true)
    expect(state.attempt).toBe(1)
    // The authorize URL is on the auth origin, not the inference origin.
    expect(state.hint).toContain('www.orcarouter.ai/auth')
    expect(state.hint).not.toContain('api.orcarouter.ai')
  })

  it('clears busy state when the request fails', async () => {
    const post = vi.fn(async () => {
      throw new Error('backend down')
    })
    const controller = createOrcaConnectController({ post })

    const payload = await controller.startLogin()
    const state = controller.getState()

    expect(payload).toBeNull()
    expect(state.busy).toBe(false)
    expect(state.errorMessage).toContain('backend down')
  })
})

describe('exchange', () => {
  it('clears busy state and the hint on success', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 3, status: 'pending', authorize_url: START_URL }),
      '/api/orcarouter/connect/exchange': () => ({
        status: 'ok',
        credential: { account_id: '42', scope: 'api', secret_masked: 'sk-orca-…abcd' },
      }),
    })

    await controller.startLogin()
    const ok = await controller.exchange('the-code')
    const state = controller.getState()

    expect(ok).toBe(true)
    expect(state.busy).toBe(false)
    expect(state.status.status).toBe('success')
    expect(state.status.connected).toBe(true)
    expect(state.errorMessage).toBe('')
  })

  it('surfaces a denial as an actionable message and releases the lock', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 1, status: 'pending', authorize_url: START_URL }),
      '/api/orcarouter/connect/exchange': () => {
        const error = new Error('授权码无效 (403)：已过期或已被使用') as Error & { detail: unknown }
        error.detail = { code: 'code_rejected', message: '授权码无效 (403)：已过期或已被使用' }
        throw error
      },
    })

    await controller.startLogin()
    const ok = await controller.exchange('bad-code')
    const state = controller.getState()

    expect(ok).toBe(false)
    expect(state.busy).toBe(false)
    expect(state.errorMessage).toContain('授权码无效')
    expect(state.status.status).toBe('failed')
  })

  it('never puts the code or a key into the error message', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 1, status: 'pending', authorize_url: START_URL }),
      '/api/orcarouter/connect/exchange': () => {
        throw new Error('授权码交换失败')
      },
    })
    await controller.startLogin()
    await controller.exchange('super-secret-code')
    expect(controller.getState().errorMessage).not.toContain('super-secret-code')
  })
})

describe('cancellation paths', () => {
  it('an explicit cancel releases the lock and clears the hint', async () => {
    const { controller, calls } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 2, status: 'pending', authorize_url: START_URL }),
    })

    await controller.startLogin()
    await controller.cancel()
    const state = controller.getState()

    expect(state.busy).toBe(false)
    expect(state.hint).toBe('')
    expect(state.status.status).toBe('idle')
    expect(calls.map((c) => c.path)).toContain('/api/orcarouter/connect/cancel')
  })

  it('a cancel that the backend rejects still frees the local UI', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 1, status: 'pending', authorize_url: START_URL }),
    })
    await controller.startLogin()
    vi.spyOn(globalThis, 'fetch')
    await controller.cancel()
    expect(controller.getState().busy).toBe(false)
  })

  it('switching authentication method cancels the in-flight attempt', async () => {
    const { controller, calls } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 1, status: 'pending', authorize_url: START_URL }),
    })
    await controller.startLogin()
    await controller.cancel()
    expect(calls.filter((c) => c.path === '/api/orcarouter/connect/cancel')).toHaveLength(1)
  })
})

describe('pagehide (back-forward cache)', () => {
  it('clears busy and hint synchronously and sends a keepalive cancel', async () => {
    const { controller, calls } = harness({
      '/api/orcarouter/connect/start': () => ({ attempt: 5, status: 'pending', authorize_url: START_URL }),
    })

    await controller.startLogin()
    expect(controller.getState().busy).toBe(true)

    controller.handlePageHide()

    // Synchronous: the restored page must never be left permanently busy.
    const state = controller.getState()
    expect(state.busy).toBe(false)
    expect(state.hint).toBe('')
    expect(state.errorMessage).toBe('')

    const cancel = calls.find((c) => c.path === '/api/orcarouter/connect/cancel')
    expect(cancel).toBeDefined()
    expect(cancel?.keepalive).toBe(true)
  })

  it('lets a second login start without remounting the component', async () => {
    let attempt = 0
    const { controller } = harness({
      '/api/orcarouter/connect/start': () => {
        attempt += 1
        return { attempt, status: 'pending', authorize_url: `${START_URL}&n=${attempt}` }
      },
    })

    await controller.startLogin()
    controller.handlePageHide()

    // No remount: the same controller instance must accept a new attempt.
    const second = await controller.startLogin()
    expect(second?.attempt).toBe(2)
    expect(controller.getState().busy).toBe(true)
    expect(controller.getState().hint).toContain('n=2')
  })

  it('a late response from the invalidated attempt cannot overwrite state', async () => {
    let resolveStart: ((value: unknown) => void) | undefined
    const post = vi.fn((path: string) => {
      if (path === '/api/orcarouter/connect/start') {
        return new Promise((resolve) => {
          resolveStart = resolve
        }) as never
      }
      return Promise.resolve({} as never)
    })
    const controller = createOrcaConnectController({ post })

    const pending = controller.startLogin()
    controller.handlePageHide() // invalidate while the request is in flight

    resolveStart?.({ attempt: 1, status: 'pending', authorize_url: START_URL })
    await pending

    // The stale success must not resurrect the busy state.
    expect(controller.getState().busy).toBe(false)
    expect(controller.getState().hint).toBe('')
  })

  it('a stale exchange cannot mark a fresh login as connected', async () => {
    let resolveExchange: ((value: unknown) => void) | undefined
    const post = vi.fn((path: string) => {
      if (path === '/api/orcarouter/connect/start') {
        return Promise.resolve({ attempt: 1, status: 'pending', authorize_url: START_URL } as never)
      }
      if (path === '/api/orcarouter/connect/exchange') {
        return new Promise((resolve) => {
          resolveExchange = resolve
        }) as never
      }
      return Promise.resolve({} as never)
    })
    const controller = createOrcaConnectController({ post })

    await controller.startLogin()
    const inflight = controller.exchange('code')
    await controller.cancel() // user switched method / closed the modal

    resolveExchange?.({
      status: 'ok',
      credential: { account_id: '9', scope: 'api', secret_masked: 'sk-orca-…zzzz' },
    })
    expect(await inflight).toBe(false)
    expect(controller.getState().status.status).toBe('idle')
    expect(controller.getState().busy).toBe(false)
  })
})

describe('status refresh', () => {
  it('picks up a server-side failure without wedging the panel', async () => {
    const { controller } = harness({
      '/api/orcarouter/connect/status': () => ({
        attempt: 1,
        status: 'failed',
        error_code: 'timeout',
        error_message: '授权超时',
      }),
    })
    await controller.refreshStatus()
    expect(controller.getState().errorMessage).toBe('授权超时')
    expect(controller.getState().busy).toBe(false)
  })
})

describe('errorText', () => {
  it('unwraps a FastAPI detail object', () => {
    expect(errorText({ detail: { code: 'x', message: '具体原因' } })).toBe('具体原因')
    expect(errorText({ detail: 'plain' })).toBe('plain')
    expect(errorText(new Error('boom'))).toBe('boom')
    expect(errorText(undefined)).toBe('undefined')
  })
})
