import { HttpResponse } from 'msw'

// Any origin, so the tests do not depend on the configured API address
export const MARKET = '*/api/market'

export function problem(status: number, detail: string, type = 'about:blank') {
  return HttpResponse.json(
    { type, title: detail, status, detail },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}
