import { http, HttpResponse } from 'msw'
import {
  BASE_RUN,
  RUNNING_RUN,
  STRESSED_RUN,
  baseRun,
  calibrations,
  quantiles,
  runningRun,
  runs,
  scenarios,
  stressedRun,
} from '../fixtures/simulation'
import { SIMULATION, problem } from './common'

const byId = { [BASE_RUN]: baseRun, [STRESSED_RUN]: stressedRun, [RUNNING_RUN]: runningRun }

/** The simulation service's default answers, each from a fixture. Tests override per case. */
export const simulationHandlers = [
  http.get(`${SIMULATION}/runs`, () => HttpResponse.json({ items: runs, next_cursor: null })),
  http.get(`${SIMULATION}/runs/:id`, ({ params }) => {
    const run = byId[params.id as keyof typeof byId]
    return run ? HttpResponse.json(run) : problem(404, 'No run has this id.', 'urn:quantsim:problem:not-found')
  }),
  http.get(`${SIMULATION}/runs/:id/quantiles`, ({ params }) =>
    HttpResponse.json(quantiles(params.id as string, params.id === STRESSED_RUN ? 0.8 : 1)),
  ),
  http.get(`${SIMULATION}/calibrations`, () => HttpResponse.json({ items: calibrations, next_cursor: null })),
  http.get(`${SIMULATION}/scenarios`, () => HttpResponse.json(scenarios)),
]
