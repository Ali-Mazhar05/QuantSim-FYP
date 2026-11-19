import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('apiBaseUrl', () => {
  it('uses the public API address from the deployed config.json', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ apiBaseUrl: 'https://api-dev.example.com/' }))),
    )
    const client = await import('./client')

    await client.loadRuntimeConfig()

    expect(client.apiBaseUrl()).toBe('https://api-dev.example.com')
  })

  it('falls back to the local gateway when there is no config.json', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('missing', { status: 404 })))
    const client = await import('./client')

    await client.loadRuntimeConfig()

    expect(client.apiBaseUrl()).toBe('http://localhost:8081')
  })

  it('falls back when config.json cannot be fetched at all', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('offline'))))
    const client = await import('./client')

    await client.loadRuntimeConfig()

    expect(client.apiBaseUrl()).toBe('http://localhost:8081')
  })
})
