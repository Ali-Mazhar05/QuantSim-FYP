import { useQuery } from '@tanstack/react-query'
import { isInverted } from '../components/forms/dateWindow'
import {
  type Candle,
  type Interval,
  getCandleSeries,
  getMetrics,
  getRecentSeries,
} from '../services/api/market'
import { marketKeys } from './queryKeys'

/** The window a user chose: an interval and an optional date range ('' means open). */
export interface WindowChoice {
  interval: Interval
  from: string
  to: string
}

/** True once the user typed a date: the window is then exactly what they asked for. */
export const isExplicit = (choice: WindowChoice): boolean => choice.from !== '' || choice.to !== ''

/**
 * The candles for a choice. With no dates it is the latest default window (and the latest data
 * however old); with dates it is exactly that window, so an empty answer is an empty window.
 * An inverted range is not sent at all.
 */
export function useCandles(instrumentId: string | undefined, choice: WindowChoice) {
  return useQuery({
    queryKey: marketKeys.candles(instrumentId ?? '', choice.interval, choice.from, choice.to),
    queryFn: () =>
      isExplicit(choice)
        ? getCandleSeries(instrumentId ?? '', {
            interval: choice.interval,
            from: choice.from || undefined,
            to: choice.to || undefined,
          })
        : getRecentSeries(instrumentId ?? '', choice.interval),
    enabled: Boolean(instrumentId) && !isInverted(choice.from, choice.to),
  })
}

/** The metrics of exactly the window the candles show, asked for once they are known. */
export function useMetrics(instrumentId: string | undefined, interval: Interval, candles: Candle[] | undefined) {
  const first = candles?.[0]
  const last = candles?.at(-1)
  const from = first?.date ?? ''
  const to = last?.lastSession ?? last?.date ?? ''
  return useQuery({
    queryKey: marketKeys.metrics(instrumentId ?? '', interval, from, to),
    queryFn: () => getMetrics(instrumentId ?? '', { interval, from, to }),
    enabled: Boolean(instrumentId) && from !== '',
  })
}
