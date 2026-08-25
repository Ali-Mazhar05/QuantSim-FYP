import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import DataTable, { type Column } from '../../components/tables/DataTable'
import StatusPill from '../../components/status/StatusPill'
import { PORTFOLIO } from '../../services/mock/data'

interface Row {
  id: string
  name: string
  value: number
  returnPct: number
  status: string
}

const columns: Column<Row>[] = [
  { key: 'name', header: 'Portfolio', render: (r) => <span className="font-medium text-[var(--color-text-primary)]">{r.name}</span> },
  { key: 'value', header: 'Value', align: 'right', render: (r) => <span className="mono">${r.value.toLocaleString()}</span> },
  { key: 'return', header: 'Return', align: 'right', render: (r) => <span className="mono text-[var(--color-risk-low)]">+{r.returnPct}%</span> },
  { key: 'status', header: 'Status', render: (r) => <StatusPill tone="success" dot>{r.status}</StatusPill> },
]

export default function Portfolios() {
  const navigate = useNavigate()
  const rows: Row[] = [
    { id: PORTFOLIO.id, name: PORTFOLIO.name, value: PORTFOLIO.currentValue, returnPct: PORTFOLIO.returnPct, status: 'Active' },
    { id: 'pf-0981', name: 'Value Strategy — Run #0981', value: 942_310, returnPct: -1.2, status: 'Closed' },
    { id: 'pf-0850', name: 'Pairs Strategy — Run #0850', value: 1_112_004, returnPct: 4.6, status: 'Closed' },
  ]
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Portfolios"
        description="Portfolios constructed from simulated market environments."
        action={
          <Button icon={Plus} onClick={() => navigate('/trading/portfolios/new')}>
            New Portfolio
          </Button>
        }
      />
      <Panel bodyClassName="p-0">
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={() => navigate('/risk/overview')} />
      </Panel>
    </div>
  )
}
