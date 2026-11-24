import { test } from '@playwright/test'
import { laneBSpine } from '../dev-smoke/lane-b-spine'

// Lane B's spine (B22); the steps are in dev-smoke/lane-b-spine.ts, shared with the other gate
test('replay, calibrate, simulate and stress on a real environment, and the refusals', async ({ page, request }) => {
  await laneBSpine(page, request)
})
