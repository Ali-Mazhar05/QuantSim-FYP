// Lane A demo spine on DEV (I2-62), over the demo environment bundled with the Trading
// service; the steps are in spine.ts. TEST runs the same spine on a real replay
// environment (e2e/demo-spine).

import { test } from '@playwright/test'
import { laneASpine } from './spine'

/** The demo environment shipped with the Trading service: two symbols, ten sessions. */
const DEMO_ENVIRONMENT = '5d0c6c1e-7a14-4a14-8a14-000000000001'

test('a momentum portfolio runs with costs and slippage, rebuilds identical and reruns to the same hash', async ({
  page,
  request,
}) => {
  await laneASpine(page, request, DEMO_ENVIRONMENT)
})
