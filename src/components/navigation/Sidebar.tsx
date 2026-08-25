import clsx from 'clsx'
import { ChevronDown, Radar } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import ExtendedScopeBadge from '../status/ExtendedScopeBadge'
import { NAV_SECTIONS } from './navConfig'

export default function Sidebar() {
  const location = useLocation()
  const [hovered, setHovered] = useState(false)
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({})

  // Keep whichever section contains the current route expanded, without
  // collapsing sections the user has opened manually.
  useEffect(() => {
    const active = NAV_SECTIONS.find((s) => s.items.some((i) => location.pathname.startsWith(i.path.split('/:')[0])))
    if (active) setOpenSections((prev) => ({ ...prev, [active.title]: true }))
  }, [location.pathname])

  const toggleSection = (title: string) => setOpenSections((s) => ({ ...s, [title]: !s[title] }))

  return (
    <aside
      className="relative h-full w-16 shrink-0"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        className={clsx(
          'absolute inset-y-0 left-0 z-40 flex h-full flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-1)] transition-[width] duration-200 ease-out',
          hovered ? 'w-64 shadow-2xl' : 'w-16',
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--color-border)] px-4">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-[var(--color-accent)]/15 text-[var(--color-accent)]">
            <Radar size={16} />
          </div>
          {hovered && (
            <div className="qs-fade-in overflow-hidden whitespace-nowrap">
              <div className="text-sm font-semibold tracking-tight text-[var(--color-text-primary)]">QuantSim</div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">Risk Analytics</div>
            </div>
          )}
        </div>

        {!hovered ? (
          <nav className="qs-scrollbar-thin flex-1 overflow-y-auto py-3">
            <div className="flex flex-col items-center gap-1">
              {NAV_SECTIONS.flatMap((s) => s.items).map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  title={item.label}
                  className={({ isActive }) =>
                    clsx(
                      'flex h-9 w-9 items-center justify-center rounded transition-colors',
                      isActive
                        ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                        : 'text-[var(--color-text-secondary)] hover:bg-white/[0.04] hover:text-[var(--color-text-primary)]',
                    )
                  }
                >
                  <item.icon size={16} />
                </NavLink>
              ))}
            </div>
          </nav>
        ) : (
          <nav className="qs-scrollbar-thin qs-fade-in flex-1 overflow-y-auto px-2 py-3">
            {NAV_SECTIONS.map((section) => {
              const solo = section.items.length === 1
              const open = solo || !!openSections[section.title]
              return (
                <div key={section.title} className="mb-1">
                  {!solo && (
                    <button
                      onClick={() => toggleSection(section.title)}
                      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                    >
                      {section.title}
                      <ChevronDown size={12} className={clsx('transition-transform', open && 'rotate-180')} />
                    </button>
                  )}
                  {open && (
                    <div className="flex flex-col gap-0.5 pb-2">
                      {section.items.map((item) => (
                        <NavLink
                          key={item.path}
                          to={item.path}
                          className={({ isActive }) =>
                            clsx(
                              'flex items-center gap-2.5 whitespace-nowrap rounded px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                              isActive
                                ? 'bg-[var(--color-accent)]/12 text-[var(--color-accent)]'
                                : 'text-[var(--color-text-secondary)] hover:bg-white/[0.04] hover:text-[var(--color-text-primary)]',
                            )
                          }
                        >
                          <item.icon size={15} className="shrink-0" />
                          <span className="flex-1 truncate">{item.label}</span>
                          {item.extended && <ExtendedScopeBadge compact />}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </nav>
        )}

        <div className="shrink-0 border-t border-[var(--color-border)] px-4 py-3">
          {hovered ? (
            <span className="qs-fade-in inline-flex items-center gap-1.5 whitespace-nowrap rounded border border-[var(--color-border-strong)] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent)]" />
              Demo Mode
            </span>
          ) : (
            <span className="mx-auto block h-1.5 w-1.5 rounded-full bg-[var(--color-accent)]" />
          )}
        </div>
      </div>
    </aside>
  )
}
