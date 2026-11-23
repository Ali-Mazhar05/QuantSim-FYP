// @vitest-environment node
import { readFileSync } from 'node:fs'
import openapiTS, { astToString } from 'openapi-typescript'
import { describe, expect, it } from 'vitest'

// The committed types must be exactly what the committed OpenAPI document generates. If a service's
// spec changed and `npm run gen:api` was not run, this fails and says which service.
const SERVICES = ['market', 'trading', 'simulation']
const eol = (text: string) => text.replace(/\r\n/g, '\n')

describe('generated API types', () => {
  it.each(SERVICES)('%s schema.d.ts matches its openapi.json', async (service) => {
    const dir = new URL(`./${service}/`, import.meta.url)
    const generated = eol(astToString(await openapiTS(new URL('openapi.json', dir)))).trim()
    const committed = eol(readFileSync(new URL('schema.d.ts', dir), 'utf8'))
    expect(committed, `run "npm run gen:api" in frontend and commit ${service}/schema.d.ts`).toContain(generated)
  })
})
