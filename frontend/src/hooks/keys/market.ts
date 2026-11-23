// One key factory per service. A key starts with the service, then the resource, then its
// parameters, so invalidating ['market', 'environments'] refreshes the list and every detail.
export const marketKeys = {
  all: ['market'] as const,
  environments: () => [...marketKeys.all, 'environments'] as const,
  session: (environmentId: string) => [...marketKeys.all, 'replay-session', environmentId] as const,
  instruments: (status: string | null) => [...marketKeys.all, 'instruments', status] as const,
  candles: (id: string, interval: string, from: string, to: string) =>
    [...marketKeys.all, 'candles', id, interval, from, to] as const,
  metrics: (id: string, interval: string, from: string, to: string) =>
    [...marketKeys.all, 'metrics', id, interval, from, to] as const,
}
