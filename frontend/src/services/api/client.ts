// HTTP client for the QuantSim backend. It finds the API for the environment the page is
// served from, attaches the access token, refreshes it once when it expires (one refresh
// at a time, however many requests are waiting) and reports an unreachable backend
// separately, so the app can fall back to demo mode.

const SITE_PORTS: Record<string, number> = { develop: 8081, test: 8082, acceptance: 8083 }
const REFRESH_KEY = 'qs.refresh_token'

/** Base URL of the backend gateway for the site this page was loaded from. */
export function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (configured) return configured.replace(/\/$/, '')
  const host = window.location.hostname
  if (host === 'localhost' || host === '127.0.0.1') return 'http://localhost:8081'
  // develop.<project>.pages.dev -> DEV, test. -> TEST, acceptance. -> ACC, otherwise PROD
  const port = SITE_PORTS[host.split('.')[0]] ?? 8084
  return `http://localhost:${port}`
}

export class ApiError extends Error {
  readonly status: number
  readonly type: string

  constructor(status: number, type: string, message: string) {
    super(message)
    this.status = status
    this.type = type
  }
}

/** The backend could not be reached at all (not running, or not on this machine). */
export class ApiUnreachableError extends Error {}

let accessToken: string | null = null

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function setSession(access: string, refresh: string): void {
  accessToken = access
  storage()?.setItem(REFRESH_KEY, refresh)
}

export function clearSession(): void {
  accessToken = null
  storage()?.removeItem(REFRESH_KEY)
}

export function storedRefreshToken(): string | null {
  return storage()?.getItem(REFRESH_KEY) ?? null
}

async function send(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(`${apiBaseUrl()}${path}`, { ...init, signal: controller.signal })
  } catch {
    throw new ApiUnreachableError('The QuantSim backend is not reachable from this browser.')
  } finally {
    window.clearTimeout(timer)
  }
}

async function toError(response: Response): Promise<ApiError> {
  let body: { type?: string; detail?: string; title?: string } = {}
  try {
    body = await response.json()
  } catch {
    // not a problem-details body
  }
  return new ApiError(response.status, body.type ?? 'about:blank', body.detail ?? body.title ?? response.statusText)
}

let refreshing: Promise<boolean> | null = null

/** Swap the stored refresh token for a new pair; false when the session has ended. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const token = storedRefreshToken()
    if (!token) return false
    const response = await send(
      '/api/platform/auth/refresh',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: token }) },
      5000,
    )
    if (!response.ok) {
      clearSession()
      return false
    }
    const body: { access_token: string; refresh_token: string } = await response.json()
    setSession(body.access_token, body.refresh_token)
    return true
  })().finally(() => {
    refreshing = null
  })
  return refreshing
}

/** JSON request to the backend with the signed-in user's token. */
export async function apiRequest<T>(path: string, init: RequestInit = {}, timeoutMs = 10_000): Promise<T> {
  const call = () =>
    send(
      path,
      {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          ...init.headers,
        },
      },
      timeoutMs,
    )
  let response = await call()
  if (response.status === 401 && storedRefreshToken() && (await refreshSession())) {
    response = await call()
  }
  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
