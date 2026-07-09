export function Hero() {
  return (
    <section className="hero" id="top">
      {/* Sierra Nevada dawn photograph */}
      <div className="hero-scene" aria-hidden="true">
        <img
          className="hero-photo"
          src="/pexels-stephen-leonardi-587681991-28639333.jpg"
          alt=""
        />
        <div className="hero-overlay" />
      </div>

      <div className="hero-copy">
        <span className="eyebrow">Sierra Nevada · route awareness</span>
        <h1>
          The high country is<br />
          <em>beautiful.</em> Let's get<br />
          there <span className="und">safely.</span>
        </h1>
        <p className="lede">
          Sierra Pass Watch lays live weather and the road's own history across your drive — so the
          mountains feel less like the unknown and more like a place you're ready for.
        </p>
        <div className="hero-actions">
          <a href="#plan" className="btn btn-primary">
            Plan your passage <span aria-hidden="true">↓</span>
          </a>
          <a href="#disclaimer" className="btn btn-ghost">About the data</a>
        </div>
      </div>
      <div className="hero-scroll" aria-hidden="true">
        <span>scroll</span>
        <i></i>
      </div>
      <p className="hero-credit">
        Photo by{' '}
        <a href="https://www.pexels.com/@stephen-leonardi-587681991/" target="_blank" rel="noopener noreferrer">
          Stephen Leonardi
        </a>{' '}
        on{' '}
        <a href="https://www.pexels.com" target="_blank" rel="noopener noreferrer">
          Pexels
        </a>
      </p>
    </section>
  )
}
