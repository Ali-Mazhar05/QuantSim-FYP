// Lane A demo spine on DEV (I2-62, steps 5-8 of the Final-I demo): a momentum portfolio with
// the demo's execution assumptions ($1,000,000, $1 fixed + 5 bps per fill, 10 bps slippage)
// runs on the bundled demo environment; the trade log replays; every fill carries exactly
// that cost and slippage; the log verifies as one hash chain; a rebuild from the log is
// identical to the live projections; a second run recomputes the log and ends on the same
// final hash; and an analyst may not create a portfolio.
//
// The pages are driven like a quant would drive them. The checks a page does not show
// (fills to the cent, verify, rebuild, rerun, the analyst's 403) go straight to the
// Trading API with a token from the platform's sign-in, against the API address the
// deploy published in /config.json.
//
// The same spine runs on TEST (e2e/demo-spine) once Lane B's market feeds serve real
// replay environments there; demo environments exist only in local and DEV.

import { expect, test, type APIRequestContext } from '@playwright/test'
import { credentials, openInApp, signIn, watchPage } from './support'

/** The demo environment shipped with the Trading service: two symbols, ten sessions. */
const DEMO_ENVIRONMENT = '5d0c6c1e-7a14-4a14-8a14-000000000001'
const RUN_TIMEOUT_MS = 90_000
const FIXED_COST = '1'
const PCT_COST = '0.0005'
const SLIPPAGE_BPS = '10'

interface Fill {
  side: 'buy' | 'sell'
  quantity: number
  reference_price: string
  fill_price: string
  slippage: string
  cost_fixed: string
  cost_per_share: string
  cost_percentage: string
}

/** The public API address this deploy published. */
async function apiBase(request: APIRequestContext): Promise<string> {
  const response = await request.get('/config.json')
  expect(response.ok(), '/config.json is served').toBeTruthy()
  const body = (await response.json()) as { apiBaseUrl?: string }
  expect(body.apiBaseUrl, '/config.json names the API').toBeTruthy()
  return String(body.apiBaseUrl).replace(/\/$/, '')
}

/** An access token for `username`, from the platform's sign-in. */
async function tokenFor(request: APIRequestContext, api: string, username: string, password: string): Promise<string> {
  const response = await request.post(`${api}/api/platform/auth/login`, { data: { username, password } })
  expect(response.status(), `sign-in as ${username}`).toBe(200)
  return ((await response.json()) as { access_token: string }).access_token
}

/** Polls a run until it has succeeded (or fails the test with the run's error). */
async function waitForRun(
  request: APIRequestContext,
  url: string,
  headers: Record<string, string>,
): Promise<{ final_seq: number; final_hash: string; resumed_at_session: number }> {
  let run: { status: string; error: string | null; result: Record<string, unknown> | null } | undefined
  await expect
    .poll(
      async () => {
        const response = await request.get(url, { headers })
        run = await response.json()
        return run?.status
      },
      { timeout: RUN_TIMEOUT_MS, intervals: [1_000, 2_000, 3_000] },
    )
    .toMatch(/^(succeeded|failed)$/)
  if (run?.status !== 'succeeded') throw new Error(`the run failed: ${run?.error}`)
  return run.result as { final_seq: number; final_hash: string; resumed_at_session: number }
}

