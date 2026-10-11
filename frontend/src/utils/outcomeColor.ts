// Shared helper so every non-candlestick line/area chart colors itself the
// same way: green when the series ends above where it started, red when it
// ends below — matching the equity curve, drawdown chart, and any similar
// value-over-time visualization.

export function outcomeColor(start: number, end: number) {
  return end >= start ? 'var(--color-risk-low)' : 'var(--color-risk-severe)'
}

export function seriesOutcomeColor(values: number[]) {
  if (values.length < 2) return 'var(--color-risk-low)'
  return outcomeColor(values[0], values[values.length - 1])
}
