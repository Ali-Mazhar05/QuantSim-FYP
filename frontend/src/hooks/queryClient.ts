import { QueryClient } from '@tanstack/react-query'

/**
 * One client per app mount. Retries are off so a failure shows at once, as the pages behaved
 * before the kit; a query that should retry sets `retry` itself. Data counts as fresh for 15 s,
 * so moving between pages does not refetch what was just read.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}
