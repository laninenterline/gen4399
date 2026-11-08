import type { RunPayload } from '../api'
import { Card, Field, Input, Select } from './ui'

type Props = {
  value: RunPayload
  identityCount: number
  onChange: (patch: Partial<RunPayload>) => void
}

export default function SettingsPanel({ value, identityCount, onChange }: Props) {
  const planned = Math.min(value.count || identityCount, identityCount)

  return (
    <Card title="2 · 生成设置" aside={<span className="text-xs text-slate-400">将生成 {planned} 个账号</span>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="数量">
          <Input
            type="number"
            min={1}
            value={value.count}
            onChange={(event) => onChange({ count: Number(event.target.value) || 1 })}
          />
        </Field>
        <Field label="通道">
          <Select value={value.path} onChange={(event) => onChange({ path: event.target.value as RunPayload['path'] })}>
            <option value="unified">unified（ptlogin）</option>
            <option value="web">web</option>
          </Select>
        </Field>
        <Field label="用户名前缀">
          <Input value={value.prefix} onChange={(event) => onChange({ prefix: event.target.value.trim() })} />
        </Field>
        <Field label="用户名后缀">
          <Input value={value.suffix} onChange={(event) => onChange({ suffix: event.target.value.trim() })} />
        </Field>
        <Field label="间隔（秒）">
          <Input
            type="number"
            min={0}
            value={value.interval}
            onChange={(event) => onChange({ interval: Number(event.target.value) || 0 })}
          />
        </Field>
        <Field label="随机抖动（秒）">
          <Input
            type="number"
            min={0}
            value={value.jitter}
            onChange={(event) => onChange({ jitter: Number(event.target.value) || 0 })}
          />
        </Field>
        <Field label="验证码">
          <Select
            value={value.captcha}
            onChange={(event) => onChange({ captcha: event.target.value as RunPayload['captcha'] })}
          >
            <option value="matcher">内置模板（unified 60×30）</option>
            <option value="learn">自学习字库（web 150×45）</option>
            <option value="human">浏览器人工识别</option>
            <option value="">不处理</option>
          </Select>
        </Field>
        <Field label="模式">
          <Select
            value={value.dry_run ? 'dry' : 'real'}
            onChange={(event) => onChange({ dry_run: event.target.value === 'dry' })}
          >
            <option value="dry">dry-run（不提交）</option>
            <option value="real">真实提交</option>
          </Select>
        </Field>
      </div>

      <label className="mt-3 flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={value.verify_login}
          onChange={(event) => onChange({ verify_login: event.target.checked })}
          className="size-4 accent-sky-500"
        />
        注册后登录复核
      </label>
    </Card>
  )
}
