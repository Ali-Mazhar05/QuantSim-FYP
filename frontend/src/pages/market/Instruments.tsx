import clsx from 'clsx'
import { useEffect, useState } from 'react'
import DataTable, { type Column } from '../../components/tables/DataTable'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import EmptyState from '../../components/status/EmptyState'
import { type MarketInstrument, listInstruments } from '../../services/api/market'
import { errorMessage } from '../auth/authShared'

// An instrument with fewer than two clean bars has no price or change yet and is shown without them
const columns: Column<MarketInstrument>[] = [
  { key: 'symbol', header: 'Symbol', render: (r) => <span className="mono font-semibold text-[var(--color-text-primary)]">{r.symbol}</span> },
  { key: 'name', header: 'Name', render: (r) => r.name },
  { key: 'sector', header: 'Sector', render: (r) => r.sector },
  {
    key: 'price',
    header: 'Price',
    align: 'right',
    render: (r) => <span className="mono">{r.price === null ? '—' : `$${Number(r.price).toFixed(2)}`}</span>,
  },
  {
    key: 'change',
    header: 'Chg %',
    align: 'right',
    render: (r) => {
      if (r.changePct === null) return <span className="mono text-[var(--color-text-muted)]">—</span>
      const change = Number(r.changePct)
      return (
        <span className={clsx('mono', change >= 0 ? 'text-[var(--color-risk-low)]' : 'text-[var(--color-risk-severe)]')}>
          {change >= 0 ? '+' : ''}
          {change.toFixed(2)}%
        </span>
      )
    },
  },
]

export default function Instruments() {
  const [rows, setRows] = useState<MarketInstrument[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listInstruments('active')
      .then((instruments) => !cancelled && setRows(instruments))
      .catch((failure: unknown) => !cancelled && setError(errorMessage(failure)))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Instruments" description="Reference universe of tradable instruments available across market environments." />
      {error ? (
        <p role="alert" className="text-sm text-[var(--color-risk-severe)]">
          {error}
        </p>
      ) : rows === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading instruments…</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No instruments yet" description="An administrator adds instruments through the market API." />
      ) : (
        <Panel bodyClassName="p-0">
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
        </Panel>
      )}
    </div>
  )
}
