import clsx from 'clsx'
import { Radar } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { NAV_SECTIONS } from './navConfig'

export default function Sidebar() {
  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-1)]">
      <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-4">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]">
          <Radar size={16} />
        </div>
        <div>
          <div className="text-sm font-semibold tracking-tight text-[var(--color-text-primary)]">QuantSim</div>
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">Risk Analytics</div>
        </div>
      </div>
      <nav className="qs-scrollbar-thin flex-1 overflow-y-auto px-2 py-3">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="mb-4">
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              {section.title}
            </div>
            <div className="flex flex-col gap-0.5">
              {section.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-2.5 rounded px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                      isActive
                        ? 'bg-[var(--color-accent)]/12 text-[var(--color-accent-strong)]'
                        : 'text-[var(--color-text-secondary)] hover:bg-white/[0.04] hover:text-[var(--color-text-primary)]',
                    )
                  }
                >
                  <item.icon size={15} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t border-[var(--color-border)] px-4 py-3">
        <span className="inline-flex items-center gap-1.5 rounded border border-[var(--color-border-strong)] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-strong)]" />
          Demo Mode
        </span>
      </div>
    </aside>
  )
}
