// Trading flow on DEV (A18): through the real pages and the real Trading API, a quant's
// path from a new strategy to a replayed backtest. It creates a uniquely named buy and
// hold strategy, a portfolio on the bundled demo environment (DEV sets
// QS_TRADING_DEMO_ENVIRONMENTS=bundled), runs the backtest, waits for it to succeed and
// plays the trade log at 20x. Every name carries a run stamp, so repeated deploys never
// collide with what earlier runs left behind.

import { expect, test } from '@playwright/test'
import { credentials, openInApp, signIn, watchPage } from './support'

/** The demo environment shipped with the Trading service: two symbols, ten sessions. */
const DEMO_ENVIRONMENT = '5d0c6c1e-7a14-4a14-8a14-000000000001'
/** How long the backtest may take, queueing included. */
const RUN_TIMEOUT_MS = 90_000

test('a strategy becomes a portfolio whose backtest replays', async ({ page }) => {
  credentials()
  const watch = watchPage(page)
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  const strategyName = `E2E buy and hold ${stamp}`
  const portfolioName = `E2E portfolio ${stamp}`
  const main = page.getByRole('main')

  await test.step('sign in', async () => {
    await signIn(page)
  })

  await test.step('create a buy and hold strategy', async () => {
    await openInApp(page, '/trading/strategies/new')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('New Strategy')
    await main.getByTestId('strategy-name').fill(strategyName)
    await main.getByTestId('strategy-kind').selectOption('buy_and_hold')
    await main.getByRole('button', { name: 'Create Strategy' }).click()
    await expect(page).toHaveURL(/\/trading\/strategies$/)
    await expect(main.getByTestId('strategy-card').filter({ hasText: strategyName })).toHaveCount(1)
  })

  await test.step('create a portfolio on the demo environment', async () => {
    await openInApp(page, '/trading/portfolios/new')
    await expect(main.getByRole('heading', { level: 1 })).toHaveText('Create Portfolio')
    const strategy = main.getByTestId('portfolio-strategy')
    await expect(strategy.locator('option', { hasText: strategyName })).toHaveCount(1)
    await strategy.selectOption({ label: strategyName })
    await main.getByTestId('portfolio-name').fill(portfolioName)
    const environment = main.getByTestId('portfolio-environment')
    await expect(
      environment.locator(`option[value="replay:${DEMO_ENVIRONMENT}"]`),
      'the demo environment is listed (is QS_TRADING_DEMO_ENVIRONMENTS set on DEV?)',
    ).toHaveCount(1)
    await environment.selectOption(`replay:${DEMO_ENVIRONMENT}`)
    await main.getByRole('button', { name: 'Create Portfolio' }).click()
    await expect(main.getByRole('button', { name: 'Run backtest' })).toBeVisible()
  })

  await test.step('run the backtest until it succeeds', async () => {
    await main.getByRole('button', { name: 'Run backtest' }).click()
    const status = main.getByTestId('run-status')
    await expect(status).toHaveAttribute('data-status', /^(succeeded|failed)$/, { timeout: RUN_TIMEOUT_MS })
    if ((await status.getAttribute('data-status')) === 'failed') {
      throw new Error(`the backtest failed: ${await main.getByTestId('run-status').locator('..').innerText()}`)
    }
  })

  await test.step('replay the trade log at 20x', async () => {
    await main.getByRole('button', { name: 'Open Trade Replay' }).click()
    await expect(page).toHaveURL(/\/trading\/replay\/[0-9a-f-]{36}$/)
    await expect(main.getByRole('heading', { level: 1 })).toHaveText(`Trade Replay — ${portfolioName}`)
    const play = main.getByTestId('replay-play')
    await expect(play).toBeEnabled()
    await main.getByTestId('replay-speed-20').click()
    await expect(main.getByTestId('replay-speed-20')).toHaveAttribute('aria-pressed', 'true')
    await play.click()
    await expect(main.getByTestId('replay-status')).toHaveAttribute('data-status', 'Complete', { timeout: 60_000 })

    const rows = main.getByTestId('replay-events').locator('tbody tr')
    await expect(rows.first()).toContainText('RUN_STARTED')
    await expect(rows.last()).toContainText('RUN_COMPLETED')
    await expect(rows.filter({ hasText: 'ORDER_FILLED' }).first()).toBeVisible()
    const fills = Number(await main.getByTestId('replay-fills').innerText())
    expect(fills, 'fills replayed').toBeGreaterThanOrEqual(1)
  })

  await watch.settled()
  await expect(main.getByRole('alert')).toHaveCount(0)
  const problems = watch.take()
  if (problems.length > 0) throw new Error(problems.join('\n'))
})
