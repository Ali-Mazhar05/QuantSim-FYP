import { Bell, ChevronDown, LogOut, Radio, Search, Settings } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDemoStore } from '../../demo/demoState'
import { useRiskAlerts } from '../../demo/useRiskAlerts'
import type { Role } from '../../types'
import { MARKET_ENVIRONMENTS } from '../../services/mock/data'
import StatusPill from '../status/StatusPill'

const ROLES: Role[] = ['Viewer', 'Analyst', 'Quant', 'Admin']

export default function Topbar() {
  const navigate = useNavigate()
  const role = useDemoStore((s) => s.role)
  const setRole = useDemoStore((s) => s.setRole)
  const logout = useDemoStore((s) => s.logout)
  const flowStep = useDemoStore((s) => s.flowStep)
  const { active: activeAlerts } = useRiskAlerts()
  const toggleSystemActivity = useDemoStore((s) => s.toggleSystemActivity)

  const [roleOpen, setRoleOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)

  const simStatus = flowStep === 'IDLE' ? 'Idle' : flowStep === 'SIMULATION_RUNNING' ? 'Running' : 'Ready'
  const activeEnv = MARKET_ENVIRONMENTS[0]

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-bg-1)] px-4">
      <div className="flex items-center gap-3">
        <div>
          <div className="text-sm font-semibold text-[var(--color-text-primary)]">Research Environment</div>
          <div className="text-[11px] text-[var(--color-text-muted)]">{activeEnv.name}</div>
        </div>
      </div>

      <div className="flex flex-1 justify-center px-8">
        <div className="relative w-full max-w-md">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            placeholder="Search simulations, portfolios, instruments…"
            className="w-full rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] py-1.5 pl-8 pr-3 text-xs text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-strong)] focus:outline-none"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={toggleSystemActivity}
          className="hidden items-center gap-1.5 rounded border border-[var(--color-border-strong)] px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent-strong)] hover:text-[var(--color-accent-strong)] lg:flex"
        >
          <Radio size={13} />
          Activity
        </button>

        <StatusPill tone={simStatus === 'Running' ? 'info' : 'success'} dot>
          Simulation {simStatus}
        </StatusPill>

        <div className="relative">
          <button
            onClick={() => setNotifOpen((v) => !v)}
            className="relative rounded p-1.5 text-[var(--color-text-secondary)] hover:bg-black/5 hover:text-[var(--color-text-primary)]"
          >
            <Bell size={16} />
            {activeAlerts.length > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--color-risk-severe)] px-1 text-[9px] font-bold text-white">
                {activeAlerts.length}
              </span>
            )}
          </button>
          {notifOpen && (
            <div className="qs-fade-in qs-panel absolute right-0 top-full z-30 mt-2 w-80 rounded shadow-xl">
              <div className="border-b border-[var(--color-border)] px-3.5 py-2.5 text-xs font-semibold text-[var(--color-text-primary)]">
                Notifications
              </div>
              {activeAlerts.length > 0 ? (
                <div className="max-h-80 overflow-y-auto">
                  {activeAlerts.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => {
                        setNotifOpen(false)
                        navigate('/alerts')
                      }}
                      className="flex w-full flex-col gap-1 border-b border-[var(--color-border)] px-3.5 py-3 text-left hover:bg-black/[0.03]"
                    >
                      <span className="text-xs font-semibold text-[var(--color-risk-high)]">{a.title}</span>
                      <span className="text-xs text-[var(--color-text-secondary)]">{a.message}</span>
                      <span className="mono text-[10px] text-[var(--color-text-muted)]">
                        {a.source} · {a.createdAt}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="px-3.5 py-6 text-center text-xs text-[var(--color-text-muted)]">
                  No active notifications.
                </div>
              )}
              <button
                onClick={() => {
                  setNotifOpen(false)
                  navigate('/alerts')
                }}
                className="w-full px-3.5 py-2.5 text-center text-xs font-medium text-[var(--color-accent-strong)] hover:bg-black/[0.03]"
              >
                View all alerts
              </button>
            </div>
          )}
        </div>

        <div className="relative">
          <button
            onClick={() => setRoleOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded border border-[var(--color-border-strong)] px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent-strong)]"
          >
            {role}
            <ChevronDown size={13} />
          </button>
          {roleOpen && (
            <div className="qs-fade-in qs-panel absolute right-0 top-full z-30 mt-2 w-40 rounded p-1 shadow-xl">
              {ROLES.map((r) => (
                <button
                  key={r}
                  onClick={() => {
                    setRole(r)
                    setRoleOpen(false)
                  }}
                  className={`block w-full rounded px-2.5 py-1.5 text-left text-xs ${
                    r === role ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]' : 'text-[var(--color-text-secondary)] hover:bg-black/5'
                  }`}
                >
                  Demo as {r}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="relative">
          <button onClick={() => setProfileOpen((v) => !v)} className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-accent)]/20 text-xs font-semibold text-[var(--color-accent-strong)]">
              AM
            </div>
          </button>
          {profileOpen && (
            <div className="qs-fade-in qs-panel absolute right-0 top-full z-30 mt-2 w-52 rounded p-1 shadow-xl">
              <div className="px-3 py-2 text-xs">
                <div className="font-semibold text-[var(--color-text-primary)]">Awais</div>
                <div className="text-[var(--color-text-muted)]">Awais@powerbanclending.com</div>
              </div>
              <div className="my-1 h-px bg-[var(--color-border)]" />
              <button
                onClick={() => {
                  setProfileOpen(false)
                  navigate('/settings')
                }}
                className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left text-xs text-[var(--color-text-secondary)] hover:bg-black/5"
              >
                <Settings size={13} /> Settings
              </button>
              <button
                onClick={logout}
                className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left text-xs text-[var(--color-text-secondary)] hover:bg-black/5"
              >
                <LogOut size={13} /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
