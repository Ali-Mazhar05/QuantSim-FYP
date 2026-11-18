import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useEffect, useState } from 'react'
import { useDemoStore } from '../demo/demoState'
import { createQueryClient } from './queryClient'

/** Gives every hook its cache. Signing out empties it, so one user's data never shows to the next. */
export default function QueryProvider({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient())
  const authenticated = useDemoStore((s) => s.authenticated)
  useEffect(() => {
    if (!authenticated) queryClient.clear()
  }, [authenticated, queryClient])
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
