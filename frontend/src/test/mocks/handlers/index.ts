import { marketHandlers } from './market'

// One file per service: a lane edits its own file and adds one line here.
export { MARKET, problem } from './common'

/** The default mock backend. Tests override per case. */
export const handlers = [...marketHandlers]
