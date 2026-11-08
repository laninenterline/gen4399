// 后端 JSON API 的类型化客户端（后端是 gen4399/webui.py）

export type TaskItem = {
  index: number
  username: string
  kind: string
  ok: boolean
  message: string
}

export type TaskStatus = {
  running: boolean
  total: number
  finished: number
  success: number
  failed: number
  skipped: number
  elapsed: number
  error: string
  items: TaskItem[]
  logs: string[]
}

export type Health = { ok: boolean; version: string; running: boolean }

export type RunPayload = {
  sfz: string
  count: number
  prefix: string
  suffix: string
  path: 'unified' | 'web'
  interval: number
  jitter: number
  captcha: '' | 'matcher' | 'learn' | 'human'
  dry_run: boolean
  verify_login: boolean
}

export type AccountRecord = {
  created_at?: string
  username?: string
  password?: string
  kind?: string
  ok?: boolean
  message?: string
  path?: string
  idcard_masked?: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body?.error) detail = body.error
    } catch {
      /* 后端不一定返回 JSON */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  status: () => request<TaskStatus>('/api/status'),
  accounts: () => request<{ items: AccountRecord[] }>('/api/accounts'),
  parse: (sfz: string) =>
    request<{ count: number; invalid: number; errors: string[] }>('/api/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sfz }),
    }),
  run: (payload: RunPayload) =>
    request<{ ok: boolean; error?: string }>('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  stop: () => request<{ ok: boolean }>('/api/stop', { method: 'POST', body: '{}' }),
  captcha: () => request<{ image?: string }>('/api/captcha'),
  submitCaptcha: (code: string) =>
    request<{ ok: boolean }>('/api/captcha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    }),
}

export const exportUrl = (format: 'csv' | 'json') => `/api/export?format=${format}`
