import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDemoStore } from '../demo/demoState'
import {
  type ReplaySession,
  type ReplaySpeed,
  activateEnvironment,
  controlSession,
  createSession,
  latestSession,
} from '../services/api/replay'
import { classifyError } from './apiError'
import { marketKeys } from './keys/market'

/** How often a playing session is read: the server computes the position on read (ADR 06). */
export const REPLAY_POLL_MS = 750

/** The newest replay session of an environment; read again while it is playing. */
export function useReplaySession(environmentId: string | undefined) {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: marketKeys.session(environmentId ?? ''),
    queryFn: ({ signal }) => latestSession(environmentId as string, { signal }),
    enabled: signedIn && Boolean(environmentId),
    refetchInterval: (q) => (q.state.data?.state === 'playing' && !q.state.data.finished ? REPLAY_POLL_MS : false),
  })
  return {
    session: query.data ?? null,
    loaded: query.data !== undefined,
    error: query.error ? classifyError(query.error) : null,
  }
}

type Action = { kind: 'play' } | { kind: 'pause' } | { kind: 'speed'; speed: ReplaySpeed } | { kind: 'seek'; index: number }

/**
 * The controls. Play starts a session when the environment has none, after activating the
 * environment when it is not active yet (a session pins the fingerprint activation froze).
 */
export function useReplayControls(environmentId: string | undefined, active: boolean) {
  const queryClient = useQueryClient()
  const key = marketKeys.session(environmentId ?? '')
  return useMutation({
    mutationFn: async ({ action, session }: { action: Action; session: ReplaySession | null }) => {
      let current = session
      if (!current) {
        if (!environmentId) throw new Error('There is no environment to replay.')
        if (!active) await activateEnvironment(environmentId)
        current = await createSession(environmentId)
      }
      switch (action.kind) {
        case 'play':
          return controlSession(current.id, { action: 'play' })
        case 'pause':
          return controlSession(current.id, { action: 'pause' })
        case 'speed':
          return controlSession(current.id, { action: 'speed', speed: action.speed })
        case 'seek':
          return controlSession(current.id, { action: 'seek', index: action.index })
      }
    },
    onSuccess: async (session) => {
      queryClient.setQueryData(key, session)
      await queryClient.invalidateQueries({ queryKey: marketKeys.environments() })
    },
  })
}
