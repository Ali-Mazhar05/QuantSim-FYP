// Query keys of the simulation service, in the shape every service uses: [service, resource,
// ...params], so invalidating ['simulation', 'runs'] refreshes the list and every detail.
export const simulationKeys = {
  all: ['simulation'] as const,
  runs: () => [...simulationKeys.all, 'runs'] as const,
  runList: (filter: object) => [...simulationKeys.runs(), 'list', filter] as const,
  run: (id: string) => [...simulationKeys.runs(), 'run', id] as const,
  quantiles: (id: string) => [...simulationKeys.runs(), 'quantiles', id] as const,
  calibrations: () => [...simulationKeys.all, 'calibrations'] as const,
  calibration: (id: string) => [...simulationKeys.calibrations(), 'one', id] as const,
  scenarios: () => [...simulationKeys.all, 'scenarios'] as const,
}
