import { useState, type FormEvent } from 'react'
import { TOWNS } from '../lib/data'

interface Props {
  onPlan: (startIdx: number, endIdx: number) => void
}

export function Planner({ onPlan }: Props) {
  const [startIdx, setStartIdx] = useState(0) // Auburn
  const [endIdx, setEndIdx] = useState(5) // Kirkwood
  const [flash, setFlash] = useState<string | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (startIdx === endIdx) {
      setFlash('Pick two different places to draw a route.')
      window.setTimeout(() => setFlash(null), 3200)
      return
    }
    onPlan(startIdx, endIdx)
  }

  const swap = () => {
    setStartIdx(endIdx)
    setEndIdx(startIdx)
  }

  const preset = () => {
    const a = TOWNS.findIndex((t) => t.id === 'Auburn')
    const b = TOWNS.findIndex((t) => t.id === 'Kirkwood')
    setStartIdx(a)
    setEndIdx(b)
    onPlan(a, b)
  }

  return (
    <section className="planner" id="plan">
      <div className="section-head">
        <span className="kicker">Set your line</span>
        <h2>Where are you headed?</h2>
        <p className="sub">
          Pick a start and a destination through the Sierra Nevada. We'll
          draw the drive, then layer everything else on top of it.
        </p>
      </div>

      <form className="route-form" onSubmit={submit} autoComplete="off">
        <div className="field">
          <label htmlFor="startSel">Starting from</label>
          <div className="select-wrap">
            <select id="startSel" name="start" value={startIdx} onChange={(e) => setStartIdx(Number(e.target.value))}>
              {TOWNS.map((t, i) => (
                <option key={t.id} value={i}>{t.id}</option>
              ))}
            </select>
          </div>
        </div>
        <button type="button" className="swap" onClick={swap} title="Swap start & destination" aria-label="Swap start and destination">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 4 L4 7 L7 10" />
            <path d="M4 7 H20" />
            <path d="M17 20 L20 17 L17 14" />
            <path d="M20 17 H4" />
          </svg>
        </button>
        <div className="field">
          <label htmlFor="endSel">Driving to</label>
          <div className="select-wrap">
            <select id="endSel" name="end" value={endIdx} onChange={(e) => setEndIdx(Number(e.target.value))}>
              {TOWNS.map((t, i) => (
                <option key={t.id} value={i}>{t.id}</option>
              ))}
            </select>
          </div>
        </div>
        <button type="submit" className="btn btn-primary plan-btn">Draw the route</button>
      </form>
      <p className="route-hint">
        {flash ? (
          <strong style={{ color: 'var(--clay)' }}>{flash}</strong>
        ) : (
          <>
            Try{' '}
            <button type="button" className="link-btn" onClick={preset}>
              Auburn → Kirkwood
            </button>{' '}
            to see it in motion.
          </>
        )}
      </p>
    </section>
  )
}
