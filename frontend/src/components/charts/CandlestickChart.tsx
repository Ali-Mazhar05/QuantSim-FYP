import { type KeyboardEvent, type MouseEvent, useMemo, useState } from 'react'
import { generateCandles } from '../../services/mock/generators'
import { useElementWidth } from '../../hooks/useElementWidth'

export interface ChartCandle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

// Room for the price scale on the right and the dates underneath
const PRICE_AXIS = 64
const DATE_AXIS = 22
// Date labels at least this far apart, so they never overlap whatever the zoom
const MIN_LABEL_GAP = 84
const GRID = [0, 0.25, 0.5, 0.75, 1]
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const PRICE = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const VOLUME = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** "2025-01-02" as "Jan 2" over a short span, "Jan 2025" over a long one. */
function dateLabel(iso: string, long: boolean): string {
  const [year, month, day] = iso.split('-')
  const name = MONTHS[Number(month) - 1] ?? month
  return long ? `${name} ${year}` : `${name} ${Number(day)}`
}

function signed(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

/** Draws `candles` when given (real data); otherwise a generated series from seed, start,
 * vol and count, which the other POC pages still use. A given series must not be empty.
 *
 * A price scale on the right, dates underneath, and the session under the pointer (or
 * chosen with the arrow keys) is outlined with its date, open, high, low, close, change
 * from the previous close and, when known, volume. */
export default function CandlestickChart({
  seed = 1,
  start = 200,
  vol = 0.02,
  count = 90,
  height = 260,
  candles: given,
}: {
  seed?: number
  start?: number
  vol?: number
  count?: number
  height?: number
  candles?: ChartCandle[]
}) {
  const generated = useMemo(
    () => (given ? [] : generateCandles({ seed, count, start, vol })),
    [given, seed, count, start, vol],
  )
  const candles: ChartCandle[] = given ?? generated
  const n = candles.length
  const [wrapRef, available] = useElementWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)
  // Draw at the panel's real width so the candles widen to fill it. Below
  // MIN_PLOT the candles keep their own size and only the plot scrolls sideways,
  // which is the only case where they would otherwise be unreadable. The price
  // scale sits outside the scrolling part, so it is always in view.
  const MIN_PLOT = Math.max(360, n * 4)
  const plot = Math.max(MIN_PLOT, (available || 0) - PRICE_AXIS)
  const cw = plot / n
  const highs = candles.map((c) => c.high)
  const lows = candles.map((c) => c.low)
  const minV = Math.min(...lows) * 0.98
  const maxV = Math.max(...highs) * 1.02
  const y = (v: number) => height - ((v - minV) / (maxV - minV)) * height
  const x = (i: number) => i * cw + cw / 2

  // Month and year labels once the series spans more than about six months
  const spanDays = n > 1 ? (Date.parse(candles[n - 1].date) - Date.parse(candles[0].date)) / 86_400_000 : 0
  const longDates = spanDays > 183
  const step = Math.max(1, Math.ceil(MIN_LABEL_GAP / cw))
  const dateTicks: number[] = []
  for (let i = 0; i < n; i += step) dateTicks.push(i)

  const pick = (event: MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const scale = box.width > 0 ? plot / box.width : 1
    const px = (event.clientX - box.left) * scale
    setActive(px < 0 || px > plot ? null : Math.min(n - 1, Math.max(0, Math.floor(px / cw))))
  }

  const keys = (event: KeyboardEvent<SVGSVGElement>) => {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, PageUp: -10, PageDown: 10 }
    if (event.key in moves) {
      event.preventDefault()
      setActive((i) => Math.min(n - 1, Math.max(0, (i ?? n - 1) + moves[event.key])))
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setActive(event.key === 'Home' ? 0 : n - 1)
    } else if (event.key === 'Escape') {
      setActive(null)
    }
  }

  const c = active === null ? null : candles[active]
  const previous = active !== null && active > 0 ? candles[active - 1] : null
  const change = c && previous && previous.close !== 0 ? ((c.close - previous.close) / previous.close) * 100 : null
  const summary = c
    ? `${c.date}: open ${PRICE.format(c.open)}, high ${PRICE.format(c.high)}, low ${PRICE.format(c.low)}, close ${PRICE.format(c.close)}` +
      (change === null ? '' : `, change ${signed(change)}`) +
      (c.volume === undefined ? '' : `, volume ${VOLUME.format(c.volume)}`)
    : ''
  // Keep the tooltip inside the plot: to the left of the cursor in the right half
  const onRight = active !== null && x(active) > plot / 2

  return (
    // relative: anchors the screen-reader line below, which would otherwise be placed
    // against the page and stretch it (a page-wide scrollbar)
    <div ref={wrapRef} className="relative flex w-full">
      <div className="min-w-0 flex-1 overflow-x-auto">
        <div className="relative" style={{ width: plot }}>
          <svg
            viewBox={`0 0 ${plot} ${height + DATE_AXIS}`}
            width={plot}
            height={height + DATE_AXIS}
            style={{ display: 'block' }}
            tabIndex={0}
            role="group"
            aria-roledescription="chart"
            aria-label={`Daily candles, ${candles[0]?.date ?? ''} to ${candles[n - 1]?.date ?? ''}. Use the arrow keys to read each session.`}
            onMouseMove={pick}
            onMouseLeave={() => setActive(null)}
            onFocus={() => setActive((i) => i ?? n - 1)}
            onBlur={() => setActive(null)}
            onKeyDown={keys}
            className="outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
          >
            {GRID.map((f) => (
              <line key={f} x1={0} x2={plot} y1={height * f} y2={height * f} stroke="var(--color-border)" strokeWidth={1} />
            ))}
            {candles.map((candle, i) => {
              const cx = x(i)
              const up = candle.close >= candle.open
              const color = up ? 'var(--color-risk-low)' : 'var(--color-risk-severe)'
              return (
                <g key={candle.date}>
                  <line x1={cx} x2={cx} y1={y(candle.high)} y2={y(candle.low)} stroke={color} strokeWidth={1} />
                  <rect
                    x={cx - cw * 0.32}
                    y={Math.min(y(candle.open), y(candle.close))}
                    width={cw * 0.64}
                    height={Math.max(1, Math.abs(y(candle.close) - y(candle.open)))}
                    fill={color}
                  />
                </g>
              )
            })}
            <line x1={0} x2={plot} y1={height} y2={height} stroke="var(--color-border-strong)" />
            {dateTicks.map((i) => (
              <text
                key={candles[i].date}
                data-testid="date-tick"
                x={x(i)}
                y={height + 15}
                fontSize={10}
                fill="var(--color-text-muted)"
                textAnchor={i === 0 ? 'start' : 'middle'}
              >
                {dateLabel(candles[i].date, longDates)}
              </text>
            ))}
            {c && active !== null && (
              <g pointerEvents="none" data-testid="crosshair">
                <line x1={x(active)} x2={x(active)} y1={0} y2={height} stroke="var(--color-text-muted)" strokeDasharray="3 3" />
                <line x1={0} x2={plot} y1={y(c.close)} y2={y(c.close)} stroke="var(--color-text-muted)" strokeDasharray="3 3" />
              </g>
            )}
          </svg>
          {c && active !== null && (
            <div
              role="tooltip"
              className="pointer-events-none absolute top-2 z-10 rounded border border-[var(--color-border-strong)] bg-[var(--color-bg-1)] px-3 py-2 text-xs shadow-lg"
              style={onRight ? { right: plot - x(active) + 12 } : { left: x(active) + 12 }}
            >
              <div className="mono mb-1 font-semibold text-[var(--color-text-primary)]">{c.date}</div>
              <dl className="mono grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-[var(--color-text-secondary)]">
                <dt>Open</dt>
                <dd className="text-right">{PRICE.format(c.open)}</dd>
                <dt>High</dt>
                <dd className="text-right">{PRICE.format(c.high)}</dd>
                <dt>Low</dt>
                <dd className="text-right">{PRICE.format(c.low)}</dd>
                <dt>Close</dt>
                <dd className="text-right font-semibold text-[var(--color-text-primary)]">{PRICE.format(c.close)}</dd>
                {change !== null && (
                  <>
                    <dt>Change</dt>
                    <dd
                      className="text-right"
                      style={{ color: change >= 0 ? 'var(--color-risk-low)' : 'var(--color-risk-severe)' }}
                    >
                      {signed(change)}
                    </dd>
                  </>
                )}
                {c.volume !== undefined && (
                  <>
                    <dt>Volume</dt>
                    <dd className="text-right">{VOLUME.format(c.volume)}</dd>
                  </>
                )}
              </dl>
            </div>
          )}
        </div>
      </div>
      {/* The price scale, outside the scrolling plot so it never scrolls away */}
      <svg
        viewBox={`0 0 ${PRICE_AXIS} ${height + DATE_AXIS}`}
        width={PRICE_AXIS}
        height={height + DATE_AXIS}
        className="shrink-0"
        style={{ display: 'block' }}
        aria-hidden="true"
      >
        <line x1={0} x2={0} y1={0} y2={height} stroke="var(--color-border-strong)" />
        {GRID.map((f) => (
          <text
            key={f}
            data-testid="price-tick"
            x={6}
            y={Math.min(height - 3, Math.max(10, height * f + 4))}
            fontSize={10}
            fill="var(--color-text-muted)"
            className="mono"
          >
            {PRICE.format(maxV - f * (maxV - minV))}
          </text>
        ))}
        {c && (
          // A halo in the page colour keeps it readable over the scale label it crosses
          <text
            x={6}
            y={Math.min(height - 3, Math.max(10, y(c.close) + 4))}
            fontSize={10}
            fontWeight={600}
            fill="var(--color-text-primary)"
            stroke="var(--color-bg-1)"
            strokeWidth={6}
            paintOrder="stroke"
          >
            {PRICE.format(c.close)}
          </text>
        )}
      </svg>
      <p className="sr-only" aria-live="polite">
        {summary}
      </p>
    </div>
  )
}
