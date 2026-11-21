import { http, HttpResponse } from 'msw'
import { environments } from './fixtures/environments'

// Any origin, so the tests do not depend on the configured API address
export const MARKET = '*/api/market'

export function problem(status: number, detail: string, type = 'about:blank') {
  return HttpResponse.json(
    { type, title: detail, status, detail },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

/** The default mock backend: every handler answers from a fixture. Tests override per case. */
export const handlers = [http.get(`${MARKET}/environments`, () => HttpResponse.json(environments))]
