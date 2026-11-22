import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useDemoStore } from '../demo/demoState'
import { clearSession } from '../services/api/client'
import { environments } from '../test/mocks/fixtures/environments'
import { MARKET, problem } from '../test/mocks/handlers'
import { server, setupMockServer } from '../test/mocks/server'
import QueryProvider from './QueryProvider'
import { createQueryClient } from './queryClient'
import { useCreateEnvironment } from './useCreateEnvironment'
import { useEnvironments } from './useEnvironments'

setupMockServer()

function wrapper({ children }: { children: ReactNode }) {
  return <QueryProvider client={createQueryClient()}>{children}</QueryProvider>
}

function signIn(activeEnvironmentId: string | null = null) {
  useDemoStore.setState({ authenticated: true, activeEnvironmentId })
}

beforeEach(() => {
  clearSession()
  useDemoStore.setState({ authenticated: false, activeEnvironmentId: null })
})

describe('useEnvironments', () => {
  it('is loading, then has the environments in the prototype shape, newest as active', async () => {
    signIn()
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    expect(result.current.environments).toBeNull()
    await waitFor(() => expect(result.current.environments).not.toBeNull())
    const [replay] = result.current.environments ?? []
    expect(replay).toMatchObject({
      name: 'Big tech 2020 replay',
      type: 'Historical Replay',
      instruments: ['AAPL', 'MSFT'],
      start: '2020-01-02',
      status: 'Ready',
    })
    expect(result.current.active?.id).toBe(replay?.id)
    expect(result.current.error).toBeNull()
  })

  it('prefers the environment chosen in this session', async () => {
    signIn(environments[1]?.id)
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    await waitFor(() => expect(result.current.active?.name).toBe('Synthetic draft'))
  })

  it('shows the empty state data when there are none', async () => {
    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([])))
    signIn()
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    await waitFor(() => expect(result.current.environments).toEqual([]))
    expect(result.current.active).toBeNull()
  })

  it('reports a failure as a message and no data', async () => {
    server.use(http.get(`${MARKET}/environments`, () => problem(500, 'The market service failed')))
    signIn()
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    await waitFor(() => expect(result.current.error).not.toBeNull())
    expect(result.current.environments).toBeNull()
  })

  it('reports a 403 as an error the page can show', async () => {
    server.use(http.get(`${MARKET}/environments`, () => problem(403, 'Your role may not do this')))
    signIn()
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    await waitFor(() => expect(result.current.error?.kind).toBe('forbidden'))
    expect(result.current.error?.message).toContain('Your role may not do this')
  })

  it('signs the user out when the session has ended (401 after the refresh failed)', async () => {
    server.use(http.get(`${MARKET}/environments`, () => problem(401, 'The session has ended')))
    signIn()
    renderHook(() => useEnvironments(), { wrapper: ({ children }) => <QueryProvider>{children}</QueryProvider> })
    await waitFor(() => expect(useDemoStore.getState().authenticated).toBe(false))
  })

  it('makes no request while signed out', async () => {
    let calls = 0
    server.use(
      http.get(`${MARKET}/environments`, () => {
        calls += 1
        return HttpResponse.json(environments)
      }),
    )
    const { result } = renderHook(() => useEnvironments(), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls).toBe(0)
    expect(result.current.environments).toBeNull()
  })

  it('empties the cache on sign-out so the next user never sees the data', async () => {
    // one provider for the whole test, as the app has one, with pages mounting and unmounting
    const shared = ({ children }: { children: ReactNode }) => (
      <QueryProvider client={client}>{children}</QueryProvider>
    )
    const client = createQueryClient()
    signIn()
    const first = renderHook(() => useEnvironments(), { wrapper: shared })
    await waitFor(() => expect(first.result.current.environments).toHaveLength(2))
    // the provider stays mounted at the app root, so it is the one that hears the sign-out
    act(() => useDemoStore.setState({ authenticated: false }))
    expect(client.getQueryCache().getAll()).toHaveLength(0)

    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([environments[1]])))
    signIn()
    const second = renderHook(() => useEnvironments(), { wrapper: shared })
    expect(second.result.current.environments).toBeNull() // not the previous user's list
    await waitFor(() => expect(second.result.current.environments).toHaveLength(1))
    expect(second.result.current.environments?.[0]?.name).toBe('Synthetic draft')
  })
})

describe('useCreateEnvironment', () => {
  it('refreshes the list once an environment is saved', async () => {
    const rows = [...environments]
    server.use(
      http.get(`${MARKET}/environments`, () => HttpResponse.json(rows)),
      http.post(`${MARKET}/environments`, () => {
        rows.unshift({ ...environments[0]!, id: '6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c99', name: 'New one' })
        return HttpResponse.json(rows[0], { status: 201 })
      }),
    )
    signIn()
    const { result } = renderHook(() => ({ list: useEnvironments(), create: useCreateEnvironment() }), { wrapper })
    await waitFor(() => expect(result.current.list.environments).toHaveLength(2))
    await act(() =>
      result.current.create.mutateAsync({
        name: 'New one',
        type: 'Historical Replay',
        universe: 'Big tech',
        instrumentIds: ['0b6d7f3a-1111-4a00-8000-000000000001'],
        start: '2020-01-02',
        end: '2020-12-31',
      }),
    )
    await waitFor(() => expect(result.current.list.environments).toHaveLength(3))
    expect(result.current.list.environments?.[0]?.name).toBe('New one')
  })
})
