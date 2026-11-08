import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

export function Card({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold tracking-[0.14em] text-slate-400 uppercase">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }

export function Button({ variant = 'primary', className = '', ...rest }: ButtonProps) {
  const styles = {
    primary: 'bg-sky-500 text-white hover:bg-sky-400 disabled:bg-slate-700',
    ghost: 'border border-slate-700 bg-transparent text-slate-200 hover:border-slate-500',
    danger: 'bg-rose-600 text-white hover:bg-rose-500',
  }[variant]
  return (
    <button
      {...rest}
      className={`rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${styles} ${className}`}
    />
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] text-slate-500">{hint}</span> : null}
    </label>
  )
}

const controlClass =
  'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = '', ...rest } = props
  return <input {...rest} className={`${controlClass} ${className}`} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = '', ...rest } = props
  return <select {...rest} className={`${controlClass} ${className}`} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className = '', ...rest } = props
  return <textarea {...rest} className={`${controlClass} min-h-[140px] font-mono text-xs ${className}`} />
}

export function Badge({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'ok' | 'bad' | 'warn' }) {
  const styles = {
    default: 'border-slate-700 text-slate-300',
    ok: 'border-emerald-600 text-emerald-400',
    bad: 'border-rose-600 text-rose-400',
    warn: 'border-amber-500 text-amber-400',
  }[tone]
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] ${styles}`}>{children}</span>
}
