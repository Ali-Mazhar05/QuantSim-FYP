import { http, HttpResponse } from 'msw'
import { candles } from '../fixtures/candles'
import { environments } from '../fixtures/environments'
import { MARKET } from './common'

/** The market service's default answers, each from a fixture. Tests override per case. */
export const marketHandlers = [
  http.get(`${MARKET}/environments`, () => HttpResponse.json(environments)),
  http.get(`${MARKET}/instruments/:id/candles`, () => HttpResponse.json(candles(100))),
  // no replay session yet: the first Play starts one
  http.get(`${MARKET}/replay-sessions`, () => HttpResponse.json([])),
]
