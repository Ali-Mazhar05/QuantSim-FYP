import { describe, expect, it } from 'vitest'
import { ApiError, ApiUnreachableError } from '../services/api/client'
import { classifyError, isForbidden } from './apiError'

const api = (status: number, body = {}) => new ApiError(status, 'about:blank', `status ${status}`, body)

describe('classifyError', () => {
  it.each([
    [401, 'unauthenticated'],
    [403, 'forbidden'],
    [404, 'not_found'],
    [409, 'conflict'],
    [422, 'invalid'],
    [429, 'rate_limited'],
    [500, 'server'],
    [503, 'server'],
    [418, 'unknown'],
  ])('maps status %i to %s', (status, kind) => {
    const result = classifyError(api(status))
    expect(result.kind).toBe(kind)
    expect(result.status).toBe(status)
  })

  it('names the fields of a 422', () => {
    const result = classifyError(
      api(422, { errors: [{ location: ['body', 'end_date'], message: 'end_date must be after start_date' }] }),
    )
    expect(result.fieldErrors).toEqual({ end_date: 'end_date must be after start_date' })
  })

  it('reports how long to wait after a 429', () => {
    expect(classifyError(api(429, { retry_after_seconds: 30 })).retryAfterSeconds).toBe(30)
  })

  it('tells an unreachable backend from a failed call', () => {
    const result = classifyError(new ApiUnreachableError())
    expect(result.kind).toBe('unreachable')
    expect(result.status).toBeNull()
  })

  it('handles anything else as unknown, with a message to show', () => {
    const result = classifyError(new TypeError('boom'))
    expect(result.kind).toBe('unknown')
    expect(result.message).not.toBe('')
  })

  it('answers the 403 question directly', () => {
    expect(isForbidden(api(403))).toBe(true)
    expect(isForbidden(api(404))).toBe(false)
  })
})
