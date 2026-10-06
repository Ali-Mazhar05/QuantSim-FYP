import { useCallback, useLayoutEffect, useRef, useState } from 'react'

// Reports the live content width of an element so a chart can be drawn at its
// container's real size instead of a hard-coded one. Charts that size
// themselves fill the panel they sit in - no dead gutters on a wide screen,
// and no distortion from stretching a fixed viewBox.
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)

  const measure = useCallback((node: T | null) => {
    if (node) setWidth(node.clientWidth)
  }, [])

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    measure(node)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => measure(node))
    ro.observe(node)
    return () => ro.disconnect()
  }, [measure])

  return [ref, width] as const
}
