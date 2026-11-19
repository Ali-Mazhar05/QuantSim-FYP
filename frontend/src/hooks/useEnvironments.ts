import { useEffect, useState } from 'react'
import { useDemoStore } from '../demo/demoState'
import { errorMessage } from '../pages/auth/authShared'
import { type Environment, listEnvironments } from '../services/api/market'

export interface EnvironmentsState {
  /** Null while loading. */
  environments: Environment[] | null
  error: string | null
  /** The session's active environment: the one chosen in this session, else the newest. */
  active: Environment | null
}

/** The market environments from the API, loaded once per mounted component. */
export function useEnvironments(): EnvironmentsState {
  const authenticated = useDemoStore((s) => s.authenticated)
  const activeId = useDemoStore((s) => s.activeEnvironmentId)
  const [environments, setEnvironments] = useState<Environment[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!authenticated) return
    let cancelled = false
    listEnvironments()
      .then((rows) => !cancelled && setEnvironments(rows))
      .catch((failure: unknown) => !cancelled && setError(errorMessage(failure)))
    return () => {
      cancelled = true
    }
  }, [authenticated, activeId])

  const active = environments?.find((e) => e.id === activeId) ?? environments?.[0] ?? null
  return { environments, error, active }
}
