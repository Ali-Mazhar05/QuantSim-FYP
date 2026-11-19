import clsx from 'clsx'
import { useState } from 'react'
import Button from '../../components/forms/Button'
import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import { useNotifications } from '../../demo/notifications'
import { changePassword } from '../../services/api/platform'
import AuthField from '../auth/AuthField'
import PasswordPair from '../auth/PasswordPair'
import { errorMessage, passwordPairProblems } from '../auth/authShared'

const TABS = ['General', 'Appearance', 'Notifications', 'Risk Thresholds', 'Simulation Defaults', 'Data Sources', 'Security'] as const

export default function Settings() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('General')
  const push = useNotifications((s) => s.push)

  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader title="Settings" description="Configure workspace preferences and platform defaults." />
      <div className="flex flex-wrap gap-1 border-b border-[var(--color-border)]">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'border-b-2 px-3 py-2 text-sm font-medium',
              tab === t ? 'border-[var(--color-accent-strong)] text-[var(--color-accent-strong)]' : 'border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <Panel title={tab}>
        {tab === 'General' && (
          <div className="flex flex-col gap-4 text-sm">
            <Field label="Workspace Name" value="Research Environment" />
            <Field label="Default Base Currency" value="USD" />
            <Field label="Time Zone" value="America/New_York" />
          </div>
        )}
        {tab === 'Appearance' && (
          <div className="flex flex-col gap-4 text-sm">
            <Field label="Theme" value="Dark (Institutional)" />
            <Field label="Density" value="Comfortable" />
          </div>
        )}
        {tab === 'Notifications' && (
          <div className="flex flex-col gap-3 text-sm">
            {['High-severity alerts', 'Simulation completion', 'Report exports'].map((n) => (
              <label key={n} className="flex items-center gap-2.5">
                <input type="checkbox" defaultChecked className="accent-[var(--color-accent)]" />
                {n}
              </label>
            ))}
          </div>
        )}
        {tab === 'Risk Thresholds' && (
          <div className="flex flex-col gap-4 text-sm">
            <Field label="Composite Risk — HIGH threshold" value="70" />
            <Field label="Composite Risk — SEVERE threshold" value="85" />
            <Field label="TDA structural shift alert threshold" value="75" />
          </div>
        )}
        {tab === 'Simulation Defaults' && (
          <div className="flex flex-col gap-4 text-sm">
            <Field label="Default Model" value="GBM" />
            <Field label="Default Paths" value="10,000" />
            <Field label="Default Confidence" value="95%" />
          </div>
        )}
        {tab === 'Data Sources' && (
          <div className="flex flex-col gap-4 text-sm">
            <Field label="Primary Feed" value="Synthetic Market Generator" />
            <Field label="Historical Archive" value="Internal Research Dataset" />
          </div>
        )}
        {tab === 'Security' && <ChangePassword />}

        {tab !== 'Security' && (
          <div className="mt-6 border-t border-[var(--color-border)] pt-4">
            <Button onClick={() => push('Settings saved', 'success')}>Save Changes</Button>
          </div>
        )}
      </Panel>
    </div>
  )
}

/** Change your own password; the platform signs out every other session. */
function ChangePassword() {
  const notify = useNotifications((s) => s.push)
  const [current, setCurrent] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<{ current?: string; password?: string; confirm?: string }>({})
  const [saving, setSaving] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const found = { ...(current ? {} : { current: 'Enter your current password' }), ...passwordPairProblems(password, confirm) }
    setErrors(found)
    if (Object.keys(found).length > 0) return
    setSaving(true)
    try {
      await changePassword(current, password)
      setCurrent('')
      setPassword('')
      setConfirm('')
      notify('Password changed. Your other sessions were signed out.', 'success')
    } catch (failure) {
      setErrors({ current: errorMessage(failure) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex max-w-sm flex-col text-sm" aria-label="Change password">
      <p className="mb-4 text-[var(--color-text-secondary)]">
        Changing your password signs you out on every other device and browser.
      </p>
      <AuthField
        label="Current password"
        type="password"
        value={current}
        onChange={setCurrent}
        error={errors.current}
        autoComplete="current-password"
      />
      <PasswordPair
        password={password}
        confirm={confirm}
        onPasswordChange={setPassword}
        onConfirmChange={setConfirm}
        errors={errors}
        passwordLabel="New password"
      />
      <div className="mt-2">
        <Button type="submit" loading={saving}>
          Change password
        </Button>
      </div>
    </form>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-[var(--color-text-secondary)]">{label}</span>
      <input
        defaultValue={value}
        className="max-w-sm rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent-strong)] focus:outline-none"
      />
    </label>
  )
}
