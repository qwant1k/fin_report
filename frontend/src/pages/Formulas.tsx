import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpenCheck, Calculator, SlidersHorizontal, Sigma } from 'lucide-react'

import { PageHeader, Segmented } from '@/components/ui'
import SystemFormulas from '@/components/formulas/SystemFormulas'
import CalcParameters from '@/components/formulas/CalcParameters'
import IndicatorBuilder from '@/components/formulas/IndicatorBuilder'

type Tab = 'system' | 'params' | 'custom'

const SUBTITLE: Record<Tab, string> = {
  system: 'Как система считает стоимость, НКД, дюрацию, доли и лимиты — простыми словами и с примером на ваших данных',
  params: 'Настройки расчёта, которые можно менять: коридор дюрации, приоритет цен, базы дней, допуски сверки',
  custom: 'Свои показатели из полей сводки — без программиста: перетащите поля, проверьте на данных, выведите в «Сводку»',
}

export default function FormulasPage() {
  const [search, setSearch] = useSearchParams()
  const initial = (search.get('tab') as Tab) || 'system'
  const [tab, setTab] = useState<Tab>(['system', 'params', 'custom'].includes(initial) ? initial : 'system')
  const [focusParam, setFocusParam] = useState<string | null>(null)

  const go = (t: Tab) => {
    setTab(t)
    const next = new URLSearchParams(search)
    next.set('tab', t)
    setSearch(next, { replace: true })
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Формулы"
        subtitle={SUBTITLE[tab]}
        icon={Calculator}
        actions={(
          <Segmented<Tab>
            layoutId="formulas-tab"
            value={tab}
            onChange={go}
            options={[
              { value: 'system', label: 'Как считается', icon: BookOpenCheck },
              { value: 'params', label: 'Параметры расчёта', icon: SlidersHorizontal },
              { value: 'custom', label: 'Мои показатели', icon: Sigma },
            ]}
          />
        )}
      />
      {tab === 'system' && <SystemFormulas onParam={(code) => { setFocusParam(code); go('params') }} />}
      {tab === 'params' && <CalcParameters focus={focusParam} />}
      {tab === 'custom' && <IndicatorBuilder />}
    </div>
  )
}
