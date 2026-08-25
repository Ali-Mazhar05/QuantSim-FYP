import { useDemoModeModal } from '../../demo/notifications'
import Modal from './Modal'

export default function DemoModeModal() {
  const { open, hide } = useDemoModeModal()
  return (
    <Modal open={open} onClose={hide} title="Demo Mode" width="sm">
      <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
        This capability is represented as a POC interaction and will be connected to the backend in the
        implementation phase.
      </p>
      <div className="mt-5 flex justify-end">
        <button
          onClick={hide}
          className="rounded bg-[var(--color-accent)] px-4 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-accent-strong)]"
        >
          Close
        </button>
      </div>
    </Modal>
  )
}
