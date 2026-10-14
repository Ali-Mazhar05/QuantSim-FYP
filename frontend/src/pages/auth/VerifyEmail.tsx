import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { ApiError } from '../../services/api/client'
import { resendVerification, verifyEmail } from '../../services/api/platform'
import AuthCard, { AuthNotice } from './AuthCard'
import AuthField from './AuthField'
import {
  INVALID_LINK_MESSAGE,
  LINK_CLASS,
  SENT_MESSAGE,
  clearHash,
  emailProblem,
  errorMessage,
  readHashParams,
} from './authShared'

type Status =
  | { kind: 'verifying' }
  | { kind: 'verified'; approvalRequired: boolean }
  | { kind: 'invalid' }
  | { kind: 'failed'; message: string }

export default function VerifyEmail() {
  const navigate = useNavigate()
  const [token] = useState(() => readHashParams().get('token'))
  const [status, setStatus] = useState<Status>(token ? { kind: 'verifying' } : { kind: 'invalid' })
  const started = useRef(false)

  const verify = useCallback(async (value: string) => {
    setStatus({ kind: 'verifying' })
    try {
      const result = await verifyEmail(value)
      setStatus({ kind: 'verified', approvalRequired: result.approval_required })
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 400) setStatus({ kind: 'invalid' })
      else setStatus({ kind: 'failed', message: errorMessage(failure) })
    }
  }, [])

  useEffect(() => {
    clearHash()
    // A link works once, so it is sent once even when effects run twice in development
    if (!token || started.current) return
    started.current = true
    void verify(token)
  }, [token, verify])

  if (status.kind === 'verified') {
    return (
      <AuthCard title="Email verified" subtitle="Thank you for confirming your address.">
        {status.approvalRequired && (
          <AuthNotice tone="info">An admin must approve your account before you can sign in.</AuthNotice>
        )}
        <Button type="button" className="w-full" onClick={() => navigate('/login')}>
          Sign in
        </Button>
      </AuthCard>
    )
  }

  if (status.kind === 'invalid') return <InvalidLink />

  return (
    <AuthCard title="Verifying your email" subtitle="This takes a moment.">
      {status.kind === 'failed' && (
        <>
          <AuthNotice>{status.message}</AuthNotice>
          {token && (
            <Button type="button" className="w-full" onClick={() => void verify(token)}>
              Try again
            </Button>
          )}
        </>
      )}
      <div className="mt-4 text-center text-xs">
        <Link to="/login" className={LINK_CLASS}>
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  )
}

function InvalidLink() {
  const [email, setEmail] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null)

  const resend = async (e: React.FormEvent) => {
    e.preventDefault()
    const problem = emailProblem(email)
    setFieldError(problem)
    if (problem) return
    setSending(true)
    setNotice(null)
    try {
      await resendVerification(email.trim())
      setNotice({ tone: 'success', text: SENT_MESSAGE })
    } catch (failure) {
      setNotice({ tone: 'warning', text: errorMessage(failure) })
    } finally {
      setSending(false)
    }
  }

  return (
    <AuthCard title="Link not valid" subtitle={INVALID_LINK_MESSAGE} onSubmit={resend}>
      {notice && <AuthNotice tone={notice.tone}>{notice.text}</AuthNotice>}
      <AuthField
        label="Email"
        type="email"
        value={email}
        onChange={setEmail}
        error={fieldError}
        autoComplete="email"
        className="mb-4"
      />
      <Button type="submit" className="w-full" loading={sending}>
        Send a new link
      </Button>
      <div className="mt-4 text-center text-xs">
        <Link to="/login" className={LINK_CLASS}>
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  )
}
