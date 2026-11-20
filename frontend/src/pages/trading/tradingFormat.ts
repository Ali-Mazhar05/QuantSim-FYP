// Plain helpers the five trading pages share: what a failed request means for the page,
// and the plain-language summary of a strategy's parameters that the prototype's cards show.

import { ApiError } from '../../services/api/client'
import { errorMessage } from '../auth/authShared'
import { type Strategy, formatFraction, kindLabel } from './tradingApi'

/** What a failed request means for the page: refused for this role, or another failure. */
export interface Failure {
  forbidden: boolean
  message: string
}

export function failureOf(error: unknown): Failure {
  const forbidden = error instanceof ApiError && error.status === 403
  return { forbidden, message: errorMessage(error) }
}

const p = (params: Record<string, unknown>, key: string): string => String(params[key] ?? '—')

/** One line under the strategy's name: its type and its sizing limit. */
export function strategySubtitle(s: Strategy): string {
  const params = s.params
  switch (s.kind) {
    case 'momentum':
      return `${kindLabel(s.kind)} · Rebalance: every ${p(params, 'rebalance_every')} sessions · Max position: ${formatFraction(params.max_position)}`
    default:
      return `${kindLabel(s.kind)} · Cash buffer: ${formatFraction(params.cash_buffer)}`
  }
}

/** The strategy's rules in plain language, from its stored parameters. */
export function strategyRules(s: Strategy): string[] {
  const params = s.params
  switch (s.kind) {
    case 'buy_and_hold': {
      const weights = params.weights as Record<string, unknown> | null | undefined
      const buys = weights
        ? `Buys ${Object.entries(weights)
            .map(([symbol, w]) => `${symbol} at ${formatFraction(w)}`)
            .join(', ')} once and holds.`
        : 'Buys every symbol of the environment at equal weights once and holds.'
      return [buys, `Keeps ${formatFraction(params.cash_buffer)} of value in cash.`]
    }
    case 'momentum':
      return [
        `Ranks symbols by their ${p(params, 'lookback')}-session return and holds the top ${p(params, 'top_n')}.`,
        `Rebalances every ${p(params, 'rebalance_every')} sessions, at most ${formatFraction(params.max_position)} per position.`,
        `Keeps ${formatFraction(params.cash_buffer)} of value in cash.`,
      ]
    case 'ma_crossover':
      return [
        `Buys when the ${p(params, 'fast')}-session average crosses above the ${p(params, 'slow')}-session average.`,
        'Sells when it crosses back below.',
        `Keeps ${formatFraction(params.cash_buffer)} of value in cash.`,
      ]
    case 'mean_reversion':
      return [
        `Buys when the price is ${p(params, 'entry_z')} standard deviations below its ${p(params, 'window')}-session mean.`,
        `Exits when the z-score returns to ${p(params, 'exit_z')}.`,
        `Keeps ${formatFraction(params.cash_buffer)} of value in cash.`,
      ]
    default:
      return Object.entries(params).map(([key, value]) => `${key}: ${String(value)}`)
  }
}
