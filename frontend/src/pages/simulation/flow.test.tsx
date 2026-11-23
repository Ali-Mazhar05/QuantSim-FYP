import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDemoStore } from '../../demo/demoState'
import QueryProvider from '../../hooks/QueryProvider'
import { clearSession } from '../../services/api/client'
import { account } from '../../test/fakeBackend'
import { environments } from '../../test/mocks/fixtures/environments'
import {
  BASE_RUN,
  RUNNING_RUN,
  STRESSED_RUN,
  baseRun,
  calibrations,
  gbmFit,
  runningRun,
  stressedRun,
} from '../../test/mocks/fixtures/simulation'
import { MARKET, SIMULATION, problem } from '../../test/mocks/handlers'
import { server, setupMockServer } from '../../test/mocks/server'
import type { Role } from '../../types'
import ConfigureSimulation from './ConfigureSimulation'
import RunSimulation from './RunSimulation'
import SimulationResults from './SimulationResults'

// B-FR-17, B-NFR-15: Configure, Run and Results on the mock backend, every state, no real service
setupMockServer()

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string, role: Role = 'Quant') {
  useDemoStore.getState().startSession(account(role))
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryProvider>
        <Routes>
          <Route path="/simulation/configure" element={<ConfigureSimulation />} />
          <Route path="/simulation/run/:id" element={<RunSimulation />} />
          <Route path="/simulation/results/:id" element={<SimulationResults />} />
          <Route path="*" element={<Where />} />
        </Routes>
        <Where />
      </QueryProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => clearSession())
afterEach(() => useDemoStore.getState().logout())

const env = environments[0] // two instruments, 2020-01-02 to 2020-12-31
const succeeded = (id: string, instrumentId: string, over: object = {}) => ({
  ...calibrations[0],
  id,
  calibration: { ...gbmFit, instrument_id: instrumentId, ...over },
})

