// Single source for the demo equity/drawdown series so the dashboard's panel
// headers (portfolio value, max drawdown) stay in sync with the charts that
// render them, instead of each place picking its own numbers.

import { generateDrawdownSeries, generateEquityCurve } from './generators'

const EQUITY = generateEquityCurve({ seed: 909, days: 60, start: 1_000_000, drift: 0.0834, vol: 0.182 })
const DRAWDOWN = generateDrawdownSeries(EQUITY)

export const PORTFOLIO_EQUITY_SERIES = EQUITY
export const PORTFOLIO_DRAWDOWN_SERIES = DRAWDOWN

export const LATEST_PORTFOLIO_VALUE = EQUITY[EQUITY.length - 1].value
export const MAX_DRAWDOWN_PCT = Math.min(...DRAWDOWN.map((d) => d.drawdown))
