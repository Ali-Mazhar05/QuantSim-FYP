import { useQuery } from '@tanstack/react-query'
import { useDemoStore } from '../demo/demoState'
import { type ClassifiedError, classifyError } from './apiError'
import { type Environment, listEnvironments } from '../services/api/market'
import { marketKeys } from './keys/market'

export interface EnvironmentsState {
  /** Null while loading. */
  environments: Environment[] | null
  /** Why the read failed, classified (a 403 is `kind === 'forbidden'`); null when it did not. */
  error: ClassifiedError | null
  /** The session's active environment: the one chosen in this session, else the newest. */
  active: Environment | null
}

/** The market environments from the API, shared by every component that asks. */
export function useEnvironments(): EnvironmentsState {
  const authenticated = useDemoStore((s) => s.authenticated)
  const activeId = useDemoStore((s) => s.activeEnvironmentId)
  const query = useQuery({
    queryKey: marketKeys.environments(),
    queryFn: ({ signal }) => listEnvironments({ signal }),
    enabled: authenticated,
  })
  const environments = query.data ?? null
  const error = query.error ? classifyError(query.error) : null
  const active = environments?.find((e) => e.id === activeId) ?? environments?.[0] ?? null
  return { environments, error, active }
}