describe('Configure page', () => {
  it('offers the three working models and keeps regime switching visible but off', async () => {
    renderAt('/simulation/configure')
    expect(await screen.findByText('Big tech 2020 replay')).toBeInTheDocument()
    expect(screen.getByTestId('model-gbm')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('model-extended')).toBeDisabled()
    expect(screen.getByText(/not available yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('model-merton'))
    expect(screen.getByTestId('model-merton')).toHaveAttribute('aria-pressed', 'true')
  })

  it('fits each instrument, starts the run with those fits and moves to the run page', async () => {
    const posted: { calibrations: unknown[]; run: unknown; keys: string[] } = { calibrations: [], run: null, keys: [] }
    server.use(
      http.get(`${SIMULATION}/calibrations`, () => HttpResponse.json({ items: [], next_cursor: null })),
      http.post(`${SIMULATION}/calibrations`, async ({ request }) => {
        const body = (await request.json()) as { instrument_id: string }
        posted.calibrations.push(body)
        posted.keys.push(request.headers.get('Idempotency-Key') ?? '')
        return HttpResponse.json(succeeded(`cal-${posted.calibrations.length}`, body.instrument_id), { status: 202 })
      }),
      http.post(`${SIMULATION}/runs`, async ({ request }) => {
        posted.run = await request.json()
        posted.keys.push(request.headers.get('Idempotency-Key') ?? '')
        return HttpResponse.json({ ...runningRun, id: RUNNING_RUN }, { status: 202 })
      }),
    )
    renderAt('/simulation/configure')
    await screen.findByText('Big tech 2020 replay')
    await userEvent.click(screen.getByRole('button', { name: /Run Simulation/ }))
    await waitFor(() => expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent(`/simulation/run/${RUNNING_RUN}`))
    expect(posted.calibrations).toEqual(
      env.instrument_ids.map((id) => ({ instrument_id: id, model: 'gbm', window_start: env.start_date, window_end: env.end_date })),
    )
    expect(posted.run).toEqual({
      model: 'gbm',
      instruments: env.instrument_ids.map((id, i) => ({ instrument_id: id, calibration_id: `cal-${i + 1}` })),
      n_paths: 1000,
      n_steps: 252,
    })
    expect(posted.keys.every((k) => k.length > 8)).toBe(true) // every write carries an Idempotency-Key
  })

  it('reuses a converged fit of the same model and window instead of fitting again', async () => {
    let fitted = 0
    server.use(
      http.get(`${SIMULATION}/calibrations`, () =>
        HttpResponse.json({
          items: env.instrument_ids.map((id, i) => succeeded(`stored-${i}`, id, { window_start: env.start_date, window_end: env.end_date })),
          next_cursor: null,
        }),
      ),
      http.post(`${SIMULATION}/calibrations`, () => {
        fitted += 1
        return HttpResponse.json({}, { status: 500 })
      }),
      http.post(`${SIMULATION}/runs`, async ({ request }) => {
        const body = (await request.json()) as { instruments: { calibration_id: string }[] }
        expect(body.instruments.map((i) => i.calibration_id)).toEqual(['stored-0', 'stored-1'])
        return HttpResponse.json({ ...runningRun }, { status: 202 })
      }),
    )
    renderAt('/simulation/configure')
    expect(await screen.findByText('Fitted')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Run Simulation/ }))
    await waitFor(() => expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent('/simulation/run/'))
    expect(fitted).toBe(0)
  })

  it('says why a model was refused, for which instrument, and stays on the page', async () => {
    server.use(
      http.get(`${SIMULATION}/calibrations`, () => HttpResponse.json({ items: [], next_cursor: null })),
      http.post(`${SIMULATION}/calibrations`, () =>
        HttpResponse.json(
          {
            ...calibrations[0],
            status: 'refused',
            calibration: null,
            refusal: { http_status: 422, code: 'fit_refused', reason: 'not_mean_reverting: ADF p = 0.41' },
          },
          { status: 202 },
        ),
      ),
    )
    renderAt('/simulation/configure')
    await screen.findByText('Big tech 2020 replay')
    await userEvent.click(screen.getByTestId('model-ou'))
    await userEvent.click(screen.getByRole('button', { name: /Run Simulation/ }))
    expect(await screen.findByTestId('configure-problem')).toHaveTextContent('not_mean_reverting: ADF p = 0.41')
    expect(screen.getByTestId('configure-problem')).toHaveTextContent('Ornstein-Uhlenbeck model was refused for AAPL')
    expect(screen.getByRole('button', { name: /Run Simulation/ })).toBeEnabled()
    expect(screen.getByTestId('where')).toHaveTextContent('/simulation/configure')
  })

  it('shows a refused run request in words', async () => {
    server.use(
      http.get(`${SIMULATION}/calibrations`, () =>
        HttpResponse.json({
          items: env.instrument_ids.map((id, i) => succeeded(`stored-${i}`, id, { window_start: env.start_date, window_end: env.end_date })),
          next_cursor: null,
        }),
      ),
      http.post(`${SIMULATION}/runs`, () => problem(422, 'calibration stored-1 did not converge', 'urn:quantsim:problem:invalid-run')),
    )
    renderAt('/simulation/configure')
    await screen.findByText('Fitted')
    await userEvent.click(screen.getByRole('button', { name: /Run Simulation/ }))
    expect(await screen.findByTestId('configure-problem')).toHaveTextContent('did not converge')
  })

  it('tells an analyst why it cannot run, and disables the button', async () => {
    renderAt('/simulation/configure', 'Analyst')
    await screen.findByText('Big tech 2020 replay')
    expect(screen.getByRole('button', { name: /Run Simulation/ })).toBeDisabled()
    expect(screen.getByText('Your role can read simulations but not start one.')).toBeInTheDocument()
  })

  it('says so when there is no environment', async () => {
    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([])))
    renderAt('/simulation/configure')
    expect(await screen.findByText('There is no market environment to simulate yet. Create one first.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run Simulation/ })).toBeDisabled()
  })
})

