import { defineConfig, devices } from '@playwright/test'

// End-to-end suites that run against a deployed environment (ci/scripts/playwright-gate.sh).
// Each suite is a folder under e2e/; the gate runs one of them inside the pinned Playwright
// image, whose browsers match the @playwright/test version in package.json.
//
//   PLAYWRIGHT_BASE_URL            the website to test, e.g. https://develop.<project>.pages.dev
//   PLAYWRIGHT_JUNIT_OUTPUT_NAME   where the JUnit report goes (the gate sets reports/e2e-<suite>.xml)
//   QS_E2E_USERNAME, QS_E2E_PASSWORD   the account the suites sign in with

const ci = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  // One browser at a time: the suites share one account and the DEV backend runs on a
  // single host behind a tunnel
  fullyParallel: false,
  workers: 1,
  forbidOnly: ci,
  // One retry absorbs a cold Cloudflare edge or a slow first call through the tunnel
  retries: ci ? 1 : 0,
  // A whole suite signs in once and walks every page, so its test needs minutes, not seconds
  timeout: 5 * 60_000,
  expect: { timeout: 15_000 },
  reporter: [['line'], ['junit', { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT_NAME ?? 'reports/e2e.xml' }]],
  outputDir: 'reports/e2e-results',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173',
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // HTTP/1.1 over TCP. With QUIC off the sign-in flake remained (develop build 110): in a
    // browser that earlier tests had used, every API request hung while the same URL
    // answered 200 outside the browser at once, which is a dead pooled HTTP/2 connection
    // to the tunnel that all requests to the host share. On HTTP/1.1 a dead reused socket is
    // retried on a fresh one. The sign-in probe reports it if it still happens (support.ts)
    launchOptions: { args: ['--disable-quic', '--disable-http2'] },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
