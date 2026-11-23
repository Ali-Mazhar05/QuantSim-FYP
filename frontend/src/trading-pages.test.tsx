import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDemoStore } from './demo/demoState'
import QueryProvider from './hooks/QueryProvider'
import ConfigureStrategy from './pages/trading/ConfigureStrategy'
import CreatePortfolio from './pages/trading/CreatePortfolio'
import Portfolios from './pages/trading/Portfolios'
import Strategies from './pages/trading/Strategies'
import TradeReplay from './pages/trading/TradeReplay'
import { BASE_STEP_MS } from './pages/trading/tradingApi'
import { clearSession } from './services/api/client'
import { account } from './test/fakeBackend'
import LocationProbe from './test/LocationProbe'

// ---- A fake Trading (and market) API ----

function json(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function problem(status: number, detail: string, extra: Record<string, unknown> = {}): Response {
  return json(status, { type: 'urn:quantsim:problem:x', title: 'Problem', status, detail, ...extra })
}

interface Call {
  method: string
  path: string
  query: URLSearchParams
  body: Record<string, unknown> | undefined
  headers: Headers
}

type Handler = (call: Call) => Response | Promise<Response>

const S1 = '11111111-1111-4111-8111-111111111111'
const P1 = '22222222-2222-4222-8222-222222222222'
const P2 = '33333333-3333-4333-8333-333333333333'
const JOB = '44444444-4444-4444-8444-444444444444'
const ENV = '55555555-5555-4555-8555-555555555555'
const DEMO = '5d0c6c1e-7a14-4a14-8a14-000000000001'
const OWNER = '66666666-6666-4666-8666-666666666666'

const MOMENTUM = {
  id: S1,
  name: 'Momentum 2',
  kind: 'momentum',
  params: { lookback: 2, top_n: 1, rebalance_every: 2, max_position: '0.9', cash_buffer: '0.02' },
  owner_id: OWNER,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

const PORTFOLIO = {
  id: P1,
  name: 'Replay portfolio',
  strategy_id: S1,
  strategy_name: 'Momentum 2',
  strategy_kind: 'momentum',
  owner_id: OWNER,
  initial_capital: '10000.00',
  base_currency: 'USD',
  cost_model: { fixed: '1.00', per_share: '0', pct: '0' },
  slippage_model: { kind: 'fixed_bps', bps: '5' },
  env_type: 'replay',
  replay_environment_id: DEMO,
  simulation_run_id: null,
  path_index: null,
  source_fingerprint: 'fixture',
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}
const NOT_RUN = { ...PORTFOLIO, id: P2, name: 'Fresh portfolio', source_fingerprint: null, replay_environment_id: ENV }

const MARKET_ENV = {
  id: ENV,
  name: 'Tech 2024',
  type: 'historical_replay',
  universe: 'Tech',
  instrument_ids: [],
  symbols: ['AAPL'],
  start_date: '2024-01-02',
  end_date: '2024-12-31',
  frequency: 'daily',
  status: 'ready',
  created_by: 'q',
  created_at: '2026-11-01T00:00:00Z',
}
const DEMO_ENV = { id: DEMO, name: 'A14 two-symbol fixture', env_type: 'replay', sessions: 10, start_date: '2026-01-05', end_date: '2026-01-16' }

function event(seq: number, type: string, payload: Record<string, unknown> = {}) {
  return { seq, type, version: 1, event_time: `2026-01-0${5 + Math.floor(seq / 3)}T21:00:00Z`, payload, prev_hash: null, hash: `h${seq}` }
}

const LOG = [
  event(1, 'RUN_STARTED', { strategy_kind: 'momentum' }),
  event(2, 'TICK', { session: 0, ts: '2026-01-05T21:00:00Z' }),
  event(3, 'ORDER_PLACED', { order_id: 'o1', session: 0, symbol: 'AAA', side: 'buy', quantity: 90, order_type: 'market' }),
  event(4, 'TICK', { session: 1, ts: '2026-01-06T21:00:00Z' }),
  event(5, 'ORDER_FILLED', {
    order_id: 'o1',
    session: 1,
    symbol: 'AAA',
    side: 'buy',
    quantity: 90,
    reference_price: '100.00',
    fill_price: '100.05',
    slippage: '0.05',
    cost_total: '1.00',
  }),
  event(6, 'VALUED', { session: 1, portfolio_value: '10044.50' }),
  event(7, 'RUN_COMPLETED', { sessions: 2, final_value: '10044.50' }),
]

const VALUES = [
  { session: 1, ts: '2026-01-06T21:00:00Z', seq: 6, cash: '994.50', market_value: '9050.00', value: '10044.50', realised_pnl: '0', unrealised_pnl: '44.50', total_costs: '1.00' },
]

const METRICS = {
  portfolio_id: P1,
  final_seq: 7,
  final_hash: 'h7',
  sessions: 2,
  initial_capital: '10000.00',
  final_value: '10044.50',
  trades: 1,
  total_costs: '1.00',
  total_return: null,
  volatility: null,
  sharpe: null,
  max_drawdown: null,
  turnover: null,
  pending: [],
}

function eventsPage(call: Call): Response {
  const after = Number(call.query.get('after_seq') ?? '0')
  const limit = Number(call.query.get('limit') ?? '500')
  const items = LOG.filter((e) => e.seq > after).slice(0, limit)
  const last = items[items.length - 1]
  return json(200, { items, next_cursor: last && last.seq < LOG.length ? last.seq : null })
}

const DEFAULTS: Record<string, Handler> = {
  'GET /strategies': () => json(200, [MOMENTUM]),
  [`GET /strategies/${S1}`]: () => json(200, MOMENTUM),
  'GET /portfolios': () => json(200, [PORTFOLIO, NOT_RUN]),
  [`GET /portfolios/${P1}`]: () => json(200, PORTFOLIO),
  [`GET /portfolios/${P1}/metrics`]: () => json(200, METRICS),
  [`GET /portfolios/${P1}/events`]: eventsPage,
  [`GET /portfolios/${P1}/value-series`]: () => json(200, VALUES),
  'GET /demo-environments': () => json(200, [DEMO_ENV]),
  'GET /api/market/environments': () => json(200, [MARKET_ENV]),
  'GET /api/simulation/runs': () => json(200, { items: [], next_cursor: null }),
}

/** Every request is recorded; a route not given answers from DEFAULTS, else 404. */
function tradingBackend(routes: Record<string, Handler> = {}) {
  const calls: Call[] = []
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input)
    const method = init?.method ?? 'GET'
    const path = url.pathname.replace(/^\/api\/trading/, '')
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined
    const call = { method, path, query: url.searchParams, body, headers: new Headers(init?.headers) }
    calls.push(call)
    const handler = routes[`${method} ${path}`] ?? DEFAULTS[`${method} ${path}`]
    return handler ? handler(call) : json(404, { detail: 'Not found' })
  })
  vi.stubGlobal('fetch', fetch)
  return { calls }
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryProvider>
      <Routes>
        <Route path="/trading/strategies" element={<Strategies />} />
        <Route path="/trading/strategies/new" element={<ConfigureStrategy />} />
        <Route path="/trading/strategies/:id" element={<ConfigureStrategy />} />
        <Route path="/trading/portfolios" element={<Portfolios />} />
        <Route path="/trading/portfolios/new" element={<CreatePortfolio />} />
        <Route path="/trading/replay/:id" element={<TradeReplay />} />
        <Route path="*" element={null} />
      </Routes>
      <LocationProbe />
      <GoTo />
      </QueryProvider>
    </MemoryRouter>,
  )
}

