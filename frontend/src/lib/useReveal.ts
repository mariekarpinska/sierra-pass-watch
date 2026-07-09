import { useEffect, useRef } from 'react'

/* Adds the .reveal/.in scroll entrance to a section. Re-arms when `key` changes. */
export function useReveal<T extends HTMLElement>(key?: unknown) {
  const ref = useRef<T | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.classList.add('reveal')
    el.classList.remove('in')
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add('in')
            io.unobserve(e.target)
          }
        })
      },
      { threshold: 0.12 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [key])

  return ref
}
