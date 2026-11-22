import { expect, type Page, type Request } from '@playwright/test'
import type { PageRoute } from './routes'

/** The account the suite signs in with; the gate passes it in (playwright-gate.sh). */
export function credentials(): { username: string; password: string } {
  const username = process.env.QS_E2E_USERNAME?.trim()
  const password = process.env.QS_E2E_PASSWORD
  const missing = [!username && 'QS_E2E_USERNAME', !password && 'QS_E2E_PASSWORD'].filter(Boolean)
  if (missing.length > 0 || !username || !password) {
    throw new Error(
      `${missing.join(' and ')} not set: the DEV smoke suite signs in with a real account. ` +
        'ci/scripts/playwright-gate.sh sets them (test.admin, whose password is TEST_USERS_PASSWORD ' +
        "in the environment's encrypted secrets); for a run by hand, export both first.",
    )
  }
  return { username, password }
}

/**
 * Watches the browser for what a page that "loads" must not do: throw an uncaught error,
 * or get a server error from the API. Also counts API calls still in flight, so a page is
 * only judged once its data has arrived (or failed).
 */
export function watchPage(page: Page) {
  const problems: string[] = []
  let inFlight = 0
  const isData = (type: string) => type === 'fetch' || type === 'xhr'

  page.on('pageerror', (error) => problems.push(`uncaught error on ${page.url()}: ${error.message}`))
  page.on('request', (request) => {
    if (isData(request.resourceType())) inFlight += 1
  })
  const settle = (type: string) => {
    if (isData(type)) inFlight = Math.max(0, inFlight - 1)
  }
  page.on('requestfinished', (request) => settle(request.resourceType()))
  page.on('requestfailed', (request) => settle(request.resourceType()))
  page.on('response', (response) => {
    if (response.status() >= 500 && isData(response.request().resourceType())) {
      problems.push(`${response.status()} from ${response.request().method()} ${response.url()} on ${page.url()}`)
    }
  })

  return {
    /** Problems seen since the last call, which are then forgotten. */
    take(): string[] {
      return problems.splice(0, problems.length)
    },
    /** Waits until no API call is in flight. */
    async settled(): Promise<void> {
      await expect.poll(() => inFlight, { message: 'API calls still in flight', timeout: 30_000 }).toBe(0)
    },
  }
}

/** Opens a path inside the running app, the way its links do, without reloading the page. */
export async function openInApp(page: Page, path: string): Promise<void> {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate', { state: {} }))
  }, path)
}

/** What the sign-in card says when the browser cannot reach the API (authShared.ts). */
const UNREACHABLE = 'Cannot reach the QuantSim server'

/**
 * Waits until the browser itself can reach the platform's health route at the API address
 * the deploy published in /config.json. The first request a fresh browser sends through the
 * tunnel sometimes fails before the route answers; warming it here keeps that flake out of
 * the sign-in the test is really about.
 *
 * When the browser never gets through, the error says why: what each attempt saw (the HTTP
 * status, or the fetch error), the network errors Chromium reported for those requests
 * (net::ERR_..., which fetch hides behind "Failed to fetch"), and whether the same URL
 * answers outside the browser, from Playwright's own HTTP client. That tells a stuck
 * browser session from a tunnel or API that is down.
 */
