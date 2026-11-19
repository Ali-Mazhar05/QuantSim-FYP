import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CandlestickChart, { type ChartCandle } from './CandlestickChart'

/** `count` daily candles from `first`, `stepDays` apart, close rising by one from 100. */
function series(count: number, first = '2025-01-02', stepDays = 1, volume = true): ChartCandle[] {
  const start = Date.parse(`${first}T00:00:00Z`)
  return Array.from({ length: count }, (_, i) => {
    const close = 100 + i
    return {
      date: new Date(start + i * stepDays * 86_400_000).toISOString().slice(0, 10),
      open: close - 0.5,
      high: close + 1,
      low: close - 1.5,
      close,
      ...(volume ? { volume: 1_000_000 + i } : {}),
    }
  })
}

// In jsdom the chart has no measured width, so it draws at its minimum: 360 + 64 wide,
// a 360 px plot; with 10 candles each is 36 px wide and starts at its index times 36.
const chart = () => screen.getByRole('group')

describe('the candlestick chart', () => {
  it('draws one body per candle', () => {
    const { container } = render(<CandlestickChart candles={series(10)} />)
    expect(container.querySelectorAll('svg rect')).toHaveLength(10)
  })

  it('labels the price scale from the top of the range to the bottom', () => {
    render(<CandlestickChart candles={series(10)} />)
    const labels = screen.getAllByTestId('price-tick').map((t) => t.textContent)
    // highest high 110 padded 2% up = 112.20; lowest low 98.5 padded 2% down = 96.53
    expect(labels).toEqual(['112.20', '108.28', '104.37', '100.45', '96.53'])
  })

  it('labels dates by day over a short span and by month over a long one', () => {
    const { unmount } = render(<CandlestickChart candles={series(10)} />)
    expect(screen.getAllByTestId('date-tick')[0]).toHaveTextContent('Jan 2')
    unmount()
    render(<CandlestickChart candles={series(60, '2025-01-02', 7)} />)
    expect(screen.getAllByTestId('date-tick')[0]).toHaveTextContent('Jan 2025')
  })

  it('spaces date labels so they never overlap', () => {
    render(<CandlestickChart candles={series(300)} />)
    const xs = screen.getAllByTestId('date-tick').map((t) => Number(t.getAttribute('x')))
    expect(xs.length).toBeGreaterThan(2)
    for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(84)
  })

  it('shows the session under the pointer and hides it when the pointer leaves', () => {
    render(<CandlestickChart candles={series(10)} />)
    expect(screen.queryByRole('tooltip')).toBeNull()

    fireEvent.mouseMove(chart(), { clientX: 36 * 3 + 5 })
    const tip = screen.getByRole('tooltip')
    expect(within(tip).getByText('2025-01-05')).toBeInTheDocument()
    expect(within(tip).getByText('102.50')).toBeInTheDocument() // open
    expect(within(tip).getByText('104.00')).toBeInTheDocument() // high
    expect(within(tip).getByText('101.50')).toBeInTheDocument() // low
    expect(within(tip).getByText('103.00')).toBeInTheDocument() // close
    expect(within(tip).getByText('+0.98%')).toBeInTheDocument() // 102 -> 103
    expect(within(tip).getByText('1,000,003')).toBeInTheDocument()
    expect(screen.getByTestId('crosshair')).toBeInTheDocument()

    fireEvent.mouseMove(chart(), { clientX: 360 + 20 }) // over the price scale
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.mouseMove(chart(), { clientX: 5 })
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    fireEvent.mouseLeave(chart())
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('reads every session from the keyboard and announces it', () => {
    render(<CandlestickChart candles={series(10)} />)
    fireEvent.focus(chart())
    expect(within(screen.getByRole('tooltip')).getByText('2025-01-11')).toBeInTheDocument() // last
    fireEvent.keyDown(chart(), { key: 'ArrowLeft' })
    expect(within(screen.getByRole('tooltip')).getByText('2025-01-10')).toBeInTheDocument()
    fireEvent.keyDown(chart(), { key: 'Home' })
    const first = screen.getByRole('tooltip')
    expect(within(first).getByText('2025-01-02')).toBeInTheDocument()
    expect(within(first).queryByText('Change')).toBeNull() // nothing before the first session
    expect(screen.getByText(/2025-01-02: open 99\.50, high 101\.00, low 98\.50, close 100\.00/)).toBeInTheDocument()
    fireEvent.keyDown(chart(), { key: 'End' })
    expect(within(screen.getByRole('tooltip')).getByText('2025-01-11')).toBeInTheDocument()
    fireEvent.keyDown(chart(), { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('leaves volume out when the series has none', () => {
    render(<CandlestickChart candles={series(10, '2025-01-02', 1, false)} />)
    fireEvent.mouseMove(chart(), { clientX: 40 })
    expect(within(screen.getByRole('tooltip')).queryByText('Volume')).toBeNull()
  })

  it('still draws the generated series the other prototype pages use', () => {
    const { container } = render(<CandlestickChart seed={3} count={30} />)
    expect(container.querySelectorAll('svg rect')).toHaveLength(30)
    expect(screen.getAllByTestId('price-tick')).toHaveLength(5)
  })
})
