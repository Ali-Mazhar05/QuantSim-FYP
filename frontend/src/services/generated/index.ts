// Types generated from each service's OpenAPI document (npm run gen:api). Add a service here
// when its schema.d.ts exists; ApiPaths is the intersection of every service's paths that the
// typed helpers accept (`MarketPaths & TradingPaths`). Not a union: keyof a union keeps only
// the paths every service has, which is none.
import type { components as MarketComponents, paths as MarketPaths } from './market/schema'

export type { MarketComponents, MarketPaths }
export type ApiPaths = MarketPaths
