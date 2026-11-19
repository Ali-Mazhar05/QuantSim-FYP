import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { resendVerification } from '../../services/api/platform'
import AuthCard, { AuthNotice } from './AuthCard'
import { LINK_CLASS, SENT_MESSAGE, errorMessage } from './authShared'

export default function CheckEmail() {
  const { state } = useLocation()
  const email = typeof (state as { email?: unknown } | null)?.email === 'string' ? (state as { email: string }).email : ''
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null)

  const resend = async () => {
    setSending(true)
    setNotice(null)
    try {
      await resendVerification(email)
      setNotice({ tone: 'success', text: SENT_MESSAGE })
    } catch (failure) {
      setNotice({ tone: 'warning', text: errorMessage(failure) })
    } finally {
      setSending(false)
    }
  }

  return (
    <AuthCard title="Check your email" subtitle="Open the link we sent you to finish creating your account.">
      {notice && <AuthNotice tone={notice.tone}>{notice.text}</AuthNotice>}
      <p className="mb-2 text-sm leading-relaxed text-[var(--color-text-secondary)]">
        {email ? (
          <>
            We sent a verification link to{' '}
            <span className="mono font-semibold text-[var(--color-text-primary)]">{email}</span>.
          </>
        ) : (
          'We sent a verification link to the address you gave.'
        )}
      </p>
      <p className="mb-5 text-xs leading-relaxed text-[var(--color-text-muted)]">
        It can take a minute to arrive. If you cannot find it, look in your spam folder.
      </p>
      {email && (
        <Button type="button" variant="secondary" className="w-full" loading={sending} onClick={resend}>
          Send the link again
        </Button>
      )}
      <div className="mt-4 text-center text-xs">
        <Link to="/login" className={LINK_CLASS}>
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  )
}
