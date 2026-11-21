import { delay, http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { ApiUnreachableError, clearSession } from './client'
import { server, setupMockServer } from '../../test/mocks/server'
import { MARKET } from '../../test/mocks/handlers'
import { environments } from '../../test/mocks/fixtures/environments'
import { apiGet, apiPost, apiPut, buildUrl } from './typed'

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

const environmentBody = {
  name: 'x',
  type: 'historical_replay' as const,
  universe: 'u',
  instrument_ids: ['0b6d7f3a-1111-4a00-8000-000000000001'],
  start_date: '2020-01-02',
  end_date: '2020-12-31',
  frequency: 'daily' as const,
}

describe('apiGet, apiPost and apiPut', () => {
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
    const created = await apiPost('/api/market/environments', environmentBody)
    expect(received).toEqual(environmentBody)
    expect(created.status).toBe('ready')
  })

  it('posts without a body when the operation takes none', async () => {
    let received = 'not called'
    server.use(
      http.post(`${MARKET}/instruments/:id/retire`, async ({ request, params }) => {
        received = `${params.id} "${await request.text()}"`
        return HttpResponse.json({ id: params.id, status: 'retired' })
      }),
    )
    const retired = await apiPost('/api/market/instruments/{instrument_id}/retire', undefined, {
      path: { instrument_id: 'abc' },
    })
    expect(received).toBe('abc ""')
    expect(retired.status).toBe('retired')
  })

  it('sends extra headers such as Idempotency-Key next to the token', async () => {
    let seen: (string | null)[] = []
    server.use(
      http.post(`${MARKET}/environments`, ({ request }) => {
        seen = [request.headers.get('Idempotency-Key'), request.headers.get('Content-Type')]
        return HttpResponse.json(environments[0], { status: 201 })
      }),
    )
    await apiPost('/api/market/environments', environmentBody, { headers: { 'Idempotency-Key': 'key-1' } })
    expect(seen).toEqual(['key-1', 'application/json'])
  })

  it('stops the request when the signal aborts, without calling the backend unreachable', async () => {
    server.use(http.get(`${MARKET}/environments`, () => delay('infinite')))
    const controller = new AbortController()
    const pending = apiGet('/api/market/environments', { signal: controller.signal })
    controller.abort()
    const error = await pending.catch((e: unknown) => e)
    expect(error).not.toBeInstanceOf(ApiUnreachableError)
    expect((error as Error).name).toBe('AbortError')
  })

  it('puts the body as JSON with the same options', async () => {
    let received: unknown
    server.use(
      http.put(`${MARKET}/environments/:id`, async ({ request, params }) => {
        received = [params.id, request.headers.get('Idempotency-Key'), await request.json()]
        return HttpResponse.json(environments[0])
      }),
    )
    // The market service has no PUT route yet, so the call is made through an untyped view
    const put = apiPut as unknown as (path: string, body: unknown, options: object) => Promise<unknown>
    await put('/api/market/environments/{environment_id}', { name: 'y' }, {
      path: { environment_id: 'e1' },
      headers: { 'Idempotency-Key': 'key-2' },
    })
    expect(received).toEqual(['e1', 'key-2', { name: 'y' }])
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
      // @ts-expect-error this route takes a body, so it cannot be left out
      void apiPost('/api/market/environments')
      // @ts-expect-error this route takes no body
      void apiPost('/api/market/instruments/{instrument_id}/retire', { x: 1 }, { path: { instrument_id: 'a' } })
      // @ts-expect-error header values are strings
      void apiGet('/api/market/environments', { headers: { 'Idempotency-Key': 1 } })
      // @ts-expect-error a path without a PUT route cannot be put to
      void apiPut('/api/market/environments', {})
    }
    expect(never).toBe(false)
  })
})
