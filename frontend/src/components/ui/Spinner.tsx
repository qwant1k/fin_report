import { Loader2 } from 'lucide-react'

import { cn } from '@/lib/cn'

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-4 w-4 animate-spin', className)} />
}

/** Centered loading block with optional label. */
export function LoadingBlock({ label = 'Загрузка…', className }: { label?: string; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-3 p-10 text-slate-500', className)}>
      <Spinner className="h-6 w-6 text-emerald-600" />
      <span className="text-sm font-medium">{label}</span>
    </div>
  )
}
