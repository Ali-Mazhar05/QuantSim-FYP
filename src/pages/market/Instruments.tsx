import clsx from 'clsx'
import DataTable, { type Column } from '../../components/tables/DataTable'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { INSTRUMENTS } from '../../services/mock/data'
import type { Instrument } from '../../types'

const columns: Column<Instrument>[] = [
  { key: 'symbol', header: 'Symbol', render: (r) => <span className="mono font-semibold text-[var(--color-text-primary)]">{r.symbol}</span> },
  { key: 'name', header: 'Name', render: (r) => r.name },
  { key: 'sector', header: 'Sector', render: (r) => r.sector },
  { key: 'price', header: 'Price', align: 'right', render: (r) => <span className="mono">${r.price.toFixed(2)}</span> },
  {
    key: 'change',
    header: 'Chg %',
    align: 'right',
    render: (r) => (
      <span className={clsx('mono', r.changePct >= 0 ? 'text-[var(--color-risk-low)]' : 'text-[var(--color-risk-severe)]')}>
        {r.changePct >= 0 ? '+' : ''}
        {r.changePct.toFixed(2)}%
      </span>
    ),
  },
]

export default function Instruments() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Instruments" description="Reference universe of tradable instruments available across market environments." />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={INSTRUMENTS} rowKey={(r) => r.symbol} />
      </Panel>
    </div>
  )
}
