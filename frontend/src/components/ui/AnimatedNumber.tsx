import { useEffect, useRef, useState } from 'react'
import { useInView } from 'framer-motion'

interface Props {
  value: number
  /** Formatter applied to the interpolated value on every frame. */
  format?: (n: number) => string
  /** Animation duration in milliseconds. */
  duration?: number
  className?: string
}

const EASE_OUT = (t: number) => 1 - Math.pow(1 - t, 3)

/**
 * Smoothly counts up/down to `value` whenever it changes (and on first view).
 * Falls back to instant display when reduced motion is preferred.
 */
export default function AnimatedNumber({ value, format, duration = 900, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '-40px' })
  const [display, setDisplay] = useState(0)
  const fromRef = useRef(0)
  const frameRef = useRef<number>()

  useEffect(() => {
    if (!inView) return
    const prefersReduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      setDisplay(value)
      fromRef.current = value
      return
    }

    const from = fromRef.current
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - start) / duration, 1)
      const current = from + (value - from) * EASE_OUT(progress)
      setDisplay(current)
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = value
      }
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [value, duration, inView])

  return (
    <span ref={ref} className={className}>
      {format ? format(display) : Math.round(display).toLocaleString('ru-RU')}
    </span>
  )
}
