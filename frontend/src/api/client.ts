import type {
  SessionPage,
  MessagePage,
  SearchHit,
  ETLStatus,
  LLMConfig,
  LLMChatRequest,
} from './types'

const BASE = ''

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

let _streamAbort: AbortController | null = null

export const apiClient = {
  // 会话
  listSessions(params: { type?: string; keyword?: string; page?: number; size?: number } = {}): Promise<SessionPage> {
    const q = new URLSearchParams()
    if (params.type) q.set('type', params.type)
    if (params.keyword) q.set('keyword', params.keyword)
    if (params.page) q.set('page', String(params.page))
    if (params.size) q.set('size', String(params.size))
    return jsonFetch<SessionPage>(`/api/sessions?${q}`)
  },

  // 消息
  listMessages(params: { session: string; before_ts?: number; after_ts?: number; page?: number; size?: number }): Promise<MessagePage> {
    const q = new URLSearchParams()
    q.set('session', params.session)
    if (params.before_ts) q.set('before_ts', String(params.before_ts))
    if (params.after_ts) q.set('after_ts', String(params.after_ts))
    q.set('page', String(params.page ?? 1))
    q.set('size', String(params.size ?? 30))
    return jsonFetch<MessagePage>(`/api/messages?${q}`)
  },

  // 搜索
  search(params: { q: string; session?: string; limit?: number }): Promise<SearchHit[]> {
    const qs = new URLSearchParams()
    qs.set('q', params.q)
    if (params.session) qs.set('session', params.session)
    qs.set('limit', String(params.limit ?? 50))
    return jsonFetch<SearchHit[]>(`/api/search?${qs}`)
  },

  // Admin
  etlStatus(): Promise<ETLStatus> {
    return jsonFetch<ETLStatus>('/api/admin/status')
  },

  triggerEtl(force = false): Promise<{ mode: string; counts: any }> {
    return jsonFetch<{ mode: string; counts: any }>('/api/admin/etl', {
      method: 'POST',
      body: JSON.stringify({ force }),
    })
  },

  // LLM config
  getLLMConfig(): Promise<LLMConfig> {
    return jsonFetch<LLMConfig>('/api/llm/config')
  },

  setLLMConfig(config: LLMConfig): Promise<{ status: string }> {
    return jsonFetch<{ status: string }>('/api/llm/config', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },

  // 流式 LLM 聊天 - SSE
  async streamLLM(
    req: LLMChatRequest,
    onEvent: (e: { type: 'start' | 'content' | 'end' | 'error'; content?: string; error?: string }) => void
  ): Promise<void> {
    if (_streamAbort) _streamAbort.abort()
    _streamAbort = new AbortController()

    const res = await fetch('/api/llm/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal: _streamAbort.signal,
    })
    if (!res.ok || !res.body) {
      onEvent({ type: 'error', error: `HTTP ${res.status}` })
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() || ''
        for (const chunk of parts) {
          const line = chunk.trim()
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (!data) continue
          try {
            const obj = JSON.parse(data)
            if (obj.type === 'content') onEvent({ type: 'content', content: obj.content })
            else if (obj.type === 'start') onEvent({ type: 'start' })
            else if (obj.type === 'end') onEvent({ type: 'end' })
            else if (obj.type === 'error') onEvent({ type: 'error', error: obj.error })
          } catch {}
        }
      }
      onEvent({ type: 'end' })
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        onEvent({ type: 'error', error: e?.message || String(e) })
      }
    }
  },

  abortStream() {
    if (_streamAbort) {
      _streamAbort.abort()
      _streamAbort = null
    }
  },
}