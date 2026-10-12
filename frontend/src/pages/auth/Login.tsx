import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { useDemoStore } from '../../demo/demoState'
import { ApiError } from '../../services/api/client'
import {
  PROBLEM_APPROVAL_PENDING,
  PROBLEM_EMAIL_UNVERIFIED,
  resendVerification,
  roleName,
  signIn,
} from '../../services/api/platform'
import type { Role } from '../../types'
import AuthCard, { AuthNotice } from './AuthCard'
import AuthField from './AuthField'
import { LINK_CLASS, SENT_MESSAGE, emailProblem, errorMessage } from './authShared'

type View = { kind: 'form' } | { kind: 'unverified' } | { kind: 'pending'; role: Role | null }

export default function Login() {
  const navigate = useNavigate()
  const startSession = useDemoStore((s) => s.startSession)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>({ kind: 'form' })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      startSession(await signIn(username.trim(), password))
      navigate('/dashboard')
    } catch (failure) {
      setSubmitting(false)
      if (failure instanceof ApiError && failure.status === 403 && failure.type === PROBLEM_EMAIL_UNVERIFIED) {
        setView({ kind: 'unverified' })
      } else if (failure instanceof ApiError && failure.status === 403 && failure.type === PROBLEM_APPROVAL_PENDING) {
        setView({ kind: 'pending', role: roleName(failure.body.requested_role) })
      } else {
        setError(errorMessage(failure))
      }
    }
  }

  const backToSignIn = () => {
    setPassword('')
    setError(null)
    setView({ kind: 'form' })
  }

  if (view.kind === 'unverified') {
    return <VerifyFirst identifier={username.trim()} onBack={backToSignIn} />
  }

  if (view.kind === 'pending') {
    return (
      <AuthCard title="Waiting for admin approval" subtitle="Your email is verified.">
        <p className="mb-5 text-sm leading-relaxed text-[var(--color-text-secondary)]">
          {view.role ? (
            <>
              An admin must approve your <span className="font-semibold text-[var(--color-text-primary)]">{view.role}</span>{' '}
              account before you can sign in.
            </>
          ) : (
            'An admin must approve your account before you can sign in.'
          )}{' '}
          You will get an email when it is approved.
        </p>
        <Button type="button" variant="secondary" className="w-full" onClick={backToSignIn}>
          Back to sign in
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard onSubmit={handleSubmit}>
      {error && <AuthNotice>{error}</AuthNotice>}
      <AuthField label="Username or email" value={username} onChange={setUsername} autoComplete="username" />
      <AuthField
        label="Password"
        type="password"
        value={password}
        onChange={setPassword}
        autoComplete="current-password"
        className="mb-2"
      />
      <div className="mb-5 text-right text-xs">
        <Link to="/forgot-password" className={LINK_CLASS}>
          Forgot password?
        </Link>
      </div>

      <Button type="submit" className="w-full" loading={submitting}>
        Sign In
      </Button>

      <div className="mt-4 text-center text-xs text-[var(--color-text-secondary)]">
        No account yet?{' '}
        <Link to="/signup" className={LINK_CLASS}>
          Create account
        </Link>
      </div>
    </AuthCard>
  )
}

/** "Verify your email first", with a resend that asks for the email when a username was typed. */
function VerifyFirst({ identifier, onBack }: { identifier: string; onBack: () => void }) {
  const typedEmail = identifier.includes('@')
  const [email, setEmail] = useState(typedEmail ? identifier : '')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)
  // Ask for the address unless a valid one was typed to sign in
  const askEmail = !typedEmail || emailProblem(identifier) !== null

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
    <AuthCard title="Verify your email first" subtitle="Open the link we emailed you, then sign in." onSubmit={resend}>
      {notice && <AuthNotice tone={notice.tone}>{notice.text}</AuthNotice>}
      {askEmail && (
        <AuthField
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          error={fieldError}
          autoComplete="email"
          className="mb-4"
        />
      )}
      <Button type="submit" className="w-full" loading={sending}>
        Send the link again
      </Button>
      <Button type="button" variant="ghost" className="mt-2 w-full" onClick={onBack}>
        Back to sign in
      </Button>
    </AuthCard>
  )
}
