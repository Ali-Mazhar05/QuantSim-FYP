import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { ApiError } from '../../services/api/client'
import { setPassword as savePassword } from '../../services/api/platform'
import AuthCard, { AuthNotice } from './AuthCard'
import PasswordPair from './PasswordPair'
import { INVALID_LINK_MESSAGE, LINK_CLASS, clearHash, errorMessage, passwordPairProblems, readHashParams } from './authShared'

export default function SetPassword() {
  const navigate = useNavigate()
  const [link] = useState(() => {
    const params = readHashParams()
    return { token: params.get('token'), purpose: params.get('purpose') === 'invite' ? 'invite' : 'reset' }
  })
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [outcome, setOutcome] = useState<'form' | 'saved' | 'invalid'>(link.token ? 'form' : 'invalid')

  useEffect(() => {
    clearHash()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    const problems = passwordPairProblems(password, confirm)
    setErrors(problems)
    if (problems.password || problems.confirm || !link.token) return
    setSubmitting(true)
    try {
      await savePassword(link.token, password)
      setOutcome('saved')
    } catch (failure) {
      setSubmitting(false)
      if (failure instanceof ApiError && failure.status === 400) setOutcome('invalid')
      else if (failure instanceof ApiError && failure.status === 422 && failure.fieldErrors.password) {
        setErrors({ password: failure.fieldErrors.password })
      } else setFormError(errorMessage(failure))
    }
  }

  if (outcome === 'saved') {
    return (
      <AuthCard title="Password saved" subtitle="You can now sign in with your new password.">
        <Button type="button" className="w-full" onClick={() => navigate('/login')}>
          Sign in
        </Button>
      </AuthCard>
    )
  }

  if (outcome === 'invalid') {
    return (
      <AuthCard title="Link not valid" subtitle={INVALID_LINK_MESSAGE}>
        <p className="mb-4 text-sm leading-relaxed text-[var(--color-text-secondary)]">
          Links work once and expire. Ask for a new one to change your password.
        </p>
        <Button type="button" className="w-full" onClick={() => navigate('/forgot-password')}>
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

  return (
    <AuthCard
      title={link.purpose === 'invite' ? 'Set your password' : 'Change your password'}
      subtitle="Use at least 12 characters."
      onSubmit={handleSubmit}
    >
      {formError && <AuthNotice>{formError}</AuthNotice>}
      <PasswordPair
        password={password}
        confirm={confirm}
        onPasswordChange={setPassword}
        onConfirmChange={setConfirm}
        errors={errors}
        passwordLabel="New password"
      />
      <Button type="submit" className="w-full" loading={submitting}>
        Save password
      </Button>
    </AuthCard>
  )
}
