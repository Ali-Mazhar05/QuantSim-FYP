import { useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../../components/forms/Button'
import { ApiError } from '../../services/api/client'
import { forgotPassword } from '../../services/api/platform'
import AuthCard, { AuthNotice } from './AuthCard'
import AuthField from './AuthField'
import { LINK_CLASS, SENT_MESSAGE, emailProblem, errorMessage } from './authShared'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const problem = emailProblem(email)
    setFieldError(problem)
    if (problem) return
    setSending(true)
    setError(null)
    try {
      await forgotPassword(email.trim())
      setSent(true)
    } catch (failure) {
      // The answer never says whether the address has an account: only a limit, a server
      // fault or an unreachable server is reported
      if (failure instanceof ApiError && failure.status < 500 && failure.status !== 429) setSent(true)
      else setError(errorMessage(failure))
    } finally {
      setSending(false)
    }
  }

  return (
    <AuthCard
      title="Forgot password"
      subtitle="Enter your account's email and we will send you a link to change your password."
      onSubmit={handleSubmit}
    >
      {sent && <AuthNotice tone="success">{SENT_MESSAGE}</AuthNotice>}
      {error && <AuthNotice>{error}</AuthNotice>}
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
        Send reset link
      </Button>
      <div className="mt-4 text-center text-xs">
        <Link to="/login" className={LINK_CLASS}>
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  )
}
