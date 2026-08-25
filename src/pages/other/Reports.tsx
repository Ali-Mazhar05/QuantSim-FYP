import { Download, FileBarChart, Printer, Share2, X } from 'lucide-react'
import { useState } from 'react'
import Button from '../../components/forms/Button'
import Modal from '../../components/modals/Modal'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { useNotifications } from '../../demo/notifications'
import { REPORTS } from '../../services/mock/data'
import type { ReportDef } from '../../types'

export default function Reports() {
  const [active, setActive] = useState<ReportDef | null>(null)
  const push = useNotifications((s) => s.push)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Reports" description="Generated reports across simulation, risk and composite analysis." />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {REPORTS.map((r) => (
          <button
            key={r.id}
            onClick={() => setActive(r)}
            className="qs-panel flex flex-col items-start gap-2 rounded p-4 text-left transition-colors hover:border-[var(--color-accent-strong)]"
          >
            <FileBarChart size={18} className="text-[var(--color-accent-strong)]" />
            <div className="text-sm font-semibold text-[var(--color-text-primary)]">{r.name}</div>
            <div className="text-xs text-[var(--color-text-muted)]">{r.description}</div>
          </button>
        ))}
      </div>

      <Modal open={!!active} onClose={() => setActive(null)} title={active?.name ?? ''} width="lg">
        {active && (
          <div>
            <Panel bodyClassName="p-6">
              <div className="mb-4 flex items-center justify-between border-b border-[var(--color-border)] pb-4">
                <div>
                  <div className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">QuantSim · {active.category}</div>
                  <div className="text-lg font-semibold text-[var(--color-text-primary)]">{active.name}</div>
                </div>
                <button onClick={() => setActive(null)} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                  <X size={16} />
                </button>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)]">{active.description}</p>
              <div className="mt-4 grid grid-cols-3 gap-4 text-sm">
                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">Simulation</div>
                  <div className="mono mt-0.5 text-[var(--color-text-primary)]">#1042</div>
                </div>
                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">Portfolio</div>
                  <div className="mt-0.5 text-[var(--color-text-primary)]">Momentum Strategy</div>
                </div>
                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">Generated</div>
                  <div className="mono mt-0.5 text-[var(--color-text-primary)]">2026-08-25 16:22</div>
                </div>
              </div>
            </Panel>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" icon={Printer} onClick={() => push('Sent to printer', 'info')}>
                Print
              </Button>
              <Button variant="secondary" icon={Share2} onClick={() => push('Share link copied', 'success')}>
                Share
              </Button>
              <Button icon={Download} onClick={() => push('Report export queued', 'info')}>
                Export PDF
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
