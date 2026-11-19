import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'
import { useDemoStore } from './demo/demoState'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App routing', () => {
  afterEach(() => {
    useDemoStore.getState().logout()
  })

  it('sends a signed-out user from a protected page to the login screen', () => {
    renderAt('/dashboard')
    expect(screen.getByRole('heading', { name: 'QuantSim' })).toBeInTheDocument()
    expect(screen.getByText('Username or email')).toBeInTheDocument()
  })

  it('shows the not found page for an unknown route once signed in', () => {
    useDemoStore.getState().startSession({ username: 'q', name: 'Q', email: 'q@x', role: 'Quant', capabilities: [] })
    renderAt('/does-not-exist')
    expect(screen.getByText('Page not found')).toBeInTheDocument()
  })
})
