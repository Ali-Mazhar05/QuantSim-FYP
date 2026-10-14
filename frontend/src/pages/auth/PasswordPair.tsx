import AuthField from './AuthField'

/** Password and Confirm password, each with its own error line. */
export default function PasswordPair({
  password,
  confirm,
  onPasswordChange,
  onConfirmChange,
  errors = {},
  passwordLabel = 'Password',
}: {
  password: string
  confirm: string
  onPasswordChange: (value: string) => void
  onConfirmChange: (value: string) => void
  errors?: { password?: string | null; confirm?: string | null }
  passwordLabel?: string
}) {
  return (
    <>
      <AuthField
        label={passwordLabel}
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={onPasswordChange}
        error={errors.password}
      />
      <AuthField
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={onConfirmChange}
        error={errors.confirm}
        className="mb-4"
      />
    </>
  )
}
