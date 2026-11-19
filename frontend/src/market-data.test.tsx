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

function candle(day: string, close: string) {
  return {
    session_date: day,
    period_start: day,
    open: close,
    high: close,
    low: close,
    close,
    volume: '1000',
    adj_close: close,
    sessions: 1,
  }
}

/** `count` consecutive daily candles ending 2024-06-28, close rising by one */
function series(count: number) {
  const end = Date.UTC(2024, 5, 28)
  return {
    interval: 'daily',
    items: Array.from({ length: count }, (_, i) =>
      candle(new Date(end - (count - 1 - i) * 86_400_000).toISOString().slice(0, 10), String(100 + i)),
    ),
  }
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
    if (url.pathname.endsWith('/candles')) return json(200, series(120))
    return json(404, { detail: 'Not found' })
  })
  vi.stubGlobal('fetch', fetch)
  return { urls, series: () => urls.filter((u) => u.pathname.endsWith('/candles')) }
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

  it('keeps the prototype layout and draws the last 90 sessions from the API', async () => {
    const backend = marketBackend()
    const { container } = renderMarketData()

    expect(await screen.findByText('Apple Inc. (AAPL)')).toBeInTheDocument()
    expect(screen.getByText('Daily · last 90 sessions')).toBeInTheDocument()
    expect(screen.getByText('Daily OHLC series for instruments within the active market environment.')).toBeInTheDocument()
    await waitFor(() => expect(container.querySelectorAll('svg rect')).toHaveLength(90)) // 120 received, last 90 drawn

    const [request] = backend.series()
    expect(request.pathname).toBe('/api/market/instruments/id-aapl/candles')
    expect(request.searchParams.get('interval')).toBe('daily')
  })

  it('adds no control the prototype does not have', async () => {
    marketBackend()
    renderMarketData()
    await screen.findByText('Apple Inc. (AAPL)')
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(document.querySelector('input')).toBeNull()
    expect(screen.queryByText(/volatility|drawdown|period return/i)).toBeNull()
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['AAPL', 'NVDA'])
  })

  it('switches to another instrument from the symbol buttons', async () => {
    const backend = marketBackend()
    renderMarketData()
    await screen.findByText('Apple Inc. (AAPL)')

    fireEvent.click(screen.getByRole('button', { name: 'NVDA' }))

    expect(await screen.findByText('NVIDIA Corp. (NVDA)')).toBeInTheDocument()
    await waitFor(() => expect(backend.series().at(-1)?.pathname).toBe('/api/market/instruments/id-nvda/candles'))
  })

  it('falls back to the whole history when the data is older than the recent window', async () => {
    const calls: URL[] = []
    marketBackend((url) => {
      if (!url.pathname.endsWith('/candles')) return undefined
      calls.push(url)
      return json(200, url.searchParams.has('from') ? { interval: 'daily', items: [] } : series(5))
    })
    const { container } = renderMarketData()
    await waitFor(() => expect(container.querySelectorAll('svg rect')).toHaveLength(5))
    expect(calls.map((u) => u.searchParams.has('from'))).toEqual([true, false])
  })

  it('shows an empty state when the instrument has no ingested sessions (TC-UI-01)', async () => {
    marketBackend((url) => (url.pathname.endsWith('/candles') ? json(200, { interval: 'daily', items: [] }) : undefined))
    const { container } = renderMarketData()
    expect(await screen.findByText('No observations yet')).toBeInTheDocument()
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
