import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fireEvent } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDemoStore } from '../../demo/demoState'
import QueryProvider from '../../hooks/QueryProvider'
import { clearSession } from '../../services/api/client'
import type { ReplaySession } from '../../services/api/replay'
import { account } from '../../test/fakeBackend'
import { dayOf } from '../../test/mocks/fixtures/candles'
import { environments } from '../../test/mocks/fixtures/environments'
import { MARKET, problem } from '../../test/mocks/handlers'
import { server, setupMockServer } from '../../test/mocks/server'
import type { Role } from '../../types'
import Replay from './Replay'

// B-FR-06, B-FR-17, B-NFR-15: the Replay page follows the server's clock; every call is the right one
setupMockServer()

const env = environments[0]
const FINGERPRINT = 'xxh3:3f9a1c0e5b7d2a48c6e10f93b5d7a2c1'

function session(over: Partial<ReplaySession> = {}): ReplaySession {
  return {
    id: '3c5e8b1a-6f2d-4a7e-9b10-1d2e3f4a5b6c',
    environment_id: env.id,
    created_by: '9d1e5c7b-2222-4b00-8000-000000000001',
    created_at: '2026-11-22T10:00:00Z',
    updated_at: '2026-11-22T10:00:00Z',
    server_time: '2026-11-22T10:00:05Z',
    state: 'paused',
    speed: 1,
    position: 0,
    session_count: 100,
    session_date: dayOf(0),
    finished: false,
    source_fingerprint: FINGERPRINT,
    current_fingerprint: FINGERPRINT,
    ...over,
  }
}

