import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useDemoStore } from '../demo/demoState'
import { createQueryClient } from './queryClient'

/**
 * Gives every hook its cache. Signing out empties it, so one user's data never shows to the next.
 * Only the change from signed in to signed out empties it: a page that starts signed out must not
 * lose a request it has just made.
 */
export default function QueryProvider({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient())
  const authenticated = useDemoStore((s) => s.authenticated)
  const wasAuthenticated = useRef(authenticated)
  useEffect(() => {
    if (wasAuthenticated.current && !authenticated) queryClient.clear()
    wasAuthenticated.current = authenticated
  }, [authenticated, queryClient])
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
