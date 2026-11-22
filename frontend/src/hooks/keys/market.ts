// One key factory per service. A key starts with the service, then the resource, then its
// parameters, so invalidating ['market', 'environments'] refreshes the list and every detail.
export const marketKeys = {
  all: ['market'] as const,
  environments: () => [...marketKeys.all, 'environments'] as const,
}
