import type { TaskStatus } from '../api'
import { Badge, Button, Card } from './ui'

type Props = {
  status: TaskStatus
  running: boolean
  onStart: () => void
  onStop: () => void
  startError: string
}

export default function RunPanel({ status, running, onStart, onStop, startError }: Props) {
  const percent = status.total > 0 ? Math.round((status.finished / status.total) * 100) : 0

  return (
    <Card
      title="3 · 运行"
      aside={
        <div className="flex items-center gap-2">
          <Badge tone={running ? 'warn' : status.error ? 'bad' : 'ok'}>
            {running ? '运行中' : status.error ? '出错' : '空闲'}
          </Badge>
          <Button onClick={onStart} disabled={running}>
            开始
          </Button>
          <Button variant="danger" onClick={onStop} disabled={!running}>
            停止
          </Button>
        </div>
      }
    >
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div className="h-full bg-emerald-500 transition-all" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        总数 {status.total} · 完成 {status.finished} · 成功 {status.success} · 失败 {status.failed} · 跳过{' '}
        {status.skipped} · {status.elapsed}s
      </p>
      {startError && <p className="mt-2 text-xs text-rose-400">{startError}</p>}
      {status.error && <p className="mt-2 text-xs text-rose-400">{status.error}</p>}
      <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-400">
        {status.logs.length ? status.logs.join('\n') : '（日志会显示在这里）'}
      </pre>
    </Card>
  )
}
