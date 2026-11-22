import { marketHandlers } from './market'
import { simulationHandlers } from './simulation'

// One file per service: a lane edits its own file and adds one line here.
export { MARKET, SIMULATION, problem } from './common'

/** The default mock backend. Tests override per case. */
export const handlers = [...marketHandlers, ...simulationHandlers]