function renderPage(role: Role = 'Quant') {
  useDemoStore.getState().startSession(account(role))
  return render(
    <MemoryRouter>
      <QueryProvider>
        <Replay />
      </QueryProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => clearSession())
afterEach(() => useDemoStore.getState().logout())

describe('Replay page on the mock backend', () => {
  it('shows the session the server holds, so a reload resumes where it was', async () => {
    server.use(http.get(`${MARKET}/replay-sessions`, () => HttpResponse.json([session({ position: 41, session_date: dayOf(41) })])))
    renderPage()
    expect(await screen.findByText(new RegExp(`Session 42 / 100 · ${dayOf(41)}`))).toBeInTheDocument()
    expect(screen.getByTestId('replay-seek')).toHaveValue('41')
    expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Play')
  })

  it('with no session starts one on Play: it activates the environment, creates the session and plays', async () => {
    const calls: string[] = []
    server.use(
      http.post(`${MARKET}/environments/${env.id}/activate`, () => {
        calls.push('activate')
        return HttpResponse.json({ environment_id: env.id, status: 'active', source_fingerprint: FINGERPRINT, missing_session_count: 0, activated_by: 'u', activated_at: '2026-11-22T10:00:00Z' })
      }),
      http.post(`${MARKET}/replay-sessions`, async ({ request }) => {
        calls.push(`create ${JSON.stringify(await request.json())}`)
        return HttpResponse.json(session(), { status: 201 })
      }),
      http.post(`${MARKET}/replay-sessions/:id/control`, async ({ request }) => {
        calls.push(`control ${JSON.stringify(await request.json())}`)
        return HttpResponse.json(session({ state: 'playing' }))
      }),
    )
    renderPage()
    await screen.findByText(/Session 1 \/ 100/)
    await userEvent.click(screen.getByTestId('replay-toggle'))
    await waitFor(() => expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Pause'))
    expect(calls).toEqual(['activate', `create ${JSON.stringify({ environment_id: env.id, speed: 1 })}`, 'control {"action":"play"}'])
  })

  it('sends pause, speed and seek to the session and shows the answer', async () => {
    const sent: unknown[] = []
    let current = session({ state: 'playing', position: 10, session_date: dayOf(10) })
    server.use(
      http.get(`${MARKET}/replay-sessions`, () => HttpResponse.json([current])),
      http.post(`${MARKET}/replay-sessions/:id/control`, async ({ request }) => {
        const body = (await request.json()) as { action: string; speed?: 1 | 5 | 20; index?: number }
        sent.push(body)
        current = {
          ...current,
          state: body.action === 'pause' ? 'paused' : current.state,
          speed: body.speed ?? current.speed,
          position: body.index ?? current.position,
          session_date: dayOf(body.index ?? current.position),
        }
        return HttpResponse.json(current)
      }),
    )
    renderPage()
    expect(await screen.findByTestId('replay-toggle')).toHaveTextContent('Pause')
    await userEvent.click(screen.getByTestId('replay-speed-20'))
    await waitFor(() => expect(screen.getByTestId('replay-speed-20')).toHaveAttribute('aria-pressed', 'true'))
    await userEvent.click(screen.getByTestId('replay-toggle'))
    await waitFor(() => expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Play'))
    const seek = screen.getByTestId('replay-seek')
    fireEvent.change(seek, { target: { value: '60' } })
    expect(screen.getByTestId('replay-position')).toHaveTextContent('Session 61 / 100') // while it is held
    fireEvent.pointerUp(seek)
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent(`Session 61 / 100 · ${dayOf(60)}`))
    expect(sent).toEqual([{ action: 'speed', speed: 20 }, { action: 'pause' }, { action: 'seek', index: 60 }])
  })

  it('follows a playing session by polling the server position', async () => {
    let reads = 0
    server.use(
      http.get(`${MARKET}/replay-sessions`, () => {
        reads += 1
        const position = Math.min(5 + reads * 10, 99)
        return HttpResponse.json([session({ state: 'playing', speed: 5, position, session_date: dayOf(position) })])
      }),
    )
    renderPage()
    expect(await screen.findByText(/Session 16 \/ 100/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('Session 26 / 100'), { timeout: 3000 })
  })

  it('shows a finished session and offers Play again', async () => {
    server.use(
      http.get(`${MARKET}/replay-sessions`, () =>
        HttpResponse.json([session({ state: 'playing', position: 99, session_date: dayOf(99), finished: true })]),
      ),
    )
    renderPage()
    expect(await screen.findByText(/Session 100 \/ 100/)).toHaveTextContent('finished')
    expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Play')
  })

  it('tells a viewer why the controls are off and still shows the server position', async () => {
    server.use(http.get(`${MARKET}/replay-sessions`, () => HttpResponse.json([session({ position: 3, session_date: dayOf(3) })])))
    renderPage('Viewer')
    expect(await screen.findByText(/Session 4 \/ 100/)).toBeInTheDocument()
    expect(screen.getByTestId('replay-toggle')).toBeDisabled()
    expect(screen.getByTestId('replay-speed-5')).toBeDisabled()
    expect(screen.getByTestId('replay-seek')).toBeDisabled()
    expect(screen.getByTestId('replay-readonly')).toHaveTextContent('can watch a replay but not control it')
  })

  it('warns when the stored data changed since activation', async () => {
    server.use(
      http.get(`${MARKET}/replay-sessions`, () => HttpResponse.json([session({ current_fingerprint: 'xxh3:00000000000000000000000000000000' })])),
    )
    renderPage()
    expect(await screen.findByRole('status')).toHaveTextContent('The stored data has changed since this environment was activated.')
  })

  it('shows what the server refused, in words', async () => {
    server.use(
      http.post(`${MARKET}/replay-sessions`, () => problem(409, 'The environment is not active', 'urn:quantsim:problem:environment-not-active')),
      http.post(`${MARKET}/environments/${env.id}/activate`, () => problem(422, 'bars without adjusted prices: AAPL (3)', 'urn:quantsim:problem:missing-adjusted-prices')),
    )
    renderPage()
    await screen.findByText(/Session 1 \/ 100/)
    await userEvent.click(screen.getByTestId('replay-toggle'))
    expect(await screen.findByRole('alert')).toHaveTextContent('bars without adjusted prices: AAPL (3)')
    expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Play')
  })

  it('shows loading, the empty state and the error states', async () => {
    server.use(http.get(`${MARKET}/environments`, () => delay('infinite')))
    const loading = renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    loading.unmount()
    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([])))
    const empty = renderPage()
    expect(await screen.findByText('No environment yet')).toBeInTheDocument()
    empty.unmount()
    server.use(http.get(`${MARKET}/environments`, () => problem(403, 'Your role may not view this')))
    const forbidden = renderPage('Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
    forbidden.unmount()
    server.use(
      http.get(`${MARKET}/environments`, () => HttpResponse.json(environments)),
      http.get(`${MARKET}/replay-sessions`, () => problem(500, 'The market service failed')),
    )
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('The market service failed')
  })
})
