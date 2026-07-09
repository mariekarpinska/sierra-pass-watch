import { useEffect, useState } from 'react'

export function Nav() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > window.innerHeight * 0.7)
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`nav${scrolled ? ' scrolled' : ''}`}>
      <a className="brand" href="#top">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="26" height="26">
            <path d="M2 26 L11 9 L16 17 L21 6 L30 26 Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            <path d="M8 26 q4 -5 8 0 q4 -5 8 0" fill="none" stroke="currentColor" strokeWidth="1.4" opacity="0.6" />
          </svg>
        </span>
        <span className="brand-word">Sierra Pass Watch</span>
      </a>
      <nav className="nav-links">
        <a href="#plan">Plan a route</a>
        <a href="#disclaimer">About the data</a>
      </nav>
      <a href="#plan" className="nav-cta">Start planning</a>
    </header>
  )
}
