import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { ApiError } from '../../services/api/client'
import { apiRole, signUp, type AccountType } from '../../services/api/platform'
import type { Role } from '../../types'
import AuthCard, { AuthNotice } from './AuthCard'
import AuthField from './AuthField'
import PasswordPair from './PasswordPair'
import RoleGrid from './RoleGrid'
import {
  LINK_CLASS,
  ROLE_OPTIONS,
  emailProblem,
  errorMessage,
  passwordPairProblems,
  usernameProblem,
} from './authShared'

// Admin is never offered: only an existing admin can make someone an admin
const ACCOUNT_TYPES = ROLE_OPTIONS.filter((r) => r.role !== 'Admin')

type Field = 'username' | 'email' | 'password' | 'confirm' | 'account_type'

export default function SignUp() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [accountType, setAccountType] = useState<Role>('Quant')
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    const found: Partial<Record<Field, string>> = {
      username: usernameProblem(username) ?? undefined,
      email: emailProblem(email) ?? undefined,
      ...passwordPairProblems(password, confirm),
    }
    const problems = Object.fromEntries(Object.entries(found).filter(([, v]) => v)) as Partial<Record<Field, string>>
    setErrors(problems)
    if (Object.keys(problems).length > 0) return

    setSubmitting(true)
    const address = email.trim()
    try {
      await signUp({
        username: username.trim().toLowerCase(),
        email: address,
        password,
        account_type: apiRole(accountType) as AccountType,
      })
      navigate('/check-email', { state: { email: address } })
    } catch (failure) {
      setSubmitting(false)
      if (failure instanceof ApiError && failure.status === 409) {
        setErrors({ username: 'That username is already taken.' })
      } else if (failure instanceof ApiError && failure.status === 422 && Object.keys(failure.fieldErrors).length > 0) {
        setErrors(failure.fieldErrors as Partial<Record<Field, string>>)
      } else if (failure instanceof ApiError && failure.status === 404) {
        setFormError('Sign-up is closed on this environment')
      } else {
        setFormError(errorMessage(failure))
      }
    }
  }

  return (
    <AuthCard title="Create account" subtitle="Join the QuantSim Research Environment." onSubmit={handleSubmit}>
      {formError && <AuthNotice>{formError}</AuthNotice>}
      <AuthField label="Username" value={username} onChange={setUsername} error={errors.username} autoComplete="username" />
      <AuthField label="Email" type="email" value={email} onChange={setEmail} error={errors.email} autoComplete="email" />
      <PasswordPair
        password={password}
        confirm={confirm}
        onPasswordChange={setPassword}
        onConfirmChange={setConfirm}
        errors={errors}
      />

      <div className="mb-5">
        <RoleGrid label="Account type" roles={ACCOUNT_TYPES} value={accountType} onChange={setAccountType} />
        {errors.account_type && (
          <span className="mt-1 block text-[11px] text-[var(--color-risk-severe)]">{errors.account_type}</span>
        )}
        <p className="mt-2 text-[11px] leading-snug text-[var(--color-text-muted)]">
          Analyst and Quant accounts are activated after an admin approves them.
        </p>
      </div>

      <Button type="submit" className="w-full" loading={submitting}>
        Create account
      </Button>

      <div className="mt-4 text-center text-xs text-[var(--color-text-secondary)]">
        Already have an account?{' '}
        <Link to="/login" className={LINK_CLASS}>
          Sign in
        </Link>
      </div>
    </AuthCard>
  )
}
