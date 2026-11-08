import { useEffect, useState } from 'react'
import { Button, Input } from './ui'

type Props = {
  image: string
  onSubmit: (code: string) => void
  onDismiss: () => void
}

export default function CaptchaModal({ image, onSubmit, onDismiss }: Props) {
  const [code, setCode] = useState('')

  useEffect(() => setCode(''), [image])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-700 bg-slate-900 p-4">
        <h3 className="mb-3 text-sm font-semibold">请输入验证码</h3>
        <img
          src={`data:image/png;base64,${image}`}
          alt="captcha"
          className="mb-3 w-full rounded-lg bg-white p-1"
        />
        <Input
          autoFocus
          value={code}
          maxLength={4}
          placeholder="4 位字符"
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && code.trim()) onSubmit(code.trim())
          }}
        />
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" onClick={onDismiss}>
            跳过
          </Button>
          <Button onClick={() => onSubmit(code.trim())} disabled={!code.trim()}>
            提交
          </Button>
        </div>
      </div>
    </div>
  )
}
