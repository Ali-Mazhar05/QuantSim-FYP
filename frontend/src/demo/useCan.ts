import { useDemoStore } from './demoState'
import { can, type Capability } from './permissions'

/** Whether the role currently shown may do this; controls that need it are disabled.
 *
 * The signed-in account's capabilities, as the backend sent them from /auth/me, are the
 * ceiling: a control the backend would refuse is never offered. The role table only
 * narrows that further while the account previews a lower role. */
export function useCan(capability: Capability): boolean {
  const role = useDemoStore((s) => s.role)
  const granted = useDemoStore((s) => s.account?.capabilities)
  return can(role, capability) && (granted === undefined || granted.includes(capability))
}
