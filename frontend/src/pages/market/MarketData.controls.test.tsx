import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import QueryProvider from '../../hooks/QueryProvider'
import { type Interval } from '../../services/api/market'
import type { MarketComponents } from '../../services/generated'
import { clearSession } from '../../services/api/client'
import { MARKET, problem } from '../../test/mocks/handlers'
import { server, setupMockServer } from '../../test/mocks/server'
import MarketData from './MarketData'

// B-FR-20, B-US-03, B-NFR-15: the interval selector, the date window and the metric cards, on the
// mock backend, with every state a page of this kit shows
setupMockServer()

type Schemas = MarketComponents['schemas']

const INSTRUMENTS: Schemas['InstrumentOut'][] = [
  {
    id: 'id-aapl',
    symbol: 'AAPL',
    name: 'Apple Inc.',
    sector: 'Technology',
    price: '186.88000000',
    change_pct: '-1.25000000',
    status: 'active',
    exchange: 'XNAS',
    asset_class: 'equity',
    calendar: 'XNYS',
    currency: 'USD',
    notes: '',
    vendor_symbol: 'AAPL',
    retired_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const STEP_DAYS: Record<Interval, number> = { daily: 1, weekly: 7, monthly: 30, yearly: 365 }
const day = (offset: number) => new Date(Date.UTC(2023, 0, 2 + offset)).toISOString().slice(0, 10)

/** `count` candles of an interval: period_start is the first session, session_date the last. */
function candles(interval: Interval, count: number): Schemas['CandleOut'][] {
  const step = STEP_DAYS[interval]
  return Array.from({ length: count }, (_, i) => {
    const close = (100 + i).toFixed(2)
    return {
      period_start: day(i * step),
      session_date: day(i * step + (step === 1 ? 0 : step - 3)),
      open: close,
      high: (100 + i + 1).toFixed(2),
      low: (100 + i - 1).toFixed(2),
      close,
      adj_close: close,
      volume: '1000',
      sessions: step === 1 ? 1 : 5,
    }
  })
}

const METRICS: Schemas['MetricsOut'] = {
  interval: 'daily',
  start: '2023-01-02',
  end: '2023-04-01',
  observations: 90,
  price_basis: 'adjusted_close',
  period_return: '0.12340000',
  annualised_volatility: '0.21500000',
  max_drawdown: '-0.08200000',
  drawdown_peak: '2023-02-01',
  drawdown_trough: '2023-03-04',
  unavailable: {},
}

interface Seen {
  candles: URL[]
  metrics: URL[]
}

/** The mock market API; the answer to candles and metrics can be replaced per test. */
function backend(options: { items?: (interval: Interval) => Schemas['CandleOut'][]; metrics?: Schemas['MetricsOut'] } = {}) {
  const seen: Seen = { candles: [], metrics: [] }
  server.use(
    http.get(`${MARKET}/instruments`, () => HttpResponse.json(INSTRUMENTS)),
    http.get(`${MARKET}/instruments/:id/candles`, ({ request }) => {
      const url = new URL(request.url)
      seen.candles.push(url)
      const interval = (url.searchParams.get('interval') ?? 'daily') as Interval
      const items = options.items ? options.items(interval) : candles(interval, 12)
      return HttpResponse.json({ interval, start: null, end: null, items })
    }),
    http.get(`${MARKET}/instruments/:id/metrics`, ({ request }) => {
      const url = new URL(request.url)
      seen.metrics.push(url)
      return HttpResponse.json(options.metrics ?? METRICS)
    }),
  )
  return seen
}

function renderPage() {
  return render(
    <MemoryRouter>
      <QueryProvider>
        <MarketData />
      </QueryProvider>
    </MemoryRouter>,
  )
}

const lastOf = (urls: URL[]) => urls[urls.length - 1] as URL

beforeEach(() => clearSession())

describe('Market Data controls', () => {
  it('starts on the daily default window and shows the metric cards for it', async () => {
    const seen = backend()
    renderPage()
    expect(await screen.findByRole('group', { name: /Daily candles/ })).toBeInTheDocument()
    expect(screen.getByText('Daily · last 90 sessions')).toBeInTheDocument()
    expect(lastOf(seen.candles).searchParams.get('interval')).toBe('daily')
    const cards = await screen.findByRole('region', { name: 'Metrics for the window shown' })
    expect(await within(cards).findByText('+12.34%')).toBeInTheDocument()
    expect(within(cards).getByText('21.50%')).toBeInTheDocument()
    expect(within(cards).getByText('-8.20%')).toBeInTheDocument()
    expect(within(cards).getByText('Peak 2023-02-01, trough 2023-03-04')).toBeInTheDocument()
    expect(within(cards).getByText('90')).toBeInTheDocument()
    // metrics are asked for exactly the window the chart shows: first period to last session
    expect(lastOf(seen.metrics).searchParams.get('from')).toBe('2023-01-02')
    expect(lastOf(seen.metrics).searchParams.get('to')).toBe('2023-01-13')
  })

  it.each([
    ['weekly', 'Weekly', 'last 104 weeks'],
    ['monthly', 'Monthly', 'last 60 months'],
    ['yearly', 'Yearly', 'last 20 years'],
  ] as const)('re-queries candles and metrics when the interval changes to %s', async (value, label, window) => {
    const seen = backend()
    renderPage()
    await screen.findByRole('group', { name: /Daily candles/ })
    fireEvent.change(screen.getByLabelText('Interval'), { target: { value } })
    expect(await screen.findByRole('group', { name: new RegExp(`${label} candles`) })).toBeInTheDocument()
    expect(screen.getByText(`${label} · ${window}`)).toBeInTheDocument()
    expect(lastOf(seen.candles).searchParams.get('interval')).toBe(value)
    await screen.findByRole('region', { name: 'Metrics for the window shown' })
    await within(screen.getByRole('region', { name: 'Metrics for the window shown' })).findByText('+12.34%')
    expect(lastOf(seen.metrics).searchParams.get('interval')).toBe(value)
  })

  it('asks for exactly the dates typed and goes back to the default with Reset window', async () => {
    const seen = backend()
    renderPage()
    await screen.findByRole('group', { name: /Daily candles/ })
    expect(screen.getByRole('button', { name: 'Reset window' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2023-01-03' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2023-01-10' } })
    expect(await screen.findByText('Daily · 2023-01-03 to 2023-01-10')).toBeInTheDocument()
    // the label changes first; the requests follow in no fixed order, so look for the exact one
    await waitFor(() =>
      expect(
        seen.candles.some(
          (u) => u.searchParams.get('from') === '2023-01-03' && u.searchParams.get('to') === '2023-01-10',
        ),
      ).toBe(true),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Reset window' }))
    expect(await screen.findByText('Daily · last 90 sessions')).toBeInTheDocument()
  })

  it('shows an explicit empty state for a window without observations', async () => {
    backend({ items: () => [] })
    renderPage()
    expect(await screen.findByText('No observations yet')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2019-01-01' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2019-01-31' } })
    expect(await screen.findByText('No observations in this window')).toBeInTheDocument()
    expect(screen.getByText(/AAPL has no ingested sessions between 2019-01-01 and 2019-01-31/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Metrics for the window shown' })).not.toBeInTheDocument()
  })

  it('names an inverted window in text and does not send it', async () => {
    const seen = backend()
    renderPage()
    await screen.findByRole('group', { name: /Daily candles/ })
    const before = seen.candles.length
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2023-01-05' } })
    await screen.findByText(/2023-01-05|latest/)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2023-02-01' } })
    expect(await screen.findByText('From must not be after To.')).toBeInTheDocument()
    expect(screen.getByText('Choose a valid window')).toBeInTheDocument()
    expect(screen.getByLabelText('From')).toHaveAttribute('aria-invalid', 'true')
    expect(seen.candles.some((u) => u.searchParams.get('from') === '2023-02-01')).toBe(false)
    expect(seen.candles.length).toBeGreaterThan(before) // the valid To-only window was sent
  })

  it('says why a metric is unavailable, in words, and still shows the others', async () => {
    backend({
      metrics: {
        ...METRICS,
        annualised_volatility: null,
        unavailable: { annualised_volatility: 'needs at least 3 observations' },
      },
    })
    renderPage()
    const cards = await screen.findByRole('region', { name: 'Metrics for the window shown' })
    expect(await within(cards).findByText('Unavailable')).toBeInTheDocument()
    expect(within(cards).getByText('needs at least 3 observations')).toBeInTheDocument()
    expect(within(cards).getByText('+12.34%')).toBeInTheDocument()
  })

  it('keeps the chart when only the metrics fail', async () => {
    backend()
    server.use(http.get(`${MARKET}/instruments/:id/metrics`, () => problem(500, 'Metrics are down')))
    renderPage()
    expect(await screen.findByRole('group', { name: /Daily candles/ })).toBeInTheDocument()
    const cards = await screen.findByRole('region', { name: 'Metrics for the window shown' })
    expect(await within(cards).findAllByText('Metrics are down')).not.toHaveLength(0)
  })

  it('shows loading while the series is on its way', async () => {
    backend()
    server.use(http.get(`${MARKET}/instruments/:id/candles`, () => delay('infinite')))
    renderPage()
    expect(await screen.findByText('Loading…')).toBeInTheDocument()
  })

  it('shows a 403 on the series as a readable message', async () => {
    backend()
    server.use(http.get(`${MARKET}/instruments/:id/candles`, () => problem(403, 'Your role may not read this series')))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Your role may not read this series')
  })

  it('offers the controls by label, so they work with a keyboard and a screen reader', async () => {
    backend()
    renderPage()
    await screen.findByRole('group', { name: /Daily candles/ })
    expect(screen.getByRole('combobox', { name: 'Interval' })).toHaveValue('daily')
    expect(screen.getByLabelText('From')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('To')).toHaveAttribute('type', 'date')
  })
})
