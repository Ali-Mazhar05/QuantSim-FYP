// Lightweight toast notification store used for mock async feedback
// ("Report export queued", "Alert dismissed", etc.) across the POC.

import { create } from 'zustand'

export interface Toast {
  id: string
  title: string
  tone: 'info' | 'success' | 'warning'
}

interface NotificationState {
  toasts: Toast[]
  push: (title: string, tone?: Toast['tone']) => void
  dismiss: (id: string) => void
}

let counter = 0

export const useNotifications = create<NotificationState>((set) => ({
  toasts: [],
  push: (title, tone = 'info') => {
    counter += 1
    const id = `toast-${counter}`
    set((s) => ({ toasts: [...s.toasts, { id, title, tone }] }))
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 3200)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

interface DemoModeModalState {
  open: boolean
  show: () => void
  hide: () => void
}

export const useDemoModeModal = create<DemoModeModalState>((set) => ({
  open: false,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
}))
