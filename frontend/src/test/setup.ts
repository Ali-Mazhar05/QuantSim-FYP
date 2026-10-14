import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// findBy* and waitFor wait up to 1 s by default, too short on a busy CI machine
configure({ asyncUtilTimeout: 10_000 })

afterEach(() => {
  cleanup()
})
