import { useDemoStore } from './demoState'
import { can, type Capability } from './permissions'

/** Whether the role currently shown may do this; controls that need it are disabled. */
export function useCan(capability: Capability): boolean {
  return can(useDemoStore((s) => s.role), capability)
}
