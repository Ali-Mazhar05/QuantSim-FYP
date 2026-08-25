// Orchestrates the "Run Full Demo" presentation mode: walks the flow state
// machine forward, stage by stage, navigating the router and pausing briefly
// at each stop so the transitions read as a live system rather than a jump-cut.

import type { NavigateFunction } from 'react-router-dom'
import { DEMO_STAGES, useDemoStore } from './demoState'

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function runFullDemo(navigate: NavigateFunction) {
  const { setRunningFullDemo, advanceTo } = useDemoStore.getState()
  setRunningFullDemo(true)

  for (const stage of DEMO_STAGES) {
    if (!useDemoStore.getState().runningFullDemo) break
    navigate(stage.path)
    await wait(650)
    advanceTo(stage.step)
    await wait(950)
  }

  navigate('/dashboard')
  setRunningFullDemo(false)
}

export function stopFullDemo() {
  useDemoStore.getState().setRunningFullDemo(false)
}