test('a momentum portfolio runs with costs and slippage, rebuilds identical and reruns to the same hash', async ({
  page,
  request,
}) => {
  const { username, password } = credentials()
  const watch = watchPage(page)
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  const strategyName = `E2E momentum ${stamp}`
  const portfolioName = `E2E spine ${stamp}`
  const main = page.getByRole('main')
  let portfolioId = ''

  await test.step('sign in', async () => {
    await signIn(page)
  })

  await test.step('configure a momentum strategy', async () => {
    await openInApp(page, '/trading/strategies/new')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('New Strategy')
    await main.getByTestId('strategy-name').fill(strategyName)
    await main.getByTestId('strategy-kind').selectOption('momentum')
    // Ten demo sessions: a two-session lookback, the best symbol, rebalanced daily
    await main.getByLabel('Lookback (sessions)').fill('2')
    await main.getByLabel('Symbols Held (top N)').fill('1')
    await main.getByLabel('Rebalance Frequency').selectOption({ label: 'Daily' })
    await main.getByRole('button', { name: 'Create Strategy' }).click()
    await expect(page).toHaveURL(/\/trading\/strategies$/)
    await expect(main.getByTestId('strategy-card').filter({ hasText: strategyName })).toHaveCount(1)
  })

  await test.step('create the portfolio with the demo execution assumptions', async () => {
    await openInApp(page, '/trading/portfolios/new')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('Create Portfolio')
    const strategy = main.getByTestId('portfolio-strategy')
    await expect(strategy.locator('option', { hasText: strategyName })).toHaveCount(1)
    await strategy.selectOption({ label: strategyName })
    await main.getByTestId('portfolio-name').fill(portfolioName)
    await main.getByTestId('portfolio-capital').fill('1000000')
    await main.getByTestId('portfolio-environment').selectOption(`replay:${DEMO_ENVIRONMENT}`)
    await main.getByLabel('Fixed per Fill (USD)').fill(FIXED_COST)
    await main.getByLabel('Per Share (USD)').fill('0')
    await main.getByLabel(/^Of Notional/).fill(PCT_COST)
    // The slippage model stays on its default, fixed basis points. A label's text includes
    // the options of a select it wraps ("Fixed basis points"), so match this one exactly
    await main.getByLabel('Basis Points', { exact: true }).fill(SLIPPAGE_BPS)
    await main.getByRole('button', { name: 'Create Portfolio' }).click()
    await expect(main.getByRole('button', { name: 'Run backtest' })).toBeVisible()
  })

  await test.step('run the backtest until it succeeds', async () => {
    await main.getByRole('button', { name: 'Run backtest' }).click()
    const status = main.getByTestId('run-status')
    await expect(status).toHaveAttribute('data-status', /^(succeeded|failed)$/, { timeout: RUN_TIMEOUT_MS })
    if ((await status.getAttribute('data-status')) === 'failed') {
      throw new Error(`the backtest failed: ${await status.locator('..').innerText()}`)
    }
  })

  await test.step('Trade Replay shows ticks, orders and fills', async () => {
    await main.getByRole('button', { name: 'Open Trade Replay' }).click()
    await expect(page).toHaveURL(/\/trading\/replay\/[0-9a-f-]{36}$/)
    portfolioId = page.url().split('/').pop() ?? ''
    await main.getByTestId('replay-speed-20').click()
    await main.getByTestId('replay-play').click()
    await expect(main.getByTestId('replay-status')).toHaveAttribute('data-status', 'Complete', { timeout: 60_000 })
    const rows = main.getByTestId('replay-events').locator('tbody tr')
    for (const type of ['TICK', 'ORDER_PLACED', 'ORDER_FILLED']) {
      await expect(rows.filter({ hasText: type }).first(), `${type} is replayed`).toBeVisible()
    }
    await expect(main.getByTestId('replay-value')).not.toBeEmpty()
  })

  const api = await apiBase(request)
  const token = await tokenFor(request, api, username, password)
  const auth = { Authorization: `Bearer ${token}` }
  const portfolio = `${api}/api/trading/portfolios/${portfolioId}`

  await test.step('every fill carries $1 + 5 bps of notional and 10 bps of slippage', async () => {
    const response = await request.get(`${portfolio}/fills?limit=500`, { headers: auth })
    expect(response.status()).toBe(200)
    const fills = ((await response.json()) as { items: Fill[] }).items
    expect(fills.length, 'the momentum run filled at least one order').toBeGreaterThanOrEqual(1)
    for (const fill of fills) {
      const reference = Number(fill.reference_price)
      const price = Number(fill.fill_price)
      // Slippage moves the price against the trader by exactly 10 bps of the reference
      expect(Number(fill.slippage)).toBeCloseTo(reference * 0.001, 6)
      expect(price).toBeCloseTo(fill.side === 'buy' ? reference * 1.001 : reference * 0.999, 6)
      expect(Number(fill.cost_fixed)).toBe(1)
      expect(Number(fill.cost_per_share)).toBe(0)
      // 5 bps of the notional at the fill price, in cents
      expect(Math.abs(Number(fill.cost_percentage) - price * fill.quantity * 0.0005)).toBeLessThanOrEqual(0.005)
    }
  })

  let finalHash = ''
  await test.step('the log is one intact hash chain', async () => {
    const response = await request.get(`${portfolio}/verify`, { headers: auth })
    expect(response.status()).toBe(200)
    const chain = (await response.json()) as { valid: boolean; events: number; last_seq: number; last_hash: string | null }
    expect(chain.valid, 'the hash chain verifies').toBe(true)
    expect(chain.last_seq, 'seq has no gaps').toBe(chain.events)
    finalHash = String(chain.last_hash)
  })

  await test.step('a rebuild from the log is identical to the live projections', async () => {
    const response = await request.post(`${portfolio}/rebuild`, { headers: auth })
    expect(response.status()).toBe(200)
    const rebuild = (await response.json()) as { status: string; final_hash: string | null; differences: unknown[] }
    expect(rebuild.differences).toEqual([])
    expect(rebuild.status).toBe('identical')
    expect(rebuild.final_hash).toBe(finalHash)
  })

  await test.step('a second run recomputes the log and ends on the same final hash', async () => {
    const response = await request.post(`${portfolio}/runs`, {
      headers: { ...auth, 'Idempotency-Key': `e2e-rerun-${stamp}` },
    })
    expect(response.status()).toBe(202)
    const accepted = (await response.json()) as { job_id: string }
    const result = await waitForRun(request, `${portfolio}/runs/${accepted.job_id}`, auth)
    expect(result.final_hash, 'same spec on the same fingerprint gives the same hash').toBe(finalHash)
  })

  await test.step('an analyst may not create a portfolio', async () => {
    const analyst = await tokenFor(request, api, 'test.analyst', password)
    const current = (await (await request.get(portfolio, { headers: auth })).json()) as Record<string, unknown>
    const response = await request.post(`${api}/api/trading/portfolios`, {
      headers: { Authorization: `Bearer ${analyst}` },
      data: {
        name: `E2E analyst ${stamp}`,
        strategy_id: current.strategy_id,
        initial_capital: '1000000',
        replay_environment_id: DEMO_ENVIRONMENT,
      },
    })
    expect(response.status()).toBe(403)
  })

  await watch.settled()
  const problems = watch.take()
  if (problems.length > 0) throw new Error(problems.join('\n'))
})
