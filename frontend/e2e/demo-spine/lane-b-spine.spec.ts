// Lane B demo spine on TEST (B22, B-FR-21, B-NFR-16): steps 1 to 4 and the failure cases of the
// Final-I demo, on a real replay environment of the market service. It gates test -> acceptance
// (ci/scripts/playwright-gate.sh test demo-spine), beside Lane A's spine.
//
//   1  sign in
//   2  replay: play, speed, pause, seek, and the position survives a reload (the clock is the server's)
//   3  calibrate and simulate: Configure fits each instrument, the run is polled to completion
//   4  results and stress: the risk table and the fan chart, a flash crash beside the base run
//   8  failure cases: an inverted window is refused; a run on another instrument's calibration is refused
//
// The pages are driven like a quant would drive them; what a page does not show (the tick feed of
// a path, the median path, the refusals) goes to the APIs with a token from the platform's sign-in.
// The environment is QS_E2E_REPLAY_ENV_ID when set, otherwise the first historical replay the
// market service lists whose ticks it serves. A copy of it is created for the run, so it is the
// newest environment and the pages (which open on the newest) use it, whatever else exists.

import { expect, test, type APIRequestContext } from '@playwright/test'
import { apiBase, tokenFor } from '../dev-smoke/spine'
import { credentials, openInApp, signIn, watchPage } from '../dev-smoke/support'

const RUN_TIMEOUT_MS = 5 * 60_000

interface Environment {
  id: string
  name: string
  status: string
  universe: string
  instrument_ids: string[]
  start_date: string
  end_date: string
}

interface Tick {
  seq: number
  env_type: string
  scenario: string | null
  path_index: number | null
  source_fingerprint: string
}

/** A replay environment the spine can use, or why there is none. */
async function sourceEnvironment(
  request: APIRequestContext,
  api: string,
  headers: Record<string, string>,
): Promise<Environment | string> {
  const listed = await request.get(`${api}/api/market/environments?type=historical_replay`, { headers })
  expect(listed.status(), 'the market service lists its environments').toBe(200)
  const all = (await listed.json()) as Environment[]
  const chosen = process.env.QS_E2E_REPLAY_ENV_ID?.trim()
  const candidates = chosen ? all.filter((e) => e.id === chosen) : all.filter((e) => e.status !== 'draft')
  for (const environment of candidates) {
    if ((await request.get(`${api}/api/market/environments/${environment.id}/ticks?limit=1`, { headers })).ok()) {
      return environment
    }
  }
  return `the market service has no ready replay environment that serves its ticks (${candidates.length} candidates)`
}

