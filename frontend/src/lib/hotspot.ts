/**
 * The "denser than average" display heuristic, shared by the density strips
 * and the crash map so they always agree on which miles stand out. A bin is
 * accented when it holds notably more history than the drive's average
 * marked mile; the densest such bin is the one the caption names and the map
 * marks. A display heuristic only — the warehouse's concentration ratio is
 * the rigorous definition, not served by the API.
 */
import type { CrashBin } from '../api/types'

export function hotThreshold(bins: CrashBin[]): number {
  const mean = bins.length ? bins.reduce((s, b) => s + b.crashCount, 0) / bins.length : 0
  return Math.max(2, mean * 1.6)
}

export function densestBin(bins: CrashBin[]): CrashBin | null {
  const threshold = hotThreshold(bins)
  const hot = bins.filter((b) => b.crashCount >= threshold)
  return hot.sort((a, b) => b.crashCount - a.crashCount)[0] ?? null
}
