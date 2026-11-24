import type { MarketComponents } from '../../../services/generated'

type Candle = MarketComponents['schemas']['CandleOut']

/** `count` daily candles from 2020-01-02, one per calendar day (a fixture, not a trading calendar). */
export function candles(count: number): { interval: 'daily'; items: Candle[] } {
  return {
    interval: 'daily',
    items: Array.from({ length: count }, (_, i) => {
      const day = new Date(Date.UTC(2020, 0, 2) + i * 86_400_000).toISOString().slice(0, 10)
      const close = (100 + i).toFixed(4)
      return {
        session_date: day,
        period_start: day,
        open: close,
        high: close,
        low: close,
        close,
        volume: '10.00000000',
        adj_close: close,
        sessions: 1,
      } as Candle
    }),
  }
}

/** The date of session `index` of the fixture. */
export const dayOf = (index: number): string => candles(index + 1).items[index].session_date
