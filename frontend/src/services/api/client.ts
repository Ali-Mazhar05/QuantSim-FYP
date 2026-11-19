// HTTP client for the QuantSim backend. It finds the API for the environment the page is
// served from, attaches the access token, refreshes it once when it expires (one refresh
// at a time, however many requests are waiting) and reports an unreachable backend
// separately, so the sign-in page can say the server cannot be reached.

const SITE_PORTS: Record<string, number> = { develop: 8081, test: 8082, acceptance: 8083 }
const REFRESH_KEY = 'qs.refresh_token'

let runtimeApiBase: string | null = null

/** Reads /config.json, which each deploy writes with the environment's public API
 * address. Without it (local development) the address is derived from the hostname. */
export async function loadRuntimeConfig(): Promise<void> {
  try {
    const response = await fetch('/config.json', { cache: 'no-store' })
    if (!response.ok) return
    const body: { apiBaseUrl?: unknown } = await response.json()
    if (typeof body.apiBaseUrl === 'string' && body.apiBaseUrl) {
      runtimeApiBase = body.apiBaseUrl.replace(/\/$/, '')
    }
  } catch {
    // no config: fall back to the address derived from the hostname
  }
}

/** Base URL of the backend gateway for the site this page was loaded from. */
export function apiBaseUrl(): string {
  if (runtimeApiBase) return runtimeApiBase
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (configured) return configured.replace(/\/$/, '')
  const host = window.location.hostname
  if (host === 'localhost' || host === '127.0.0.1') return 'http://localhost:8081'
  // develop.<project>.pages.dev -> DEV, test. -> TEST, acceptance. -> ACC, otherwise PROD
  const port = SITE_PORTS[host.split('.')[0]] ?? 8084
  return `http://localhost:${port}`
}

/** A problem+json body: type, title, status and detail plus any extra fields. */
export type ProblemBody = Record<string, unknown>

export class ApiError extends Error {
  readonly status: number
  readonly type: string
  /** The whole problem body, for extras such as `retry_after_seconds` or `requested_role`. */
  readonly body: ProblemBody

  constructor(status: number, type: string, message: string, body: ProblemBody = {}) {
    super(message)
    this.status = status
    this.type = type
    this.body = body
  }

  /** Seconds to wait before trying again (429 answers), when the server said. */
  get retryAfterSeconds(): number | null {
    const value = this.body.retry_after_seconds
    return typeof value === 'number' && value >= 0 ? value : null
  }

  /** Field name -> first message, from a 422 body's `errors` (location ends with the field). */
  get fieldErrors(): Record<string, string> {
    const errors = this.body.errors
    const result: Record<string, string> = {}
    if (!Array.isArray(errors)) return result
    for (const entry of errors as { location?: unknown[]; message?: unknown }[]) {
      const location = Array.isArray(entry?.location) ? entry.location : []
      const field = [...location].reverse().find((part) => typeof part === 'string' && part !== 'body')
      if (typeof field === 'string' && typeof entry.message === 'string' && !(field in result)) {
        result[field] = entry.message
      }
    }
    return result
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
  let body: ProblemBody = {}
  try {
    const parsed: unknown = await response.json()
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) body = parsed as ProblemBody
  } catch {
    // not a problem-details body
  }
  const text = (key: string) => (typeof body[key] === 'string' ? (body[key] as string) : undefined)
  return new ApiError(response.status, text('type') ?? 'about:blank', text('detail') ?? text('title') ?? response.statusText, body)
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
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** JSON POST to a public route: no token is sent and no refresh is tried. */
export async function publicRequest<T>(path: string, body: unknown, timeoutMs = 10_000): Promise<T> {
  const response = await send(
    path,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    timeoutMs,
  )
  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}
