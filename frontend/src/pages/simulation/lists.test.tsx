import { render, screen, waitFor, within } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDemoStore } from '../../demo/demoState'
import QueryProvider from '../../hooks/QueryProvider'
import { clearSession } from '../../services/api/client'
import { account } from '../../test/fakeBackend'
import { SIMULATION, problem } from '../../test/mocks/handlers'
import { server, setupMockServer } from '../../test/mocks/server'
import type { Role } from '../../types'
import Calibrations from './Calibrations'
import Models from './Models'
import SimulationsList from './SimulationsList'

// B-FR-17, B-NFR-15: each page renders loading, data, empty, error and 403 on the mock backend
setupMockServer()

function renderPage(page: ReactNode, role: Role = 'Quant') {
  useDemoStore.getState().startSession(account(role))
  return render(
    <MemoryRouter>
      <QueryProvider>{page}</QueryProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => clearSession())
afterEach(() => useDemoStore.getState().logout())

describe('Calibrations page', () => {
  it('shows loading, then each stored fit with its parameters and convergence in words', async () => {
    server.use(http.get(`${SIMULATION}/calibrations`, async () => {
      await delay(20)
      return HttpResponse.json({ items: (await import('../../test/mocks/fixtures/simulation')).calibrations, next_cursor: null })
    }))
    renderPage(<Calibrations />)
    expect(screen.getByText('Loading calibrations…')).toBeInTheDocument()
    expect(await screen.findByText('AAPL · GBM')).toBeInTheDocument()
    expect(screen.getByText('mu 0.620 · sigma 0.490')).toBeInTheDocument()
    expect(screen.getByText('Converged')).toBeInTheDocument()
    expect(screen.getByText('Did not converge')).toBeInTheDocument()
    expect(screen.getByText('MSFT · Ornstein-Uhlenbeck')).toBeInTheDocument()
  })

  it('shows the empty state, an error and a 403 in words', async () => {
    server.use(http.get(`${SIMULATION}/calibrations`, () => HttpResponse.json({ items: [], next_cursor: null })))
    const first = renderPage(<Calibrations />)
    expect(await screen.findByText('No calibrations yet')).toBeInTheDocument()
    first.unmount()
    server.use(http.get(`${SIMULATION}/calibrations`, () => problem(500, 'The simulation service failed')))
    const second = renderPage(<Calibrations />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The simulation service failed')
    second.unmount()
    server.use(http.get(`${SIMULATION}/calibrations`, () => problem(403, 'Your role may not view this')))
    renderPage(<Calibrations />, 'Viewer')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Not allowed: Your role may not view this')
    expect(alert).toHaveAttribute('data-kind', 'forbidden')
  })

  it('follows the cursor to the second page', async () => {
    const { calibrations } = await import('../../test/mocks/fixtures/simulation')
    server.use(
      http.get(`${SIMULATION}/calibrations`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        return cursor
          ? HttpResponse.json({ items: [calibrations[1]], next_cursor: null })
          : HttpResponse.json({ items: [calibrations[0]], next_cursor: 'next' })
      }),
    )
    renderPage(<Calibrations />)
    expect(await screen.findByText('MSFT · Ornstein-Uhlenbeck')).toBeInTheDocument()
    expect(screen.getByText('AAPL · GBM')).toBeInTheDocument()
  })
})

describe('Models page', () => {
  it('counts the runs of each model and keeps regime switching visible as Extended', async () => {
    renderPage(<Models />)
    await waitFor(() => expect(screen.getByTestId('usage-merton')).toHaveTextContent('1 run'))
    expect(screen.getByTestId('usage-gbm')).toHaveTextContent('3 runs')
    expect(screen.getByTestId('usage-ou')).toHaveTextContent('0 runs')
    expect(screen.getByTestId('usage-extended')).toHaveTextContent('not available yet')
    expect(screen.getByText('Regime Switching')).toBeInTheDocument()
  })

  it('shows an error in words and still lists the models', async () => {
    server.use(http.get(`${SIMULATION}/runs`, () => problem(403, 'Your role may not view this')))
    renderPage(<Models />, 'Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
    expect(screen.getByText('GBM')).toBeInTheDocument()
  })
})

describe('Simulations page', () => {
  it('lists the runs with scenario and status in words', async () => {
    renderPage(<SimulationsList />)
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(5) // header and four runs
    expect(within(table).getByText('flash_crash')).toBeInTheDocument()
    expect(within(table).getByText('Running')).toBeInTheDocument()
    expect(within(table).getByText('Failed')).toBeInTheDocument()
    expect(within(table).getByText('AAPL, MSFT')).toBeInTheDocument()
  })

  it('shows loading, empty, error and 403', async () => {
    server.use(http.get(`${SIMULATION}/runs`, () => delay('infinite')))
    const loading = renderPage(<SimulationsList />)
    expect(screen.getByText('Loading simulations…')).toBeInTheDocument()
    loading.unmount()
    server.use(http.get(`${SIMULATION}/runs`, () => HttpResponse.json({ items: [], next_cursor: null })))
    const empty = renderPage(<SimulationsList />)
    expect(await screen.findByText('No simulations yet')).toBeInTheDocument()
    empty.unmount()
    server.use(http.get(`${SIMULATION}/runs`, () => problem(403, 'Your role may not view this')))
    renderPage(<SimulationsList />, 'Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
  })

  it('tells a role that cannot launch why New Simulation is off', async () => {
    renderPage(<SimulationsList />, 'Analyst')
    expect(await screen.findByRole('button', { name: /New Simulation/ })).toBeDisabled()
    expect(screen.getByText('Your role can read simulations but not start one.')).toBeInTheDocument()
  })
})