describe('Run page', () => {
  it('shows the progress of a running run and no chart yet', async () => {
    renderAt(`/simulation/run/${RUNNING_RUN}`)
    expect(await screen.findByTestId('run-percent')).toHaveTextContent('40%')
    expect(screen.getByTestId('run-events')).toHaveTextContent('Generating paths: 40%')
    expect(screen.getByTestId('fan-waiting')).toHaveTextContent('appears when the run completes')
    expect(screen.queryByRole('button', { name: /View Results/ })).not.toBeInTheDocument()
  })

  it('follows a run to completion by polling, then draws the fan and offers the results', async () => {
    let reads = 0
    server.use(
      http.get(`${SIMULATION}/runs/${RUNNING_RUN}`, () => {
        reads += 1
        return HttpResponse.json(reads < 2 ? runningRun : { ...baseRun, id: RUNNING_RUN })
      }),
    )
    renderAt(`/simulation/run/${RUNNING_RUN}`)
    expect(await screen.findByText('Generating Monte Carlo Ensemble', { selector: 'span' })).toBeInTheDocument()
    expect(await screen.findByText('Simulation Complete', undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(await screen.findByTestId('fan-chart')).toBeInTheDocument()
    expect(screen.getByTestId('run-percent')).toHaveTextContent('100%')
    await userEvent.click(screen.getByRole('button', { name: /View Results/ }))
    expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent(`/simulation/results/${RUNNING_RUN}`)
  })

  it('shows a failed run with its reason and a way back', async () => {
    server.use(
      http.get(`${SIMULATION}/runs/${RUNNING_RUN}`, () =>
        HttpResponse.json({ ...runningRun, status: 'failed', progress: 0.2, error: 'invalid_correlation: not symmetric' }),
      ),
    )
    renderAt(`/simulation/run/${RUNNING_RUN}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_correlation: not symmetric')
    await userEvent.click(screen.getByRole('button', { name: /Configure again/ }))
    expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent('/simulation/configure')
  })

  it('shows loading, an unknown run and a 403 in words', async () => {
    server.use(http.get(`${SIMULATION}/runs/${RUNNING_RUN}`, () => delay('infinite')))
    const loading = renderAt(`/simulation/run/${RUNNING_RUN}`)
    expect(screen.getByText('Loading the run…')).toBeInTheDocument()
    loading.unmount()
    server.use(http.get(`${SIMULATION}/runs/${RUNNING_RUN}`, () => problem(404, 'No run has this id.')))
    const missing = renderAt(`/simulation/run/${RUNNING_RUN}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('No run has this id.')
    missing.unmount()
    server.use(http.get(`${SIMULATION}/runs/${RUNNING_RUN}`, () => problem(403, 'Your role may not view this')))
    renderAt(`/simulation/run/${RUNNING_RUN}`, 'Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
  })
})

describe('Results page', () => {
  it('shows every instrument with its price statistics and losses in words', async () => {
    renderAt(`/simulation/results/${BASE_RUN}`)
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header, AAPL, MSFT
    expect(within(rows[1]).getByText('AAPL')).toBeInTheDocument()
    expect(within(rows[1]).getByText('$151.23')).toBeInTheDocument()
    expect(within(rows[1]).getByText('-23.1%')).toBeInTheDocument()
    expect(within(rows[1]).getByText('-31.1%')).toBeInTheDocument()
    expect(await screen.findByTestId('fan-chart')).toBeInTheDocument()
    expect(screen.getByText(/Jump Diffusion · AAPL, MSFT · 1,000 paths · 252 steps/)).toBeInTheDocument()
  })

  it('draws the stressed median over the base fan and links to the stressed run', async () => {
    renderAt(`/simulation/results/${BASE_RUN}`)
    expect(await screen.findByTestId('fan-compare')).toBeInTheDocument()
    expect(screen.getByTestId('compare-note')).toHaveTextContent('stressed copy (flash_crash)')
  })

  it('draws the base median over a stressed run', async () => {
    renderAt(`/simulation/results/${STRESSED_RUN}`)
    expect(await screen.findByTestId('fan-compare')).toBeInTheDocument()
    expect(screen.getByText('Base median')).toBeInTheDocument()
    expect(screen.getByText(/scenario flash_crash/)).toBeInTheDocument()
    expect(screen.queryByText('Stress Scenarios')).not.toBeInTheDocument() // a stressed run is not stressed again
  })

  it('applies a scenario once, with one key, and goes to the stressed run', async () => {
    const seen: { scenario: unknown; key: string | null }[] = []
    server.use(
      http.post(`${SIMULATION}/runs/${BASE_RUN}/scenarios`, async ({ request }) => {
        seen.push({ scenario: await request.json(), key: request.headers.get('Idempotency-Key') })
        return HttpResponse.json({ ...stressedRun, id: STRESSED_RUN, status: 'queued', progress: 0 }, { status: 202 })
      }),
    )
    renderAt(`/simulation/results/${BASE_RUN}`)
    await userEvent.click(await screen.findByTestId('stress-flash_crash'))
    await waitFor(() => expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent(`/simulation/run/${STRESSED_RUN}`))
    expect(seen).toHaveLength(1)
    expect(seen[0].scenario).toEqual({ scenario: 'flash_crash' })
    expect((seen[0].key ?? '').length).toBeGreaterThan(8)
  })

  it('says why a scenario was refused', async () => {
    server.use(
      http.post(`${SIMULATION}/runs/${BASE_RUN}/scenarios`, () =>
        problem(422, 'at_step: the run has 252 steps; the shock is at step 300', 'urn:quantsim:problem:invalid-scenario'),
      ),
    )
    renderAt(`/simulation/results/${BASE_RUN}`)
    await userEvent.click(await screen.findByTestId('stress-vol_spike'))
    expect(await screen.findByRole('alert')).toHaveTextContent('at_step: the run has 252 steps')
  })

  it('disables stress and portfolio actions for a role that lacks them, with words', async () => {
    renderAt(`/simulation/results/${BASE_RUN}`, 'Analyst')
    expect(await screen.findByTestId('stress-flash_crash')).toBeDisabled()
    expect(screen.getByText('Your role can read results but not start a stressed run.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create Portfolio/ })).toBeDisabled()
    expect(screen.getByText('Your role can read results but not create a portfolio.')).toBeInTheDocument()
  })

  it('opens the portfolio form for this run', async () => {
    renderAt(`/simulation/results/${BASE_RUN}`)
    await userEvent.click(await screen.findByRole('button', { name: /Create Portfolio/ }))
    expect(screen.getAllByTestId('where').at(-1)).toHaveTextContent('/trading/portfolios/new')
  })

  it('explains a run that has no results yet', async () => {
    renderAt(`/simulation/results/${RUNNING_RUN}`)
    expect(await screen.findByRole('status')).toHaveTextContent('has not finished')
  })

  it('shows loading, not found and forbidden', async () => {
    server.use(http.get(`${SIMULATION}/runs/${BASE_RUN}`, () => delay('infinite')))
    const loading = renderAt(`/simulation/results/${BASE_RUN}`)
    expect(screen.getByText('Loading the results…')).toBeInTheDocument()
    loading.unmount()
    server.use(http.get(`${SIMULATION}/runs/${BASE_RUN}`, () => problem(404, 'No run has this id.')))
    const missing = renderAt(`/simulation/results/${BASE_RUN}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('No run has this id.')
    missing.unmount()
    server.use(http.get(`${SIMULATION}/runs/${BASE_RUN}`, () => problem(403, 'Your role may not view this')))
    renderAt(`/simulation/results/${BASE_RUN}`, 'Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
  })
})

describe('an address that is not a run id (the prototype opens /simulation/run/1042)', () => {
  it.each(['/simulation/run/1042', '/simulation/results/1042'])('%s says so calmly and asks for nothing', async (path) => {
    let asked = 0
    server.use(http.get(`${SIMULATION}/runs/:id`, () => ((asked += 1), HttpResponse.json({}))))
    renderAt(path)
    expect(await screen.findByText('Run not found')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Simulation #1042')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // the DEV smoke suite fails a page with an alert
    expect(screen.queryByText(/Loading/)).not.toBeInTheDocument()
    expect(asked).toBe(0)
  })

  it('Configure with no environment is a status, not an alert', async () => {
    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([])))
    renderAt('/simulation/configure')
    expect(await screen.findByRole('status')).toHaveTextContent('There is no market environment to simulate yet')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
