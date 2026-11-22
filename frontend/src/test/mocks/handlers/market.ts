import { http, HttpResponse } from 'msw'
import { environments } from '../fixtures/environments'
import { MARKET } from './common'

/** The market service's default answers, each from a fixture. Tests override per case. */
export const marketHandlers = [http.get(`${MARKET}/environments`, () => HttpResponse.json(environments))]
