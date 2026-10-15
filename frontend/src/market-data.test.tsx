import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Instruments from './pages/market/Instruments'
import MarketData from './pages/market/MarketData'
import { clearSession } from './services/api/client'

function json(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function problem(status: number, type: string, detail: string): Response {
  return json(status, { type, title: 'Problem', status, detail })
}

const AAPL = {
  id: 'id-aapl',
  symbol: 'AAPL',
  name: 'Apple Inc.',
  sector: 'Technology',
  price: '186.88000000',
  change_pct: '-1.25000000',
  status: 'active',
  exchange: 'XNAS',
  asset_class: 'equity',
}
const NVDA = { ...AAPL, id: 'id-nvda', symbol: 'NVDA', name: 'NVIDIA Corp.', price: '120.00000000', change_pct: '3.5' }
const NEW = { ...AAPL, id: 'id-new', symbol: 'NEW', name: 'Newly Added', price: null, change_pct: null }

function candle(day: string, start: string, close: string) {
  return {
    session_date: day,
    period_start: start,
    open: close,
    high: close,
    low: close,
    close,
    volume: '1000',
    adj_close: close,
    sessions: 1,
  }
}

const CANDLES = {
  interval: 'daily',
  items: [candle('2024-01-02', '2024-01-02', '100'), candle('2024-01-03', '2024-01-03', '120')],
}

const METRICS = {
  interval: 'daily',
  observations: 2,
  price_basis: 'adjusted_close',
  period_return: '0.20000000',
  annualised_volatility: null,
  max_drawdown: '-0.05000000',
  drawdown_peak: '2024-01-02',
  drawdown_trough: '2024-01-03',
  unavailable: { annualised_volatility: 'needs at least 3 observations' },
}

type Responder = (url: URL) => Response | undefined

/** A fake market API. Every request is recorded as its URL. */
function marketBackend(respond: Responder = () => undefined) {
  const urls: URL[] = []
  const fetch = vi.fn(async (input: string) => {
    const url = new URL(input)
    urls.push(url)
    const custom = respond(url)
    if (custom) return custom
    if (url.pathname === '/api/market/instruments') return json(200, [AAPL, NVDA])
    if (url.pathname.endsWith('/candles')) return json(200, CANDLES)
    if (url.pathname.endsWith('/metrics')) return json(200, METRICS)
    return json(404, { detail: 'Not found' })
  })
  vi.stubGlobal('fetch', fetch)
  return { urls, series: () => urls.filter((u) => /\/(candles|metrics)$/.test(u.pathname)) }
}

function renderMarketData() {
  return render(
    <MemoryRouter>
      <MarketData />
    </MemoryRouter>,
  )
}

describe('the Instruments page', () => {
  beforeEach(() => clearSession())
  afterEach(() => vi.unstubAllGlobals())

  it('lists the instruments the API returns with price and change', async () => {
    marketBackend()
    render(
      <MemoryRouter>
        <Instruments />
      </MemoryRouter>,
    )
    const aapl = (await screen.findByText('Apple Inc.')).closest('tr') as HTMLElement
    expect(within(aapl).getByText('AAPL')).toBeInTheDocument()
    expect(within(aapl).getByText('$186.88')).toBeInTheDocument()
    expect(within(aapl).getByText('-1.25%')).toBeInTheDocument()
    const nvda = screen.getByText('NVIDIA Corp.').closest('tr') as HTMLElement
    expect(within(nvda).getByText('+3.50%')).toBeInTheDocument()
  })

  it('shows an instrument without enough bars with no price or change', async () => {
    marketBackend((url) => (url.pathname === '/api/market/instruments' ? json(200, [NEW]) : undefined))
    render(
      <MemoryRouter>
        <Instruments />
      </MemoryRouter>,
    )
    const row = (await screen.findByText('Newly Added')).closest('tr') as HTMLElement
    expect(within(row).getAllByText('—')).toHaveLength(2)
  })

  it('says when there are no instruments and when the backend fails', async () => {
    marketBackend((url) => (url.pathname === '/api/market/instruments' ? json(200, []) : undefined))
    const first = render(
      <MemoryRouter>
        <Instruments />
      </MemoryRouter>,
    )
    expect(await screen.findByText('No instruments yet')).toBeInTheDocument()
    first.unmount()

    marketBackend(() => problem(500, 'about:blank', 'The market database is unavailable.'))
    render(
      <MemoryRouter>
        <Instruments />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('The market database is unavailable.')
  })
})

describe('the Market Data page', () => {
  beforeEach(() => clearSession())
  afterEach(() => vi.unstubAllGlobals())

  it('draws the series and shows the metrics from the API', async () => {
    const backend = marketBackend()
    const { container } = renderMarketData()

    expect(await screen.findByText('Apple Inc. (AAPL)')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('20.00%')).toBeInTheDocument()) // period return
    expect(screen.getByText('-5.00%')).toBeInTheDocument() // maximum drawdown
    expect(screen.getByText('adjusted close')).toBeInTheDocument()
    expect(container.querySelectorAll('svg rect')).toHaveLength(2) // one body per candle

    const [candles, metrics] = backend.series()
    expect(candles.pathname).toBe('/api/market/instruments/id-aapl/candles')
    expect(metrics.pathname).toBe('/api/market/instruments/id-aapl/metrics')
    expect(candles.searchParams.get('interval')).toBe('daily')
    expect(candles.searchParams.get('from')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('explains a metric that has no value instead of inventing one', async () => {
    marketBackend()
    renderMarketData()
    expect(await screen.findByText('needs at least 3 observations')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('asks for the chosen interval, dates and symbol', async () => {
    const backend = marketBackend()
    renderMarketData()
    await screen.findByText('Apple Inc. (AAPL)')

    fireEvent.change(screen.getByLabelText('Interval'), { target: { value: 'weekly' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2024-01-01' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2024-03-31' } })
    fireEvent.click(screen.getByRole('button', { name: 'NVDA' }))

    await waitFor(() => {
      const last = backend.series().at(-1)
      expect(last?.pathname).toBe('/api/market/instruments/id-nvda/metrics')
      expect(last?.searchParams.get('interval')).toBe('weekly')
      expect(last?.searchParams.get('from')).toBe('2024-01-01')
      expect(last?.searchParams.get('to')).toBe('2024-03-31')
    })
    expect(screen.getByRole('button', { name: 'NVDA' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows an empty state for a range with no observations (TC-UI-01)', async () => {
    marketBackend((url) =>
      url.pathname.endsWith('/candles')
        ? json(200, { interval: 'daily', items: [] })
        : url.pathname.endsWith('/metrics')
          ? json(200, {
              ...METRICS,
              observations: 0,
              period_return: null,
              max_drawdown: null,
              unavailable: { period_return: 'needs at least 2 observations' },
            })
          : undefined,
    )
    const { container } = renderMarketData()
    expect(await screen.findByText('No observations in this range')).toBeInTheDocument()
    expect(container.querySelector('svg rect')).toBeNull()
  })

  it('reports a failed request instead of an empty or invented chart', async () => {
    marketBackend((url) =>
      url.pathname.endsWith('/candles') ? problem(500, 'about:blank', 'Could not read the series.') : undefined,
    )
    const { container } = renderMarketData()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read the series.')
    expect(container.querySelector('svg rect')).toBeNull()
  })

  it('does not send a reversed date range', async () => {
    const backend = marketBackend()
    renderMarketData()
    await screen.findByText('Apple Inc. (AAPL)')
    const before = backend.series().length

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2024-05-01' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2024-04-01' } })

    expect(await screen.findByRole('alert')).toHaveTextContent('The start date must not be after the end date.')
    const sent = backend.series().slice(before)
    expect(sent.every((u) => u.searchParams.get('from') !== '2024-05-01' || u.searchParams.get('to') !== '2024-04-01')).toBe(true)
  })

  it('says so when no instrument has been added yet', async () => {
    marketBackend((url) => (url.pathname === '/api/market/instruments' ? json(200, []) : undefined))
    renderMarketData()
    expect(await screen.findByText('No instruments yet')).toBeInTheDocument()
  })

  it('says the backend cannot be reached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )
    renderMarketData()
    expect(await screen.findByRole('alert')).toHaveTextContent(/Cannot reach the QuantSim server/)
  })
})
