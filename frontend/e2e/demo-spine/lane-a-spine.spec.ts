// Lane A demo spine on TEST (I2-62, A-NFR-16): the same spine as on DEV (dev-smoke/spine.ts)
// on a real replay environment from Lane B's market service. It gates test -> acceptance
// (ci/scripts/playwright-gate.sh test demo-spine).
//
// The environment is QS_E2E_REPLAY_ENV_ID when set, otherwise the first active historical
// replay the market service lists whose ticks it serves. Until the market feed serves
// ticks (B12; the route answers 501 today) there is no such environment and the test is
// skipped with that reason in the report, so the gate does not block on Lane B; it runs in
// full as soon as one exists.

import { expect, test, type APIRequestContext } from '@playwright/test'
import { apiBase, laneASpine, tokenFor } from '../dev-smoke/spine'
import { credentials } from '../dev-smoke/support'

interface Environment {
  id: string
  name: string
  status: string
}

/** A replay environment the spine can run on, or why there is none. */
async function replayEnvironment(request: APIRequestContext): Promise<{ id: string } | { reason: string }> {
  const chosen = process.env.QS_E2E_REPLAY_ENV_ID?.trim()
  if (chosen) return { id: chosen }

  const { username, password } = credentials()
  const api = await apiBase(request)
  const headers = { Authorization: `Bearer ${await tokenFor(request, api, username, password)}` }
  const listed = await request.get(`${api}/api/market/environments?type=historical_replay`, { headers })
  expect(listed.status(), 'the market service lists its environments').toBe(200)
  const active = ((await listed.json()) as Environment[]).filter((e) => e.status === 'active')
  if (active.length === 0) return { reason: 'the market service has no active historical replay environment' }

  const statuses: string[] = []
  for (const environment of active) {
    const ticks = await request.get(`${api}/api/market/environments/${environment.id}/ticks?limit=1`, { headers })
    if (ticks.ok()) return { id: environment.id }
    statuses.push(`${environment.name}: ${ticks.status()}`)
  }
  return { reason: `no active replay environment serves its ticks yet (${statuses.join(', ')})` }
}

test('a momentum portfolio on a real replay runs with costs and slippage, rebuilds identical and reruns to the same hash', async ({
  page,
  request,
}) => {
  const environment = await replayEnvironment(request)
  if ('reason' in environment) {
    test.skip(true, `Lane B's feed is not ready on this environment: ${environment.reason}`)
    return
  }
  await laneASpine(page, request, environment.id)
})
