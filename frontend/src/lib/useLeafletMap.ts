import { useEffect, useRef } from 'react'
import L from 'leaflet'

/* Shared CARTO dark basemap for every map on the site. */
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_OPTS: L.TileLayerOptions = {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  subdomains: 'abcd',
  maxZoom: 16,
}

interface Options {
  /* Passed once, when the map is first created. */
  mapOptions?: L.MapOptions
  /* Re-run `draw` (on a fresh layer) whenever any of these change. */
  deps: unknown[]
  /* Draw this section's contents onto a cleared layer; may fit bounds via `map`. */
  draw: (layer: L.LayerGroup, map: L.Map) => void
}

/*
  Owns the Leaflet lifecycle shared by every map section: create the map once,
  add the tile layer, and on each dependency change swap in a fresh LayerGroup
  for `draw` to render into. Returns the ref to attach to the map container.

  A ResizeObserver keeps Leaflet's cached container size correct: Leaflet
  measures the container only at creation, so if it isn't laid out yet (reveal
  animation / flex sizing) the map renders at the wrong size. The observer calls
  invalidateSize() when the container's size actually settles — and on any later
  resize — instead of guessing with a fixed timeout.
*/
export function useLeafletMap({ mapOptions, deps, draw }: Options) {
  const mapEl = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const observerRef = useRef<ResizeObserver | null>(null)

  useEffect(() => {
    if (!mapEl.current) return
    if (!mapRef.current) {
      const map = L.map(mapEl.current, mapOptions)
      L.tileLayer(TILE_URL, TILE_OPTS).addTo(map)
      mapRef.current = map
      // Fires once after the container is laid out, then on every resize.
      observerRef.current = new ResizeObserver(() => map.invalidateSize())
      observerRef.current.observe(mapEl.current)
    }
    const map = mapRef.current
    layerRef.current?.remove()
    const layer = L.layerGroup().addTo(map)
    layerRef.current = layer

    draw(layer, map)
    // deps is a stable-length array supplied by the caller; mapOptions/draw are
    // read fresh each run and intentionally excluded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  // tear the map down only on unmount
  useEffect(
    () => () => {
      observerRef.current?.disconnect()
      observerRef.current = null
      mapRef.current?.remove()
      mapRef.current = null
    },
    [],
  )

  return mapEl
}
