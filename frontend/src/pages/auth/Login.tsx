import clsx from 'clsx'
import { Radar } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { useDemoStore } from '../../demo/demoState'
import { useNotifications } from '../../demo/notifications'
import { ApiError, ApiUnreachableError } from '../../services/api/client'
import { signIn } from '../../services/api/platform'
import type { Role } from '../../types'

const ROLES: { role: Role; description: string }[] = [
  { role: 'Viewer', description: 'View dashboards, reports & alerts' },
  { role: 'Analyst', description: 'Run stress tests & TDA analysis' },
  { role: 'Quant', description: 'Launch simulations & build portfolios' },
  { role: 'Admin', description: 'Manage users, roles & system' },
]

export default function Login() {
  const navigate = useNavigate()
  const login = useDemoStore((s) => s.login)
  const signInLive = useDemoStore((s) => s.signInLive)
  const notify = useNotifications((s) => s.push)
  const [role, setRole] = useState<Role>('Quant')
  const [username, setUsername] = useState('quant.demo')
  const [password, setPassword] = useState('••••••••')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      // Real sign-in: the account's role decides access; the picker can only preview
      // that role or a lower one
      signInLive(await signIn(username, password), role)
      navigate('/dashboard')
    } catch (error) {
      if (error instanceof ApiUnreachableError) {
        // No backend reachable from this browser: keep the POC working on mock data
        login(role)
        notify('Backend not reachable from this browser; running in demo mode', 'info')
        navigate('/dashboard')
      } else {
        notify(error instanceof ApiError ? error.message : 'Sign-in failed', 'warning')
        setSubmitting(false)
      }
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-0)] px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-[var(--color-accent)]/15 text-[var(--color-accent-strong)]">
            <Radar size={24} />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-text-primary)]">QuantSim</h1>
          <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
            AI-Assisted Market Simulation
            <br />
            &amp; Portfolio Risk Analytics
          </p>
        </div>

        <form onSubmit={handleSubmit} className="qs-panel rounded p-6">
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none"
            />
          </label>
          <label className="mb-4 block">
            <span className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none"
            />
          </label>

          <div className="mb-5">
            <span className="mb-2 block text-xs font-medium text-[var(--color-text-secondary)]">Demo as</span>
            <div className="grid grid-cols-2 gap-2">
              {ROLES.map((r) => (
                <button
                  type="button"
                  key={r.role}
                  onClick={() => setRole(r.role)}
                  className={clsx(
                    'rounded border px-3 py-2 text-left transition-colors',
                    role === r.role
                      ? 'border-[var(--color-accent-strong)] bg-[var(--color-accent)]/10'
                      : 'border-[var(--color-border-strong)] hover:border-[var(--color-border-strong)]/80',
                  )}
                >
                  <div
                    className={clsx(
                      'text-xs font-semibold',
                      role === r.role ? 'text-[var(--color-accent-strong)]' : 'text-[var(--color-text-primary)]',
                    )}
                  >
                    {r.role}
                  </div>
                  <div className="mt-0.5 text-[10px] leading-snug text-[var(--color-text-muted)]">{r.description}</div>
                </button>
              ))}
            </div>
          </div>

          <Button type="submit" className="w-full" loading={submitting}>
            Sign In
          </Button>

          <div className="mt-4 text-center text-xs text-[var(--color-text-muted)]">Research Environment</div>
        </form>
      </div>
    </div>
  )
}