test('replay, calibrate, simulate and stress on a real environment, and the refusals', async ({ page, request }) => {
  const { username, password } = credentials()
  const api = await apiBase(request)
  const headers = { Authorization: `Bearer ${await tokenFor(request, api, username, password)}` }

  const scenarios = await request.get(`${api}/api/simulation/scenarios`, { headers })
  test.skip(!scenarios.ok(), `the simulation service is not deployed on this environment (${scenarios.status()})`)
  const flash = ((await scenarios.json()) as { code: string }[]).find((s) => s.code === 'flash_crash')
  test.skip(!flash, 'the flash_crash scenario is not seeded on this environment')

  const source = await sourceEnvironment(request, api, headers)
  test.skip(typeof source === 'string', typeof source === 'string' ? source : '')
  if (typeof source === 'string') return

  const watch = watchPage(page)
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  const main = page.getByRole('main')
  let runId = ''
  let stressedId = ''

  await test.step('a fresh environment over the same instruments and window', async () => {
    const created = await request.post(`${api}/api/market/environments`, {
      headers,
      data: {
        name: `E2E spine ${stamp}`,
        type: 'historical_replay',
        universe: source.universe,
        instrument_ids: source.instrument_ids,
        start_date: source.start_date,
        end_date: source.end_date,
        frequency: 'daily',
      },
    })
    expect(created.status(), await created.text()).toBe(201)
  })

  await test.step('1: sign in', async () => {
    await signIn(page)
  })

  let positionBefore = ''
  await test.step('2: replay plays on the server clock, and a reload resumes where it was', async () => {
    await openInApp(page, '/market/replay')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('Replay')
    const toggle = main.getByTestId('replay-toggle')
    const position = main.getByTestId('replay-position')
    await expect(position).toContainText('Session 1 /')
    await toggle.click() // activates the environment, starts a session and plays
    await expect(toggle).toHaveText('Pause')
    await main.getByTestId('replay-speed-20').click()
    await expect(main.getByTestId('replay-speed-20')).toHaveAttribute('aria-pressed', 'true')
    await expect(position).not.toContainText('Session 1 /', { timeout: 30_000 }) // the position moved
    await toggle.click()
    await expect(toggle).toHaveText('Play')
    await main.getByTestId('replay-seek').focus()
    await main.getByTestId('replay-seek').press('End') // seek to the last session
    const count = /\/ (\d+)/.exec(await position.innerText())?.[1]
    await expect(position).toContainText(`Session ${count} / ${count}`)
    positionBefore = (await position.innerText()).split('·')[0].trim()
    await page.reload()
    await expect(main.getByTestId('replay-position')).toContainText(positionBefore) // the server's position
  })

  await test.step('3: Configure fits each instrument and the run is followed to the end', async () => {
    await openInApp(page, '/simulation/configure')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('Simulation Configuration')
    await main.getByRole('button', { name: /Run Simulation/ }).click()
    await expect(page).toHaveURL(/\/simulation\/run\/[0-9a-f-]{36}$/, { timeout: 3 * 60_000 })
    runId = /\/simulation\/run\/([0-9a-f-]{36})/.exec(page.url())?.[1] ?? ''
    await expect(main.getByText('Simulation Complete')).toBeVisible({ timeout: RUN_TIMEOUT_MS })
    await expect(main.getByTestId('fan-chart')).toBeVisible()
    await main.getByRole('button', { name: /View Results/ }).click()
    await expect(page).toHaveURL(new RegExp(`/simulation/results/${runId}$`))
  })

  await test.step('4: results show the risk table and the fan', async () => {
    await expect(main.getByRole('heading', { level: 1 })).toHaveText(`Simulation #${runId.slice(0, 8)}`)
    await expect(main.getByRole('table').getByRole('row')).not.toHaveCount(1) // header and at least one instrument
    await expect(main.getByTestId('fan-chart')).toBeVisible()
    const run = await (await request.get(`${api}/api/simulation/runs/${runId}`, { headers })).json()
    expect(run.status).toBe('completed')
    expect(run.median_path_index).toBeGreaterThanOrEqual(0)
    const ticks = await request.get(`${api}/api/simulation/runs/${runId}/ticks?path=${run.median_path_index}&limit=50`, { headers })
    expect(ticks.status()).toBe(200)
    const page1 = (await ticks.json()) as { items: Tick[] }
    expect(page1.items[0]).toMatchObject({ seq: 1, env_type: 'synthetic', scenario: null, path_index: run.median_path_index })
    expect(ticks.headers()['x-source-fingerprint']).toBe(page1.items[0].source_fingerprint)
  })

  await test.step('4: a flash crash is applied and shown beside the base run', async () => {
    await main.getByTestId('stress-flash_crash').click()
    await expect(page).toHaveURL(/\/simulation\/run\/[0-9a-f-]{36}$/)
    stressedId = /\/simulation\/run\/([0-9a-f-]{36})/.exec(page.url())?.[1] ?? ''
    expect(stressedId).not.toBe(runId)
    await expect(main.getByText('Simulation Complete')).toBeVisible({ timeout: RUN_TIMEOUT_MS })
    await main.getByRole('button', { name: /View Results/ }).click()
    await expect(main.getByTestId('fan-compare')).toBeVisible() // the base median drawn over the stressed fan
    await expect(main.getByText('Base median')).toBeVisible()
    const stressed = await (await request.get(`${api}/api/simulation/runs/${stressedId}`, { headers })).json()
    expect(stressed).toMatchObject({ parent_run_id: runId, scenario: 'flash_crash', status: 'completed' })
    const base = await (await request.get(`${api}/api/simulation/runs/${runId}`, { headers })).json()
    expect(base.parent_run_id).toBeNull() // the base run is untouched
  })

  await test.step('8: an inverted window is refused, and so is a run on another instrument\'s calibration', async () => {
    const inverted = await request.post(`${api}/api/market/environments`, {
      headers,
      data: {
        name: `E2E inverted ${stamp}`,
        type: 'historical_replay',
        universe: source.universe,
        instrument_ids: source.instrument_ids,
        start_date: source.end_date,
        end_date: source.start_date,
        frequency: 'daily',
      },
    })
    expect(inverted.status()).toBe(422)

    const stored = await request.get(`${api}/api/simulation/calibrations?limit=2000`, { headers })
    const fits = ((await stored.json()) as { items: { id: string; calibration: { instrument_id: string; model: string } | null }[] }).items
    const gbm = fits.filter((f) => f.calibration?.model === 'gbm')
    const [one, other] = [gbm[0], gbm.find((f) => f.calibration?.instrument_id !== gbm[0]?.calibration?.instrument_id)]
    test.skip(!one || !other || !one.calibration || !other.calibration, 'fewer than two instruments have a stored fit')
    const mismatched = await request.post(`${api}/api/simulation/runs`, {
      headers,
      data: {
        model: 'gbm',
        instruments: [{ instrument_id: one!.calibration!.instrument_id, calibration_id: other!.id }],
        n_paths: 100,
        n_steps: 10,
      },
    })
    expect(mismatched.status()).toBe(422)
    expect(await mismatched.text()).toMatch(/calibration/i)
  })

  expect(watch.take(), 'no uncaught error and no 5xx while the pages were used').toEqual([])
})
