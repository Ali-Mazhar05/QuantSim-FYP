// Replay sessions of the market service (B13): the clock lives on the server, so a page only asks for
// the position and sends play, pause, speed and seek. Typed from the generated market schema.

import type { MarketComponents } from '../generated'
import { apiGet, apiPost, type RequestOptions } from './typed'

export type ReplaySession = MarketComponents['schemas']['SessionOut']
export type ReplaySpeed = ReplaySession['speed']
export const SPEEDS: ReplaySpeed[] = [1, 5, 20]

const BASE = '/api/market'

/** The newest session of an environment, or null when it has none (the list is newest first). */
export async function latestSession(environmentId: string, options: RequestOptions = {}): Promise<ReplaySession | null> {
  const sessions = await apiGet(`${BASE}/replay-sessions`, { query: { environment_id: environmentId }, ...options })
  return sessions[0] ?? null
}

export const createSession = (environmentId: string, speed: ReplaySpeed = 1): Promise<ReplaySession> =>
  apiPost(`${BASE}/replay-sessions`, { environment_id: environmentId, speed })

type Control = MarketComponents['schemas']['Play' | 'Pause' | 'SetSpeed' | 'Seek']

export const controlSession = (id: string, body: Control): Promise<ReplaySession> =>
  apiPost(`${BASE}/replay-sessions/{session_id}/control`, body, { path: { session_id: id } })

/** Activating freezes the fingerprint a session pins; quants and admins only. */
export const activateEnvironment = (environmentId: string) =>
  apiPost(`${BASE}/environments/{environment_id}/activate`, undefined, { path: { environment_id: environmentId } })
