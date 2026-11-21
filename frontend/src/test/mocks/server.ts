import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { handlers } from './handlers'

export const server = setupServer(...handlers)

/**
 * Opt in from a test file that wants the mock backend with the real network off. A request no
 * handler answers fails the test, so a page can never quietly reach a real service.
 */
export function setupMockServer() {
  beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())
}
