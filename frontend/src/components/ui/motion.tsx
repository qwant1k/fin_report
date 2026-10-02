import { type ReactNode } from 'react'
import { motion, type Variants } from 'framer-motion'

import { cn } from '@/lib/cn'

/** Smooth, slightly springy easing used across the app. */
export const EASE = [0.22, 1, 0.36, 1] as const

export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
}

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.4, ease: EASE } },
}

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.25, ease: EASE } },
}

/** Parent container that staggers children using the variants above. */
export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.06, delayChildren: 0.04 },
  },
}

interface FadeInProps {
  children: ReactNode
  className?: string
  delay?: number
  y?: number
}

/** Single element that fades and rises into view on mount. */
export function FadeIn({ children, className, delay = 0, y = 12 }: FadeInProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  )
}

interface StaggerProps {
  children: ReactNode
  className?: string
}

/** Wrap a grid/list so its children animate in sequence. */
export function Stagger({ children, className }: StaggerProps) {
  return (
    <motion.div className={className} variants={staggerContainer} initial="hidden" animate="show">
      {children}
    </motion.div>
  )
}

/** Child of <Stagger>; uses the shared fadeInUp variant. */
export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={fadeInUp}>
      {children}
    </motion.div>
  )
}

/** Page-level wrapper that animates content on route change. */
export function PageTransition({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={cn(className)}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}
