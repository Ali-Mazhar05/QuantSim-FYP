import { useQuery } from '@tanstack/react-query'
import { useDemoStore } from '../demo/demoState'
import { errorMessage } from '../pages/auth/authShared'
import { type Environment, listEnvironments } from '../services/api/market'
import { marketKeys } from './queryKeys'

export interface EnvironmentsState {
  /** Null while loading. */
  environments: Environment[] | null
  error: string | null
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
  const error = query.error ? errorMessage(query.error) : null
  const active = environments?.find((e) => e.id === activeId) ?? environments?.[0] ?? null
  return { environments, error, active }
}
