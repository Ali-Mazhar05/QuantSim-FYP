import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createEnvironment } from '../services/api/market'
import { marketKeys } from './keys/market'

/** Create an environment; the list every page shows refreshes once it is saved. */
export function useCreateEnvironment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createEnvironment,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: marketKeys.environments() }),
  })
}
