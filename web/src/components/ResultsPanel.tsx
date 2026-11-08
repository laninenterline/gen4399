import { exportUrl, type AccountRecord, type TaskItem } from '../api'
import { Badge, Button, Card } from './ui'

type Props = {
  items: TaskItem[]
  accounts: AccountRecord[]
  onRefresh: () => void
}

export default function ResultsPanel({ items, accounts, onRefresh }: Props) {
  const rows = items.length > 0 ? items : accounts.map((account, index) => ({
    index: index + 1,
    username: account.username ?? '',
    kind: account.kind ?? '',
    ok: Boolean(account.ok),
    message: account.created_at ?? '',
  }))

  return (
    <Card
      title="4 · 结果"
      aside={
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => window.open(exportUrl('csv'), '_blank')}>
            导出 CSV
          </Button>
          <Button variant="ghost" onClick={() => window.open(exportUrl('json'), '_blank')}>
            导出 JSON
          </Button>
          <Button variant="ghost" onClick={onRefresh}>
            刷新
          </Button>
        </div>
      }
    >
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">还没有记录</p>
      ) : (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-900 text-slate-400">
              <tr>
                <th className="py-1.5 pr-2 font-medium">#</th>
                <th className="py-1.5 pr-2 font-medium">账号</th>
                <th className="py-1.5 pr-2 font-medium">结果</th>
                <th className="py-1.5 font-medium">说明</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(-200).map((row) => (
                <tr key={`${row.index}-${row.username}`} className="border-t border-slate-800">
                  <td className="py-1.5 pr-2 text-slate-500">{row.index}</td>
                  <td className="py-1.5 pr-2 font-mono">{row.username}</td>
                  <td className="py-1.5 pr-2">
                    <Badge tone={row.ok ? 'ok' : 'bad'}>{row.kind}</Badge>
                  </td>
                  <td className="py-1.5 text-slate-400">{row.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
