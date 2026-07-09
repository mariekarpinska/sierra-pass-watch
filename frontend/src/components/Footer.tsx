export function Footer() {
  return (
    <footer className="footer" id="disclaimer">
      <div className="footer-top">
        <div className="footer-brand">
          <span className="brand-word big">Sierra Pass Watch</span>
          <p>An awareness companion for Sierra Nevada drives.</p>
        </div>
        <div className="disclaimer-box">
          <h4>Research / educational tool. Not driving advice.</h4>
          <p>
            Sierra Pass Watch surfaces weather and historical incident patterns to help you prepare
            for a drive. It is not a live safety feed, a road-condition report, or a recommendation
            to travel or not travel.
          </p>
          <p className="disclaimer-scope">
            Only the listed California state routes are tracked. Side roads and local streets may be
            closed or carry incidents not collected here, and Nevada-side roads have no California
            crash data.
          </p>
          <p>
            Before any trip, check official sources —{' '}
            <a href="https://quickmap.dot.ca.gov" target="_blank" rel="noopener noreferrer">
              Caltrans QuickMap
            </a>
            , NWS forecasts, and current chain controls — and use your own judgment. Conditions in
            the mountains change faster than any map.
          </p>
        </div>
      </div>
      <div className="footer-bottom">
        <span>© 2026 Sierra Pass Watch</span>
        <span>Research &amp; awareness tool · not for navigation</span>
      </div>
    </footer>
  )
}

export function DisclaimerPill() {
  return (
    <div className="disclaimer-pill">
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8 v0.5 M12 11 v5" strokeLinecap="round" />
      </svg>
      <span>Awareness tool — not driving advice.</span>
      <a href="#disclaimer">More</a>
    </div>
  )
}