export async function warmUpApi(page: Page, timeoutMs = 60_000): Promise<void> {
  const netErrors: string[] = []
  const onFailed = (request: Request) => {
    if (request.url().includes('/api/platform/health') || request.url().endsWith('/config.json')) {
      netErrors.push(`${request.url()}: ${request.failure()?.errorText ?? 'failed'}`)
    }
  }
  page.on('requestfailed', onFailed)
  const seen: string[] = []
  let healthUrl = ''
  try {
    const deadline = Date.now() + timeoutMs
    for (let attempt = 1; Date.now() < deadline; attempt += 1) {
      const probe = await page.evaluate(async () => {
        let url = '/config.json'
        try {
          const config = await fetch(url, { cache: 'no-store' })
          if (!config.ok) return { ok: false, url, what: `HTTP ${config.status}` }
          const api = String(((await config.json()) as { apiBaseUrl?: string }).apiBaseUrl ?? '').replace(/\/$/, '')
          url = `${api}/api/platform/health`
          const health = await fetch(url, { cache: 'no-store' })
          return { ok: health.ok, url, what: `HTTP ${health.status}` }
        } catch (error) {
          return { ok: false, url, what: String(error) }
        }
      })
      if (probe.ok) return
      healthUrl = probe.url.startsWith('http') ? probe.url : healthUrl
      seen.push(`attempt ${attempt}: ${probe.url} ${probe.what}`)
      await page.waitForTimeout(Math.min(1_000 * attempt, 3_000))
    }
    let outside = 'not tried (the API address was never read)'
    if (healthUrl) {
      try {
        outside = `HTTP ${(await page.request.get(healthUrl, { timeout: 10_000 })).status()}`
      } catch (error) {
        outside = String(error).split('\n')[0]
      }
    }
    const unique = (items: string[]) => [...new Set(items)].slice(-5)
    throw new Error(
      [
        `the browser could not reach the API in ${timeoutMs / 1000}s`,
        `  last attempts: ${seen.slice(-3).join(' | ')}`,
        `  browser network errors: ${unique(netErrors).join(' | ') || 'none reported'}`,
        `  the same URL outside the browser: ${outside}`,
      ].join('\n'),
    )
  } finally {
    page.off('requestfailed', onFailed)
  }
}

/** Signs in through the real sign-in page and waits for the dashboard. */
export async function signIn(page: Page): Promise<void> {
  const { username, password } = credentials()
  await page.goto('/login')
  await warmUpApi(page)

  const notice = page.getByRole('alert')
  const app = page.getByRole('main')
  // One more try only when the API could not be reached; a refused sign-in fails at once
  for (let attempt = 1; ; attempt += 1) {
    await page.getByLabel('Username or email').fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByRole('button', { name: 'Sign In' }).click()

    // A refused sign-in shows a notice on the card (or another card, such as "verify your
    // email first") instead of opening the app
    await expect(app.or(notice).or(page.getByText('Back to sign in')).first()).toBeVisible({ timeout: 30_000 })
    if (await app.isVisible()) break
    const reason = (await notice.isVisible()) ? await notice.innerText() : await page.locator('h1').innerText()
    if (attempt < 2 && reason.includes(UNREACHABLE)) {
      await warmUpApi(page)
      continue
    }
    throw new Error(`sign-in as ${username} did not open the app: ${reason}`)
  }
  await expect(page).toHaveURL(/\/dashboard$/)
}

/** The role the signed-in account works as, from the dashboard greeting. */
export async function signedInRole(page: Page): Promise<string> {
  const greeting = await page.getByRole('main').getByRole('heading', { level: 1 }).first().innerText()
  const role = /, (Viewer|Analyst|Quant|Admin)$/.exec(greeting.trim())?.[1]
  if (!role) throw new Error(`cannot tell the signed-in role from the dashboard greeting "${greeting}"`)
  return role
}

/** The page at `route` shows its heading and no error state once its data has loaded. */
export async function expectPageRenders(
  page: Page,
  route: PageRoute,
  watch: ReturnType<typeof watchPage>,
  { inApp }: { inApp: boolean },
): Promise<void> {
  const region = inApp ? page.getByRole('main') : page.locator('body')
  await expect(page, `${route.path} sent the browser elsewhere`).toHaveURL(new RegExp(`${escapeRegExp(route.path)}$`))
  await expect(region.getByRole('heading', { level: 1 }).first(), `${route.path} heading`).toHaveText(route.heading)
  await watch.settled()
  await expect(region.getByText('Loading…'), `${route.path} is still loading`).toHaveCount(0)
  await expect(region.getByText('Page not found'), `${route.path} is not a known page`).toHaveCount(0)
  const alerts = region.getByRole('alert')
  if ((await alerts.count()) > 0) {
    throw new Error(`${route.path} shows an error: ${(await alerts.allInnerTexts()).join(' | ')}`)
  }
  const problems = watch.take()
  if (problems.length > 0) throw new Error(problems.join('\n'))
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
