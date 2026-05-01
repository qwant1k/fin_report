import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, Plus, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { FormulaDefinition } from '@/lib/types'
import { formatDate } from '@/lib/format'

type Node =
  | { var: string }
  | { const: number }
  | { op: 'ADD' | 'SUB' | 'MUL' | 'DIV'; args: Node[] }
  | { op: 'WEIGHTED_AVG'; field: string; weight: string }

const VARS = [
  'nominal_volume', 'price', 'accrued_interest', 'repo_buyback_sum',
  'repo_open_sum', 'repo_term_days', 'yield_pct', 'market_value_current',
]
const OPS: Array<'ADD' | 'SUB' | 'MUL' | 'DIV'> = ['ADD', 'SUB', 'MUL', 'DIV']

export default function FormulasPage() {
  const qc = useQueryClient()
  const formulas = useQuery<FormulaDefinition[]>({
    queryKey: ['formulas'],
    queryFn: async () => (await api.get('/settings/formulas')).data,
  })

  const upsert = useMutation({
    mutationFn: async (f: any) => (await api.post('/settings/formulas', f)).data,
    onSuccess: () => {
      toast.success('Формула сохранена')
      qc.invalidateQueries({ queryKey: ['formulas'] })
    },
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/settings/formulas/${id}`)).data,
    onSuccess: () => {
      toast.success('Удалена')
      qc.invalidateQueries({ queryKey: ['formulas'] })
    },
  })

  const [editing, setEditing] = useState<FormulaDefinition | null>(null)
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [target, setTarget] = useState('CMV')
  const [tree, setTree] = useState<Node>({ var: 'nominal_volume' })

  const startEdit = (f: FormulaDefinition) => {
    setEditing(f)
    setCode(f.code)
    setName(f.name)
    setTarget(f.target)
    try { setTree(JSON.parse(f.expression_json)) } catch { setTree({ var: 'nominal_volume' }) }
  }

  const startNew = () => {
    setEditing(null)
    setCode('')
    setName('')
    setTarget('CMV')
    setTree({ var: 'nominal_volume' })
  }

  const save = () => {
    upsert.mutate({
      code, name, description: '', target, expression_json: JSON.stringify(tree), is_active: true,
    })
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">Формулы расчёта</h1>
          <p className="text-sm text-slate-500">Drag-and-drop конструктор формул для CMV/YTM/Duration</p>
        </div>
        <button onClick={startNew} className="btn-primary"><Plus className="w-4 h-4" /> Новая формула</button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 card overflow-hidden">
          <div className="p-3 border-b font-semibold">Список</div>
          <div className="divide-y divide-slate-100">
            {(formulas.data ?? []).map((f) => (
              <div key={f.id} className="p-3 flex items-center justify-between cursor-pointer hover:bg-slate-50" onClick={() => startEdit(f)}>
                <div>
                  <div className="font-mono text-sm">{f.code}</div>
                  <div className="text-xs text-slate-500">{f.name} · {f.target} · v{f.version}</div>
                  <div className="text-[10px] text-slate-400">{formatDate(f.updated_at)}</div>
                </div>
                <button onClick={(e) => { e.stopPropagation(); remove.mutate(f.id) }} className="text-red-500 hover:text-red-700">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-3">
          <div className="card p-4 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="label">Код</label>
                <input className="input font-mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="MY_FORMULA" />
              </div>
              <div>
                <label className="label">Название</label>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <label className="label">Target</label>
                <select className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="CMV">CMV</option>
                  <option value="YTM">YTM</option>
                  <option value="DURATION">DURATION</option>
                  <option value="PCT">PCT</option>
                </select>
              </div>
            </div>
            <button onClick={save} disabled={!code || !name} className="btn-primary">
              <Save className="w-4 h-4" /> Сохранить
            </button>
          </div>

          <div className="card p-4 space-y-3">
            <h3 className="font-semibold">Выражение</h3>
            <NodeEditor node={tree} onChange={setTree} />
            <div>
              <details>
                <summary className="text-xs text-slate-500 cursor-pointer">JSON</summary>
                <pre className="bg-slate-50 rounded p-3 text-xs whitespace-pre-wrap mt-2">{JSON.stringify(tree, null, 2)}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function NodeEditor({ node, onChange }: { node: Node; onChange: (n: Node) => void }) {
  if ('var' in node) {
    return (
      <div className="flex gap-2 items-center bg-blue-50 border border-blue-200 rounded p-2">
        <span className="text-xs uppercase text-blue-700">var</span>
        <select className="input py-1" value={node.var} onChange={(e) => onChange({ var: e.target.value })}>
          {VARS.map((v) => <option key={v}>{v}</option>)}
        </select>
        <NodeMenu onChange={onChange} />
      </div>
    )
  }
  if ('const' in node) {
    return (
      <div className="flex gap-2 items-center bg-amber-50 border border-amber-200 rounded p-2">
        <span className="text-xs uppercase text-amber-700">const</span>
        <input
          className="input py-1 w-32"
          type="number"
          value={node.const}
          onChange={(e) => onChange({ const: Number(e.target.value) })}
        />
        <NodeMenu onChange={onChange} />
      </div>
    )
  }
  if (node.op === 'WEIGHTED_AVG') {
    return (
      <div className="bg-purple-50 border border-purple-200 rounded p-2 space-y-2">
        <div className="text-xs uppercase text-purple-700">weighted_avg</div>
        <div className="flex gap-2">
          <span className="text-xs">field:</span>
          <select className="input py-1" value={node.field} onChange={(e) => onChange({ ...node, field: e.target.value })}>
            {VARS.map((v) => <option key={v}>{v}</option>)}
          </select>
        </div>
        <div className="flex gap-2">
          <span className="text-xs">weight:</span>
          <select className="input py-1" value={node.weight} onChange={(e) => onChange({ ...node, weight: e.target.value })}>
            {VARS.map((v) => <option key={v}>{v}</option>)}
          </select>
        </div>
        <NodeMenu onChange={onChange} />
      </div>
    )
  }
  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded p-2 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs uppercase text-emerald-700">op</span>
        <select className="input py-1" value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value as any })}>
          {OPS.map((o) => <option key={o}>{o}</option>)}
        </select>
        <button onClick={() => onChange({ ...node, args: [...node.args, { var: 'price' }] })} className="btn-secondary text-xs">+ arg</button>
        <NodeMenu onChange={onChange} />
      </div>
      <div className="space-y-2 ml-4 border-l-2 border-emerald-300 pl-3">
        {node.args.map((a, i) => (
          <div key={i} className="flex items-start gap-2">
            <NodeEditor
              node={a}
              onChange={(nn) => {
                const args = [...node.args]
                args[i] = nn
                onChange({ ...node, args })
              }}
            />
            <button
              onClick={() => onChange({ ...node, args: node.args.filter((_, j) => j !== i) })}
              className="text-red-500 hover:text-red-700"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function NodeMenu({ onChange }: { onChange: (n: Node) => void }) {
  return (
    <select className="input py-1 ml-auto text-xs" defaultValue="" onChange={(e) => {
      const v = e.target.value
      if (!v) return
      if (v === 'var') onChange({ var: 'price' })
      else if (v === 'const') onChange({ const: 0 })
      else if (v === 'weighted') onChange({ op: 'WEIGHTED_AVG', field: 'ytm', weight: 'market_value_current' })
      else onChange({ op: v as any, args: [{ var: 'price' }, { var: 'nominal_volume' }] })
    }}>
      <option value="">сменить тип…</option>
      <option value="var">var</option>
      <option value="const">const</option>
      <option value="ADD">+</option>
      <option value="SUB">−</option>
      <option value="MUL">×</option>
      <option value="DIV">÷</option>
      <option value="weighted">WEIGHTED_AVG</option>
    </select>
  )
}
