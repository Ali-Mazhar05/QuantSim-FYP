import { describe, expect, it } from 'vitest'
import { outcomeColor, seriesOutcomeColor } from './outcomeColor'

const LOW = 'var(--color-risk-low)'
const SEVERE = 'var(--color-risk-severe)'

describe('outcomeColor', () => {
  it('uses the low-risk colour when the value ends above where it started', () => {
    expect(outcomeColor(100, 120)).toBe(LOW)
  })

  it('uses the severe colour when the value ends below where it started', () => {
    expect(outcomeColor(100, 80)).toBe(SEVERE)
  })

  it('treats an unchanged value as a non-loss', () => {
    expect(outcomeColor(100, 100)).toBe(LOW)
  })
})

describe('seriesOutcomeColor', () => {
  it('falls back to the low-risk colour for an empty series', () => {
    expect(seriesOutcomeColor([])).toBe(LOW)
  })

  it('falls back to the low-risk colour for a single point', () => {
    expect(seriesOutcomeColor([42])).toBe(LOW)
  })

  it('compares only the first and last points', () => {
    expect(seriesOutcomeColor([100, 10, 500, 101])).toBe(LOW)
    expect(seriesOutcomeColor([100, 500, 10, 99])).toBe(SEVERE)
  })
})
