import { useRef } from 'react'
import { Button, Card, Textarea } from './ui'

type Props = {
  text: string
  onTextChange: (value: string) => void
  count: number
  invalid: number
  onParse: () => void
  errors: string[]
}

export default function IdentityPanel({ text, onTextChange, count, invalid, onParse, errors }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File | undefined) {
    if (!file) return
    onTextChange(await file.text())
  }

  return (
    <Card
      title="1 · 身份"
      aside={
        <span className="text-xs text-slate-400">
          {count > 0 ? `已解析 ${count} 条${invalid ? `（${invalid} 条无效）` : ''}` : '未解析'}
        </span>
      }
    >
      <p className="mb-2 text-xs text-slate-500">每行 <code className="rounded bg-slate-800 px-1">姓名|身份证[|QQ]</code></p>
      <Textarea
        value={text}
        placeholder={'张三|110105198803121893\n李四|460206194611192084|123456'}
        onChange={(event) => onTextChange(event.target.value)}
        spellCheck={false}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={onParse}>解析</Button>
        <Button variant="ghost" onClick={() => fileRef.current?.click()}>
          导入 sfz.txt
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.csv,text/plain"
          className="hidden"
          onChange={(event) => handleFile(event.target.files?.[0])}
        />
      </div>
      {errors.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-rose-400">
          {errors.slice(0, 5).map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
    </Card>
  )
}
