import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type AccountRecord, type Health, type RunPayload, type TaskStatus } from './api'
import CaptchaModal from './components/CaptchaModal'
import IdentityPanel from './components/IdentityPanel'
import ResultsPanel from './components/ResultsPanel'
import RunPanel from './components/RunPanel'
import SettingsPanel from './components/SettingsPanel'
import { Badge } from './components/ui'

const EMPTY_STATUS: TaskStatus = {
  running: false,
  total: 0,
  finished: 0,
  success: 0,
  failed: 0,
  skipped: 0,
  elapsed: 0,
  error: '',
  items: [],
  logs: [],
}

const DEFAULT_PAYLOAD: RunPayload = {
  sfz: '',
  count: 1,
  prefix: '',
  suffix: '',
  path: 'unified',
  interval: 20,
  jitter: 10,
  captcha: 'matcher',
  dry_run: true,
  verify_login: false,
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [status, setStatus] = useState<TaskStatus>(EMPTY_STATUS)
  const [accounts, setAccounts] = useState<AccountRecord[]>([])
  const [payload, setPayload] = useState<RunPayload>(DEFAULT_PAYLOAD)
  const [parseInfo, setParseInfo] = useState<{ count: number; invalid: number; errors: string[] }>({
    count: 0,
    invalid: 0,
    errors: [],
  })
  const [startError, setStartError] = useState('')
  const [captchaImage, setCaptchaImage] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  const refreshAccounts = useCallback(async () => {
    try {
      const data = await api.accounts()
      setAccounts(data.items)
    } catch {
      /* 忽略：账号文件可能还不存在 */
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.status()
      setStatus(next)
      if (!next.running && pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
        void refreshAccounts()
      }
    } catch {
      /* 后端未启动时静默 */
    }
  }, [refreshAccounts])

  useEffect(() => {
    void (async () => {
      try {
        setHealth(await api.health())
      } catch {
        setHealth(null)
      }
      await refreshStatus()
      await refreshAccounts()
    })()
    const timer = window.setInterval(() => {
      void refreshStatus()
    }, 3000)
    return () => {
      window.clearInterval(timer)
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [refreshAccounts, refreshStatus])

  useEffect(() => {
    if (!status.running) {
      setCaptchaImage(null)
      return
    }
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const caption = await api.captcha()
        if (!cancelled && caption.image) setCaptchaImage(caption.image)
      } catch {
        /* 忽略 */
      }
    }, 1200)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [status.running])

  const patch = useCallback((next: Partial<RunPayload>) => {
    setPayload((prev) => ({ ...prev, ...next }))
  }, [])

  async function handleParse() {
    setParseInfo(await api.parse(payload.sfz))
  }

  async function handleStart() {
    setStartError('')
    if (parseInfo.count === 0) {
      const info = await api.parse(payload.sfz)
      setParseInfo(info)
      if (info.count === 0) {
        setStartError('没有可用身份，先粘贴或导入 sfz.txt')
        return
      }
    }
    if (!payload.dry_run && !window.confirm('将真实提交注册请求，确认继续？')) return
    try {
      await api.run(payload)
      if (pollRef.current === null) {
        pollRef.current = window.setInterval(() => {
          void refreshStatus()
        }, 1000)
      }
      await refreshStatus()
    } catch (error) {
      setStartError(error instanceof Error ? error.message : '启动失败')
    }
  }

  async function handleStop() {
    await api.stop()
    await refreshStatus()
  }

  async function handleCaptchaSubmit(code: string) {
    await api.submitCaptcha(code)
    setCaptchaImage(null)
  }

  const connection = useMemo(() => {
    if (!health) return { tone: 'bad' as const, text: '后端未连接' }
    return { tone: 'ok' as const, text: `后端 v${health.version}` }
  }, [health])

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold tracking-tight">gen4399 WebUI</h1>
        <Badge tone={connection.tone}>{connection.text}</Badge>
        <span className="text-xs text-slate-500">本地服务，仅监听 127.0.0.1</span>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <IdentityPanel
          text={payload.sfz}
          onTextChange={(sfz) => patch({ sfz })}
          count={parseInfo.count}
          invalid={parseInfo.invalid}
          onParse={handleParse}
          errors={parseInfo.errors}
        />
        <SettingsPanel value={payload} identityCount={parseInfo.count} onChange={patch} />
        <div className="lg:col-span-2">
          <RunPanel
            status={status}
            running={status.running}
            onStart={handleStart}
            onStop={handleStop}
            startError={startError}
          />
        </div>
        <div className="lg:col-span-2">
          <ResultsPanel items={status.items} accounts={accounts} onRefresh={refreshAccounts} />
        </div>
      </div>

      {captchaImage && (
        <CaptchaModal
          image={captchaImage}
          onSubmit={handleCaptchaSubmit}
          onDismiss={() => setCaptchaImage(null)}
        />
      )}
    </div>
  )
}
