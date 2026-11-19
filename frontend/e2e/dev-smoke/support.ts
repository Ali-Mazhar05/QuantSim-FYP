import { expect, type Page } from '@playwright/test'
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

/** Signs in through the real sign-in page and waits for the dashboard. */
export async function signIn(page: Page): Promise<void> {
  const { username, password } = credentials()
  await page.goto('/login')
  await page.getByLabel('Username or email').fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()

  // A refused sign-in shows a notice on the card (or another card, such as "verify your
  // email first") instead of opening the app
  const notice = page.getByRole('alert')
  const app = page.getByRole('main')
  await expect(app.or(notice).or(page.getByText('Back to sign in')).first()).toBeVisible({ timeout: 30_000 })
  if (!(await app.isVisible())) {
    const reason = (await notice.isVisible()) ? await notice.innerText() : await page.locator('h1').innerText()
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
