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

  invalidateSize runs on a short timeout because the container is often still
  being laid out (reveal animation / flex sizing) on first paint; see finding #4
  for the ResizeObserver follow-up that would remove the magic delay.
*/
export function useLeafletMap({ mapOptions, deps, draw }: Options) {
  const mapEl = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    if (!mapEl.current) return
    if (!mapRef.current) {
      mapRef.current = L.map(mapEl.current, mapOptions)
      L.tileLayer(TILE_URL, TILE_OPTS).addTo(mapRef.current)
    }
    const map = mapRef.current
    layerRef.current?.remove()
    const layer = L.layerGroup().addTo(map)
    layerRef.current = layer

    draw(layer, map)

    const id = window.setTimeout(() => map.invalidateSize(), 200)
    return () => window.clearTimeout(id)
    // deps is a stable-length array supplied by the caller; mapOptions/draw are
    // read fresh each run and intentionally excluded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  // tear the map down only on unmount
  useEffect(
    () => () => {
      mapRef.current?.remove()
      mapRef.current = null
    },
    [],
  )

  return mapEl
}
