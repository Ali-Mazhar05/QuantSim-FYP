import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { ApiError } from '../services/api/client'

/**
 * One client per app mount. Retries are off so a failure shows at once, as the pages behaved
 * before the kit; a query that should retry sets `retry` itself. Data counts as fresh for 15 s,
 * so moving between pages does not refetch what was just read.
 *
 * `onUnauthenticated` runs when any query or mutation ends in a 401. By then the client has already
 * tried to refresh the session once, so the session is over: the app signs the user out.
 */
export function createQueryClient(onUnauthenticated?: () => void): QueryClient {
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onUnauthenticated?.()
  }
  return new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: { staleTime: 15_000, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}
