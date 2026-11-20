// Typed calls over the generated API types. The path decides the parameters and the response, so
// a field renamed in a service's OpenAPI document breaks the type check wherever it is used.
// Transport (token, refresh, timeouts, problem+json errors) stays in apiRequest.

import type { ApiPaths } from '../generated'
import { apiRequest } from './client'

type Method = 'get' | 'post' | 'put'

/** The paths that offer a method. */
type PathsFor<M extends Method> = {
  [P in keyof ApiPaths]: ApiPaths[P] extends Record<M, infer O> ? ([O] extends [never] ? never : P) : never
}[keyof ApiPaths]

type Operation<P extends keyof ApiPaths, M extends Method> = ApiPaths[P] extends Record<M, infer O> ? O : never
type JsonBody<R> = R extends { content: { 'application/json': infer B } } ? B : never
type OkResponse<O> = O extends { responses: infer R } ? JsonBody<R[Extract<keyof R, 200 | 201 | 202>]> : never
type RequestBody<O> = O extends { requestBody: { content: { 'application/json': infer B } } } ? B : never
type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? Exclude<Q, undefined> : never
type PathOf<O> = O extends { parameters: { path: infer X } } ? X : never

/** Extra request settings: headers such as `Idempotency-Key`, and a signal that cancels the call. */
export interface RequestOptions {
  headers?: Record<string, string>
  signal?: AbortSignal
}

/** Path parameters are required when the route has any; the query is always optional. */
type Args<O> = [PathOf<O>] extends [never]
  ? [options?: { query?: QueryOf<O> } & RequestOptions]
  : [options: { path: PathOf<O>; query?: QueryOf<O> } & RequestOptions]

/** The body, then the options. An operation without a request body takes no body (or undefined). */
type BodyArgs<O> = [RequestBody<O>] extends [never]
  ? [PathOf<O>] extends [never]
    ? [body?: undefined, ...Args<O>]
    : [body: undefined, ...Args<O>]
  : [body: RequestBody<O>, ...Args<O>]

type Scalar = string | number | boolean | null | undefined

/** Fill `{name}` in a route template and append the query; undefined and null values are left out. */
export function buildUrl(
  template: string,
  options: { path?: Record<string, string | number>; query?: Record<string, Scalar> } = {},
): string {
  const url = template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = options.path?.[name]
    if (value === undefined) throw new Error(`Missing path parameter "${name}" for ${template}`)
    return encodeURIComponent(String(value))
  })
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null) query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `${url}?${text}` : url
}

type Loose = { path?: Record<string, string | number>; query?: Record<string, Scalar> } & RequestOptions

function send<T>(method: string, path: string, body: unknown, options: Loose = {}): Promise<T> {
  return apiRequest(buildUrl(path, options), {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    ...(options.headers ? { headers: options.headers } : {}),
    ...(options.signal ? { signal: options.signal } : {}),
  })
}

export function apiGet<P extends PathsFor<'get'>>(
  path: P,
  ...args: Args<Operation<P, 'get'>>
): Promise<OkResponse<Operation<P, 'get'>>> {
  return send('GET', path, undefined, args[0] as Loose)
}

export function apiPost<P extends PathsFor<'post'>>(
  path: P,
  ...args: BodyArgs<Operation<P, 'post'>>
): Promise<OkResponse<Operation<P, 'post'>>> {
  return send('POST', path, args[0], args[1] as Loose)
}

export function apiPut<P extends PathsFor<'put'>>(
  path: P,
  ...args: BodyArgs<Operation<P, 'put'>>
): Promise<OkResponse<Operation<P, 'put'>>> {
  return send('PUT', path, args[0], args[1] as Loose)
}
