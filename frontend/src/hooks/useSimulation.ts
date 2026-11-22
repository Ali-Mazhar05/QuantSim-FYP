import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDemoStore } from '../demo/demoState'
import {
  type RunFilter,
  createCalibration,
  createRun,
  getCalibration,
  getQuantiles,
  getRun,
  isFinished,
  listCalibrations,
  listRuns,
  listScenarios,
  stressRun,
} from '../services/api/simulation'
import { classifyError } from './apiError'
import { simulationKeys } from './keys/simulation'

/** How often a running job is asked for: once a second, and never once it has ended. */
export const POLL_MS = 1000

// Every read is idle while signed out and reports a failure as a classified error (a 403 is
// `kind === 'forbidden'`), so a page shows its four states the same way.

export function useRuns(filter: RunFilter = {}) {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.runList(filter),
    queryFn: ({ signal }) => listRuns(filter, { signal }),
    enabled: signedIn,
  })
  return { runs: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

/** One run; while it is queued or running it is read again every second. */
export function useRun(id: string | undefined) {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.run(id ?? ''),
    queryFn: ({ signal }) => getRun(id as string, { signal }),
    enabled: signedIn && Boolean(id),
    refetchInterval: (q) => (q.state.data && isFinished(q.state.data.status) ? false : POLL_MS),
  })
  return { run: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

export function useQuantiles(id: string | undefined, enabled = true) {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.quantiles(id ?? ''),
    queryFn: ({ signal }) => getQuantiles(id as string, undefined, { signal }),
    enabled: signedIn && Boolean(id) && enabled,
  })
  return { quantiles: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

export function useCalibrations() {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.calibrations(),
    queryFn: ({ signal }) => listCalibrations({ signal }),
    enabled: signedIn,
  })
  return { calibrations: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

/** One calibration job, read every second until it has succeeded, been refused or failed. */
export function useCalibration(id: string | undefined) {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.calibration(id ?? ''),
    queryFn: ({ signal }) => getCalibration(id as string, { signal }),
    enabled: signedIn && Boolean(id),
    refetchInterval: (q) => (q.state.data && isFinished(q.state.data.status) ? false : POLL_MS),
  })
  return { calibration: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

export function useScenarios() {
  const signedIn = useDemoStore((s) => s.authenticated)
  const query = useQuery({
    queryKey: simulationKeys.scenarios(),
    queryFn: ({ signal }) => listScenarios({ signal }),
    enabled: signedIn,
  })
  return { scenarios: query.data ?? null, error: query.error ? classifyError(query.error) : null }
}

/** Queue a run. The key makes a double click return the same run instead of a second one. */
export function useCreateRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ body, key }: { body: Parameters<typeof createRun>[0]; key: string }) => createRun(body, key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: simulationKeys.runs() }),
  })
}

export function useCreateCalibration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ body, key }: { body: Parameters<typeof createCalibration>[0]; key: string }) =>
      createCalibration(body, key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: simulationKeys.calibrations() }),
  })
}

export function useStressRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, scenario, key }: { runId: string; scenario: string; key: string }) =>
      stressRun(runId, scenario, key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: simulationKeys.runs() }),
  })
}
