// A fake platform API for tests: routes are "METHOD /path" under /api/platform, and every
// call is recorded so a test can check what was (or was not) sent.

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App'
import type { SignedInUser } from '../services/api/platform'
import type { Role } from '../types'
import LocationProbe from './LocationProbe'

type Handler = (body: Record<string, unknown> | undefined, url: URL) => Response | Promise<Response>

export interface Call {
  method: string
  path: string
  body: Record<string, unknown> | undefined
  authorization: string | null
}

export function json(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function problem(status: number, type: string, detail: string, extra: Record<string, unknown> = {}): Response {
  return json(status, { type, title: 'Problem', status, detail, ...extra })
}

export function fakeBackend(routes: Record<string, Handler>) {
  const calls: Call[] = []
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input)
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined
    const headers = new Headers(init?.headers)
    const path = url.pathname.replace(/^\/api\/platform/, '')
    calls.push({ method, path, body, authorization: headers.get('Authorization') })
    const handler = routes[`${method} ${path}`]
    return handler ? handler(body, url) : json(404, { detail: 'Not found' })
  })
  vi.stubGlobal('fetch', fetch)
  return { fetch, calls }
}

export function unreachableBackend() {
  const fetch = vi.fn(async () => Promise.reject(new TypeError('Failed to fetch')))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

/** The whole app at a path, with the current route shown in `data-testid="location"`. */
export function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  )
}

export function account(role: Role, username = `${role.toLowerCase()}.user`): SignedInUser {
  return { username, name: `${role} User`, email: `${username}@quantsim.dev`, role, capabilities: [] }
}
