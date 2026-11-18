import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { clearSession } from './client'
import { server, setupMockServer } from '../../test/mocks/server'
import { MARKET } from '../../test/mocks/handlers'
import { environments } from '../../test/mocks/fixtures/environments'
import { apiGet, apiPost, buildUrl } from './typed'

setupMockServer()
beforeEach(() => clearSession())

describe('buildUrl', () => {
  it('fills path parameters and encodes them', () => {
    expect(buildUrl('/api/market/instruments/{instrument_id}', { path: { instrument_id: 'a b/c' } })).toBe(
      '/api/market/instruments/a%20b%2Fc',
    )
  })

  it('adds the query and leaves out undefined and null values', () => {
    expect(buildUrl('/x', { query: { interval: 'weekly', from: undefined, to: null, limit: 5 } })).toBe(
      '/x?interval=weekly&limit=5',
    )
  })

  it('refuses a missing path parameter by name', () => {
    expect(() => buildUrl('/x/{id}')).toThrow('Missing path parameter "id"')
  })
})

describe('apiGet and apiPost', () => {
  it('reads a typed list', async () => {
    const list = await apiGet('/api/market/environments')
    expect(list.map((e) => e.symbols)).toEqual([['AAPL', 'MSFT'], ['AAPL']])
  })

  it('sends path parameters and the query to the service', async () => {
    let seen = ''
    server.use(
      http.get(`${MARKET}/instruments/:id/candles`, ({ request, params }) => {
        seen = `${params.id} ${new URL(request.url).searchParams.toString()}`
        return HttpResponse.json({ items: [] })
      }),
    )
    await apiGet('/api/market/instruments/{instrument_id}/candles', {
      path: { instrument_id: 'abc' },
      query: { interval: 'weekly', from: '2020-01-01' },
    })
    expect(seen).toBe('abc interval=weekly&from=2020-01-01')
  })

  it('posts the body as JSON and returns the typed answer', async () => {
    let received: unknown
    server.use(
      http.post(`${MARKET}/environments`, async ({ request }) => {
        received = await request.json()
        return HttpResponse.json(environments[0], { status: 201 })
      }),
    )
    const body = {
      name: 'x',
      type: 'historical_replay' as const,
      universe: 'u',
      instrument_ids: ['0b6d7f3a-1111-4a00-8000-000000000001'],
      start_date: '2020-01-02',
      end_date: '2020-12-31',
      frequency: 'daily' as const,
    }
    const created = await apiPost('/api/market/environments', body)
    expect(received).toEqual(body)
    expect(created.status).toBe('ready')
  })

  it('rejects wrong calls at compile time', () => {
    const never = false as boolean
    if (never) {
      // @ts-expect-error a path the API does not have
      void apiGet('/api/market/nope')
      // @ts-expect-error this route has path parameters, so options with `path` are required
      void apiGet('/api/market/instruments/{instrument_id}/candles')
      // @ts-expect-error the body must match the generated request type
      void apiPost('/api/market/environments', { name: 1 })
      // @ts-expect-error a GET-only path cannot be posted to
      void apiPost('/api/market/health', {})
    }
    expect(never).toBe(false)
  })
})
