import { render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDemoStore } from '../../demo/demoState'
import QueryProvider from '../../hooks/QueryProvider'
import { clearSession } from '../../services/api/client'
import { account } from '../../test/fakeBackend'
import { MARKET, problem } from '../../test/mocks/handlers'
import { server, setupMockServer } from '../../test/mocks/server'
import type { Role } from '../../types'
import MarketEnvironmentsList from './MarketEnvironmentsList'

// B-FR-19, B-NFR-15: the page renders every state on the mock backend, with no real service running
setupMockServer()

function renderPage(role: Role = 'Quant') {
  useDemoStore.getState().startSession(account(role))
  return render(
    <MemoryRouter>
      <QueryProvider>
        <MarketEnvironmentsList />
      </QueryProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => clearSession())
afterEach(() => useDemoStore.getState().logout())

describe('Market Environments page on the mock backend', () => {
  it('shows loading while the list is on its way', () => {
    server.use(http.get(`${MARKET}/environments`, () => delay('infinite')))
    renderPage()
    expect(screen.getByText('Loading environments…')).toBeInTheDocument()
  })

  it('shows the environments the API returns', async () => {
    renderPage()
    expect(await screen.findByText('Big tech 2020 replay')).toBeInTheDocument()
    expect(screen.getByText('Synthetic draft')).toBeInTheDocument()
    expect(screen.queryByText('Loading environments…')).not.toBeInTheDocument()
  })

  it('shows the empty state when there are none', async () => {
    server.use(http.get(`${MARKET}/environments`, () => HttpResponse.json([])))
    renderPage()
    expect(await screen.findByText('No environments yet')).toBeInTheDocument()
  })

  it('shows an error the user can read', async () => {
    server.use(http.get(`${MARKET}/environments`, () => problem(500, 'The market service failed')))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('The market service failed')
  })

  it('shows a 403 as a readable message, not a blank page', async () => {
    server.use(http.get(`${MARKET}/environments`, () => problem(403, 'Your role may not view this')))
    renderPage('Viewer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Your role may not view this')
  })

  it('offers New Environment only to roles that may create one', async () => {
    renderPage('Viewer')
    const viewerButton = await screen.findByRole('button', { name: /new environment/i })
    expect(viewerButton).toBeDisabled()
    expect(viewerButton).toHaveAttribute('title', 'Your role cannot do this')
  })

  it('enables New Environment for a quant', async () => {
    renderPage('Quant')
    expect(await screen.findByRole('button', { name: /new environment/i })).toBeEnabled()
  })
})