/** Navigates inside the running app to the path typed into it, as the app's links do. */
function GoTo() {
  const navigate = useNavigate()
  return <input aria-label="go to" onKeyDown={(e) => e.key === 'Enter' && navigate(e.currentTarget.value)} />
}

function goTo(path: string) {
  const input = screen.getByLabelText('go to')
  fireEvent.change(input, { target: { value: path } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

const never = () => new Promise<Response>(() => undefined)

beforeEach(() => {
  clearSession()
  window.localStorage.clear()
  useDemoStore.getState().startSession(account('Quant'))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  useDemoStore.getState().logout()
})

// ---- Strategies ----

describe('the Strategies page', () => {
  it('lists the strategies from the API with their rules', async () => {
    tradingBackend()
    renderAt('/trading/strategies')
    expect(screen.getByText('Loading strategies…')).toBeInTheDocument()
    const card = await screen.findByTestId('strategy-card')
    expect(within(card).getByText('Momentum 2')).toBeInTheDocument()
    expect(within(card).getByText(/Rebalance: every 2 sessions · Max position: 90%/)).toBeInTheDocument()
    expect(within(card).getByText('Ranks symbols by their 2-session return and holds the top 1.')).toBeInTheDocument()
    fireEvent.click(within(card).getByRole('button', { name: 'Configure' }))
    expect(screen.getByTestId('location')).toHaveTextContent(`/trading/strategies/${S1}`)
  })

  it('shows the empty, error and 403 states', async () => {
    tradingBackend({ 'GET /strategies': () => json(200, []) })
    const first = renderAt('/trading/strategies')
    expect(await screen.findByText('No strategies yet')).toBeInTheDocument()
    first.unmount()

    tradingBackend({ 'GET /strategies': () => problem(500, 'The trading database is unavailable.') })
    const second = renderAt('/trading/strategies')
    expect(await screen.findByRole('alert')).toHaveTextContent('The trading database is unavailable.')
    second.unmount()

    tradingBackend({ 'GET /strategies': () => problem(403, 'Your role may not do this.') })
    renderAt('/trading/strategies')
    expect(await screen.findByTestId('forbidden')).toHaveTextContent('Your role may not do this.')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('disables New Strategy and Configure for a role without create_strategies', async () => {
    useDemoStore.getState().startSession(account('Analyst'))
    tradingBackend()
    renderAt('/trading/strategies')
    const card = await screen.findByTestId('strategy-card')
    expect(within(card).getByRole('button', { name: 'Configure' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'New Strategy' })).toBeDisabled()
  })
})

// ---- Configure Strategy ----

describe('the Configure Strategy page', () => {
  it('creates a strategy with whole numbers as numbers and fractions as strings', async () => {
    const { calls } = tradingBackend({ 'POST /strategies': (c) => json(201, { ...MOMENTUM, ...c.body }) })
    renderAt('/trading/strategies/new')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('New Strategy')
    fireEvent.change(screen.getByTestId('strategy-name'), { target: { value: 'Rotation' } })
    fireEvent.change(screen.getByTestId('param-lookback'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('Rebalance Frequency'), { target: { value: '21' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Strategy' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/trading\/strategies$/))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.body).toEqual({
      name: 'Rotation',
      kind: 'momentum',
      params: { cash_buffer: '0.02', lookback: 30, top_n: 3, rebalance_every: 21, max_position: '0.25' },
    })
  })

  it('sends buy and hold weights from the rule rows', async () => {
    const { calls } = tradingBackend({ 'POST /strategies': (c) => json(201, { ...MOMENTUM, ...c.body }) })
    renderAt('/trading/strategies/new')
    fireEvent.change(screen.getByTestId('strategy-name'), { target: { value: 'Hold' } })
    fireEvent.change(screen.getByTestId('strategy-kind'), { target: { value: 'buy_and_hold' } })
    expect(screen.queryByLabelText('Rebalance Frequency')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Add Rule' }))
    fireEvent.change(screen.getByLabelText('Symbol 1'), { target: { value: 'AAA' } })
    fireEvent.change(screen.getByLabelText('Weight 1'), { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Strategy' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      name: 'Hold',
      kind: 'buy_and_hold',
      params: { cash_buffer: '0.02', weights: { AAA: '0.5' } },
    })
  })

  it('shows a 422 next to the field it names', async () => {
    tradingBackend({
      'POST /strategies': () =>
        problem(422, 'params.lookback: Input should be greater than or equal to 1', {
          errors: [{ location: ['body', 'params', 'lookback'], message: 'Input should be greater than or equal to 1', type: 'greater_than_equal' }],
        }),
    })
    renderAt('/trading/strategies/new')
    fireEvent.change(screen.getByTestId('strategy-name'), { target: { value: 'Bad' } })
    fireEvent.change(screen.getByTestId('param-lookback'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Strategy' }))
    expect(await screen.findByTestId('field-error-lookback')).toHaveTextContent('Input should be greater than or equal to 1')
    expect(screen.getByRole('alert')).toHaveTextContent('Check lookback')
    expect(screen.getByTestId('location')).toHaveTextContent('/trading/strategies/new')
  })

  it('loads an existing strategy and says why a change is refused (409, 403)', async () => {
    const { calls } = tradingBackend({
      [`PUT /strategies/${S1}`]: () => problem(409, 'A portfolio on this strategy has already run; create a new strategy instead.'),
    })
    renderAt(`/trading/strategies/${S1}`)
    expect(screen.getByText('Loading the strategy…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Configure — Momentum 2' })).toBeInTheDocument()
    expect(screen.getByTestId('param-lookback')).toHaveValue('2')
    expect(screen.getByLabelText('Rebalance Frequency')).toHaveValue('2')
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already run')
    expect(calls.find((c) => c.method === 'PUT')!.body).toMatchObject({ name: 'Momentum 2', kind: 'momentum' })
  })

  it('shows the 403 state when the strategy cannot be read, and a not-found page for an unknown id', async () => {
    tradingBackend({ [`GET /strategies/${S1}`]: () => problem(403, 'Not for your role.') })
    const first = renderAt(`/trading/strategies/${S1}`)
    expect(await screen.findByTestId('forbidden')).toHaveTextContent('Not for your role.')
    first.unmount()

    const { calls } = tradingBackend()
    renderAt('/trading/strategies/strat-momentum-1')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Strategy not found')
    expect(calls).toHaveLength(0)
  })

  it('starts a fresh form when the app moves to another strategy', async () => {
    tradingBackend()
    renderAt('/trading/strategies/new')
    fireEvent.change(screen.getByTestId('strategy-name'), { target: { value: 'Half typed' } })
    goTo('/trading/strategies/strat-momentum-1')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Strategy not found')
    goTo(`/trading/strategies/${S1}`)
    expect(await screen.findByRole('heading', { level: 1, name: 'Configure — Momentum 2' })).toBeInTheDocument()
    expect(screen.getByTestId('strategy-name')).toHaveValue('Momentum 2')
    goTo('/trading/strategies/new')
    expect(screen.getByTestId('strategy-name')).toHaveValue('')
  })
})

// ---- Portfolios ----

describe('the Portfolios page', () => {
  it('lists portfolios with their environment and last run status', async () => {
    tradingBackend()
    renderAt('/trading/portfolios')
    expect(screen.getByText('Loading portfolios…')).toBeInTheDocument()
    const ran = (await screen.findByText('Replay portfolio')).closest('tr') as HTMLElement
    await waitFor(() => expect(within(ran).getByText('Succeeded')).toBeInTheDocument())
    expect(within(ran).getByText('A14 two-symbol fixture')).toBeInTheDocument()
    expect(within(ran).getByText('$10,045')).toBeInTheDocument()
    expect(within(ran).getByText('+0.45%')).toBeInTheDocument()
    const fresh = screen.getByText('Fresh portfolio').closest('tr') as HTMLElement
    await waitFor(() => expect(within(fresh).getByText('Not run')).toBeInTheDocument())
    expect(within(fresh).getByText('Tech 2024')).toBeInTheDocument()
    fireEvent.click(ran)
    expect(screen.getByTestId('location')).toHaveTextContent(`/trading/replay/${P1}`)
  })

  it('shows a run started from this browser by its job status', async () => {
    window.localStorage.setItem('qs.trading.runs', JSON.stringify({ [P1]: JOB }))
    tradingBackend({ [`GET /portfolios/${P1}/runs/${JOB}`]: () => json(200, { job_id: JOB, portfolio_id: P1, status: 'running', progress: 0.5 }) })
    renderAt('/trading/portfolios')
    const row = (await screen.findByText('Replay portfolio')).closest('tr') as HTMLElement
    await waitFor(() => expect(within(row).getByText('Running')).toBeInTheDocument())
  })

  it('shows the empty, error and 403 states', async () => {
    tradingBackend({ 'GET /portfolios': () => json(200, []) })
    const first = renderAt('/trading/portfolios')
    expect(await screen.findByText('No portfolios yet')).toBeInTheDocument()
    first.unmount()

    tradingBackend({ 'GET /portfolios': () => problem(503, 'Trading is down.') })
    const second = renderAt('/trading/portfolios')
    expect(await screen.findByRole('alert')).toHaveTextContent('Trading is down.')
    second.unmount()

    tradingBackend({ 'GET /portfolios': () => problem(403, 'Refused.') })
    renderAt('/trading/portfolios')
    expect(await screen.findByTestId('forbidden')).toBeInTheDocument()
  })
})

// ---- Create Portfolio ----

describe('the Create Portfolio page', () => {
  it('offers market, demo and simulation environments', async () => {
    tradingBackend()
    renderAt('/trading/portfolios/new')
    expect(screen.getByText('Loading strategies and environments…')).toBeInTheDocument()
    const picker = await screen.findByTestId('portfolio-environment')
    const groups = Array.from(picker.querySelectorAll('optgroup')).map((g) => g.label)
    expect(groups).toEqual(['Market replay environments', 'Demo environments', 'Simulation runs'])
    expect(within(picker).getByRole('option', { name: 'Tech 2024 (2024-01-02 – 2024-12-31)' })).toHaveValue(`replay:${ENV}`)
    expect(within(picker).getByRole('option', { name: 'A14 two-symbol fixture (10 sessions)' })).toHaveValue(`replay:${DEMO}`)
    expect(within(picker).getByRole('option', { name: 'No completed simulation runs yet' })).toBeDisabled()
  })

  it('lists the completed simulation runs and binds a portfolio to the median path of the one chosen', async () => {
    const RUN = 'a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d'
    const { calls } = tradingBackend({
      'GET /api/simulation/runs': (c) =>
        c.query.get('status') === 'completed'
          ? json(200, {
              items: [
                {
                  id: RUN,
                  status: 'completed',
                  model: 'gbm',
                  n_paths: 1000,
                  n_steps: 252,
                  symbols: ['AAPL', 'MSFT'],
                  median_path_index: 417,
                  parent_run_id: null,
                  scenario: null,
                  created_at: '2026-11-20T10:00:00Z',
                },
              ],
              next_cursor: null,
            })
          : json(200, { items: [], next_cursor: null }),
      'POST /portfolios': () => json(201, PORTFOLIO),
    })
    renderAt('/trading/portfolios/new')
    fireEvent.change(await screen.findByTestId('portfolio-name'), { target: { value: 'On a run' } })
    const picker = screen.getByTestId('portfolio-environment')
    const option = await within(picker).findByRole('option', { name: '#a4d3c2b1 · AAPL, MSFT · 1,000 paths' })
    expect(option).toHaveValue(`simulation:${RUN}`)
    fireEvent.change(picker, { target: { value: `simulation:${RUN}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Portfolio' }))
    await screen.findByRole('button', { name: 'Run backtest' })
    const body = calls.find((c) => c.method === 'POST' && c.path === '/portfolios')!.body
    expect(body).toMatchObject({ simulation_run_id: RUN, path_index: 417 })
    expect(body).not.toHaveProperty('replay_environment_id')
  })

  it('chooses the run it was opened for from the results page', async () => {
    const RUN = 'a4d3c2b1-7e6f-4a5b-8c9d-0e1f2a3b4c5d'
    tradingBackend({
      'GET /api/simulation/runs': () =>
        json(200, {
          items: [
            {
              id: RUN,
              status: 'completed',
              model: 'gbm',
              n_paths: 50,
              n_steps: 10,
              symbols: ['AAPL'],
              median_path_index: 3,
              parent_run_id: null,
              scenario: 'flash_crash',
              created_at: '2026-11-20T10:00:00Z',
            },
          ],
          next_cursor: null,
        }),
    })
    renderAt(`/trading/portfolios/new?run=${RUN}`)
    const picker = await screen.findByTestId('portfolio-environment')
    await waitFor(() => expect(picker).toHaveValue(`simulation:${RUN}`))
  })

  it('creates the portfolio, starts the backtest and polls it until it succeeds', async () => {
    let polls = 0
    const { calls } = tradingBackend({
      'POST /portfolios': (c) => json(201, { ...PORTFOLIO, name: c.body?.name }),
      [`POST /portfolios/${P1}/runs`]: () => json(202, { job_id: JOB, portfolio_id: P1, status: 'queued', created: true }),
      [`GET /portfolios/${P1}/runs/${JOB}`]: () => {
        polls += 1
        return json(200, { job_id: JOB, portfolio_id: P1, status: polls < 2 ? 'running' : 'succeeded', progress: polls < 2 ? 0.5 : 1, error: null })
      },
    })
    renderAt('/trading/portfolios/new')
    fireEvent.change(await screen.findByTestId('portfolio-name'), { target: { value: 'Demo run' } })
    fireEvent.change(screen.getByTestId('portfolio-environment'), { target: { value: `replay:${DEMO}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Portfolio' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Run backtest' }))

    expect(calls.find((c) => c.method === 'POST' && c.path === '/portfolios')!.body).toEqual({
      name: 'Demo run',
      strategy_id: S1,
      initial_capital: '1000000',
      cost_model: { fixed: '0', per_share: '0', pct: '0.0005' },
      slippage_model: { kind: 'fixed_bps', bps: '2' },
      replay_environment_id: DEMO,
    })
    // Each click sends its own key, so a retry of that click can't start a second run
    const submit = await waitFor(() => calls.find((c) => c.method === 'POST' && c.path === `/portfolios/${P1}/runs`)!)
    expect(submit.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
    await waitFor(() => expect(screen.getByTestId('run-status')).toHaveAttribute('data-status', 'running'))
    expect(screen.getByTestId('run-status')).toHaveTextContent('Running · 50%')
    await waitFor(() => expect(screen.getByTestId('run-status')).toHaveAttribute('data-status', 'succeeded'), { timeout: 5000 })
    expect(polls).toBe(2)
    expect(JSON.parse(window.localStorage.getItem('qs.trading.runs')!)).toEqual({ [P1]: JOB })
    fireEvent.click(screen.getByRole('button', { name: 'Open Trade Replay' }))
    expect(screen.getByTestId('location')).toHaveTextContent(`/trading/replay/${P1}`)
  })

  it('follows the run already in progress on a 409', async () => {
    tradingBackend({
      'POST /portfolios': () => json(201, PORTFOLIO),
      [`POST /portfolios/${P1}/runs`]: () => problem(409, 'Run in progress', { job_id: JOB }),
      [`GET /portfolios/${P1}/runs/${JOB}`]: () => json(200, { job_id: JOB, portfolio_id: P1, status: 'failed', progress: 0.2, error: 'FixtureError: bad tick' }),
    })
    renderAt('/trading/portfolios/new')
    fireEvent.change(await screen.findByTestId('portfolio-name'), { target: { value: 'Again' } })
    fireEvent.change(screen.getByTestId('portfolio-environment'), { target: { value: `replay:${DEMO}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Portfolio' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Run backtest' }))
    await waitFor(() => expect(screen.getByTestId('run-status')).toHaveAttribute('data-status', 'failed'), { timeout: 5000 })
    expect(screen.getByText('FixtureError: bad tick')).toBeInTheDocument()
  })

  it('shows a 422 next to the field it names', async () => {
    tradingBackend({
      'POST /portfolios': () =>
        problem(422, 'initial_capital: Input should be greater than 0', {
          errors: [{ location: ['body', 'initial_capital'], message: 'Input should be greater than 0', type: 'greater_than' }],
        }),
    })
    renderAt('/trading/portfolios/new')
    fireEvent.change(await screen.findByTestId('portfolio-name'), { target: { value: 'Zero' } })
    fireEvent.change(screen.getByTestId('portfolio-capital'), { target: { value: '0' } })
    fireEvent.change(screen.getByTestId('portfolio-environment'), { target: { value: `replay:${ENV}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Portfolio' }))
    expect(await screen.findByTestId('field-error-initial_capital')).toHaveTextContent('Input should be greater than 0')
    expect(screen.queryByRole('button', { name: 'Run backtest' })).toBeNull()
  })

  it('shows the empty, error and 403 states', async () => {
    tradingBackend({ 'GET /strategies': () => json(200, []) })
    const first = renderAt('/trading/portfolios/new')
    expect(await screen.findByText('No strategies yet')).toBeInTheDocument()
    first.unmount()

    tradingBackend({ 'GET /strategies': () => problem(500, 'Broken.') })
    const second = renderAt('/trading/portfolios/new')
    expect(await screen.findByRole('alert')).toHaveTextContent('Broken.')
    second.unmount()

    tradingBackend({ 'GET /strategies': () => problem(403, 'Refused.') })
    const third = renderAt('/trading/portfolios/new')
    expect(await screen.findByTestId('forbidden')).toBeInTheDocument()
    third.unmount()

    // The market environments failing leaves the demo ones and says why
    tradingBackend({ 'GET /api/market/environments': () => problem(502, 'Market is down.') })
    renderAt('/trading/portfolios/new')
    expect(await screen.findByRole('alert')).toHaveTextContent('Market environments: Market is down.')
    expect(within(screen.getByTestId('portfolio-environment')).getByRole('option', { name: /A14 two-symbol fixture/ })).toBeInTheDocument()
  })
})

// ---- Trade Replay ----

describe('the Trade Replay page', () => {
  async function openLoaded() {
    const backend = tradingBackend()
    renderAt(`/trading/replay/${P1}`)
    expect(screen.getByText('Loading the trade log…')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('0 / 7'))
    return backend
  }

  it('pages in the log by seq and plays it to the end', async () => {
    const { calls } = await openLoaded()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Trade Replay — Replay portfolio')
    expect(calls.filter((c) => c.path.endsWith('/events')).map((c) => c.query.get('after_seq'))).toEqual(['0'])
    expect(screen.getByTestId('replay-status')).toHaveAttribute('data-status', 'Ready')

    fireEvent.click(screen.getByTestId('replay-speed-20'))
    fireEvent.click(screen.getByTestId('replay-play'))
    await waitFor(() => expect(screen.getByTestId('replay-status')).toHaveAttribute('data-status', 'Complete'))
    const rows = within(screen.getByTestId('replay-events')).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('RUN_STARTED')
    expect(rows[rows.length - 1]).toHaveTextContent('RUN_COMPLETED')
    expect(rows[4]).toHaveTextContent('ORDER_FILLED BUY')
    expect(rows[4]).toHaveTextContent('$100.05')
    expect(screen.getByTestId('replay-fills')).toHaveTextContent('1')
    expect(screen.getByTestId('replay-value')).toHaveTextContent('$10,045')
    expect(screen.getByRole('button', { name: 'Analyze Portfolio Risk' })).toBeInTheDocument()
  })

  it('follows next_cursor across pages', async () => {
    const pages: string[] = []
    tradingBackend({
      [`GET /portfolios/${P1}/events`]: (c) => {
        pages.push(c.query.get('after_seq') ?? '')
        const after = Number(c.query.get('after_seq'))
        const items = LOG.filter((e) => e.seq > after).slice(0, 4)
        return json(200, { items, next_cursor: after === 0 ? 4 : null })
      },
    })
    renderAt(`/trading/replay/${P1}`)
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('0 / 7'))
    expect(pages).toEqual(['0', '4'])
  })

  it('plays at the chosen speed, pauses and seeks', async () => {
    await openLoaded()
    vi.useFakeTimers()
    const step = BASE_STEP_MS / 20
    fireEvent.click(screen.getByTestId('replay-speed-20'))
    expect(screen.getByTestId('replay-speed-20')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByTestId('replay-play'))
    for (let i = 0; i < 3; i += 1) {
      act(() => {
        vi.advanceTimersByTime(step)
      })
    }
    expect(screen.getByTestId('replay-position')).toHaveTextContent('3 / 7')

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    act(() => {
      vi.advanceTimersByTime(BASE_STEP_MS * 5)
    })
    expect(screen.getByTestId('replay-position')).toHaveTextContent('3 / 7')
    expect(screen.getByTestId('replay-status')).toHaveAttribute('data-status', 'Paused')

    // At 1x one event takes the whole base step
    fireEvent.click(screen.getByTestId('replay-speed-1'))
    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    act(() => {
      vi.advanceTimersByTime(step)
    })
    expect(screen.getByTestId('replay-position')).toHaveTextContent('3 / 7')
    act(() => {
      vi.advanceTimersByTime(BASE_STEP_MS - step)
    })
    expect(screen.getByTestId('replay-position')).toHaveTextContent('4 / 7')

    fireEvent.change(screen.getByTestId('replay-seek'), { target: { value: '7' } })
    expect(screen.getByTestId('replay-status')).toHaveAttribute('data-status', 'Complete')
    expect(screen.getByTestId('replay-fills')).toHaveTextContent('1')
    fireEvent.change(screen.getByTestId('replay-seek'), { target: { value: '1' } })
    expect(screen.getByTestId('replay-fills')).toHaveTextContent('0')
  })

  it('starts afresh when the app moves to another run', async () => {
    tradingBackend()
    renderAt('/trading/replay/1042')
    goTo(`/trading/replay/${P1}`)
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('0 / 7'))
    fireEvent.change(screen.getByTestId('replay-seek'), { target: { value: '7' } })
    goTo('/trading/replay/1042')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Trade Replay — Simulation #1042')
    expect(screen.getByTestId('replay-position')).toHaveTextContent('0 / 0')
  })

  it('offers the run picker when the id names no portfolio', async () => {
    const { calls } = tradingBackend()
    renderAt('/trading/replay/1042')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Trade Replay — Simulation #1042')
    expect(screen.getByText('Choose a run to replay')).toBeInTheDocument()
    const picker = screen.getByTestId('replay-run')
    // Only portfolios that have run are offered
    await waitFor(() => expect(within(picker).getByRole('option', { name: 'Replay portfolio — Momentum 2' })).toBeInTheDocument())
    expect(within(picker).queryByRole('option', { name: /Fresh portfolio/ })).toBeNull()
    expect(calls.map((c) => c.path)).toEqual(['/portfolios'])
    fireEvent.change(picker, { target: { value: P1 } })
    expect(screen.getByTestId('location')).toHaveTextContent(`/trading/replay/${P1}`)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows the loading, empty, error, not-found and 403 states', async () => {
    tradingBackend({ [`GET /portfolios/${P1}`]: never })
    const loading = renderAt(`/trading/replay/${P1}`)
    expect(screen.getByText('Loading the trade log…')).toBeInTheDocument()
    expect(screen.getByTestId('replay-play')).toBeDisabled()
    loading.unmount()

    tradingBackend({ [`GET /portfolios/${P1}/events`]: () => json(200, { items: [], next_cursor: null }) })
    const empty = renderAt(`/trading/replay/${P1}`)
    expect(await screen.findByText('This portfolio has not run yet')).toBeInTheDocument()
    empty.unmount()

    tradingBackend({ [`GET /portfolios/${P1}/events`]: () => problem(500, 'Log unavailable.') })
    const failed = renderAt(`/trading/replay/${P1}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('Log unavailable.')
    failed.unmount()

    tradingBackend({ [`GET /portfolios/${P1}`]: () => problem(404, 'No portfolio has this id.') })
    const missing = renderAt(`/trading/replay/${P1}`)
    expect(await screen.findByText('No portfolio has this id')).toBeInTheDocument()
    missing.unmount()

    tradingBackend({ [`GET /portfolios/${P1}`]: () => problem(403, 'Refused.') })
    renderAt(`/trading/replay/${P1}`)
    expect(await screen.findByTestId('forbidden')).toHaveTextContent('Refused.')
  })
})
