// DEV smoke run (A-FR-20): it gates promotion from DEV to TEST. The deployed site must
// serve its build record, show the sign-in pages, accept a real sign-in and render every
// page the signed-in role may open. Pages the role may not open must send it back to the
// dashboard, as the router does.

import { expect, test } from '@playwright/test'
import { canOpen } from '../../src/demo/permissions'
import type { Role } from '../../src/types'
import { APP_ROUTES, PUBLIC_ROUTES } from './routes'
import { credentials, expectPageRenders, openInApp, signIn, signedInRole, watchPage } from './support'

test('the site serves its build record', async ({ request }) => {
  const response = await request.get('/version.json')
  expect(response.ok(), `/version.json answered ${response.status()}`).toBe(true)
  const record: unknown = await response.json()
  expect(record).toMatchObject({
    version: expect.any(String),
    content_hash: expect.any(String),
    git_sha: expect.any(String),
  })
})

test('the sign-in and emailed-link pages load while signed out', async ({ page }) => {
  const watch = watchPage(page)
  for (const route of PUBLIC_ROUTES) {
    await test.step(route.path, async () => {
      await page.goto(route.path)
      await expectPageRenders(page, route, watch, { inApp: false })
    })
  }
})

test('a real account signs in and every page it may open loads', async ({ page }) => {
  credentials() // fail first, with the reason, when the gate has no account to use
  const watch = watchPage(page)

  await test.step('sign in', async () => {
    await signIn(page)
  })

  const [dashboard, ...pages] = APP_ROUTES
  await test.step(dashboard.path, async () => {
    await expectPageRenders(page, dashboard, watch, { inApp: true })
  })
  const role = (await signedInRole(page)) as Role

  for (const route of pages) {
    await test.step(route.path, async () => {
      await openInApp(page, route.path)
      if (canOpen(role, route.path)) {
        await expectPageRenders(page, route, watch, { inApp: true })
      } else {
        await expect(page, `${role} must not stay on ${route.path}`).toHaveURL(/\/dashboard$/)
        await openInApp(page, dashboard.path)
      }
    })
  }

  await test.step('/ goes to the dashboard', async () => {
    await openInApp(page, '/')
    await expect(page).toHaveURL(/\/dashboard$/)
  })

  // A full reload of a deep link: the host serves the app for any path and the tab keeps
  // its session (the stored refresh token is swapped for a new one)
  const deepLink = APP_ROUTES.find((r) => r.path === '/settings')!
  await test.step(`reload ${deepLink.path}`, async () => {
    await page.goto(deepLink.path)
    await expectPageRenders(page, deepLink, watch, { inApp: true })
  })
})
