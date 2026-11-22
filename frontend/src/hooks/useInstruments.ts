import { useQuery } from '@tanstack/react-query'
import { listInstruments } from '../services/api/market'
import { marketKeys } from './keys/market'

/** The instruments with their latest price and change. */
export function useInstruments(status: 'active' | 'retired' | null = 'active') {
  return useQuery({ queryKey: marketKeys.instruments(status), queryFn: () => listInstruments(status) })
}
