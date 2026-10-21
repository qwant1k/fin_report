import { Calculator, CheckCircle2, Database, Info } from 'lucide-react'

import { Modal } from '@/components/ui'

export interface FormulaExplanation {
  title: string
  instrument: string
  formula: string
  substituted: string
  result: string
  inputs: Array<{ label: string; value: string }>
  priceSource?: {
    selected: string
    steps: Array<{ label: string; active: boolean; note?: string }>
  }
  note?: string
}

export default function FormulaExplainer({
  explanation,
  onClose,
}: {
  explanation: FormulaExplanation | null
  onClose: () => void
}) {
  return (
    <Modal
      open={!!explanation}
      onClose={onClose}
      title="Как рассчитано"
      description={explanation ? `${explanation.title} · ${explanation.instrument}` : undefined}
      size="lg"
    >
      {explanation && (
        <div className="space-y-4">
          <section className="rounded-xl border border-indigo-200 bg-indigo-50/70 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-indigo-900">
              <Calculator className="h-4 w-4" /> Формула
            </div>
            <div className="font-mono text-sm text-indigo-950">{explanation.formula}</div>
            <div className="mt-3 rounded-lg bg-white px-3 py-2 font-mono text-sm text-slate-800 shadow-sm">
              {explanation.substituted}
            </div>
            <div className="mt-3 text-base font-bold text-indigo-950">Результат: {explanation.result}</div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-800">Использованные значения</h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {explanation.inputs.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 px-3 py-2 text-sm">
                  <span className="text-slate-500">{item.label}</span>
                  <span className="text-right font-mono font-semibold text-slate-800">{item.value}</span>
                </div>
              ))}
            </div>
          </section>

          {explanation.priceSource && (
            <section className="rounded-xl border border-slate-200 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Database className="h-4 w-4" /> Приоритет источника цены
              </div>
              <div className="space-y-2">
                {explanation.priceSource.steps.map((step, index) => (
                  <div key={step.label} className={`flex items-start gap-3 rounded-lg px-3 py-2 ${step.active ? 'bg-emerald-50 text-emerald-900' : 'bg-slate-50 text-slate-500'}`}>
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${step.active ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
                      {step.active ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
                    </span>
                    <div>
                      <div className="font-semibold">{step.label}</div>
                      {step.note && <div className="text-xs opacity-80">{step.note}</div>}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-xs text-slate-500">Выбран: {explanation.priceSource.selected}</div>
            </section>
          )}

          {explanation.note && (
            <div className="flex gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <Info className="mt-0.5 h-4 w-4 shrink-0" /> {explanation.note}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
