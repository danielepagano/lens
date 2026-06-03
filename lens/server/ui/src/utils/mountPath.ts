/**
 * Playback/image URLs may be mount-relative (`hero.png`) or already contain `/mount/file/`
 * from markdown — normalize before calling `getMountFilePath` so we never double-prefix.
 */
export function normalizeMountRelativePath(raw: string): string {
  const s = raw.trim()
  const lower = s.toLowerCase()
  const marker = 'mount/file/'
  const idx = lower.lastIndexOf(marker)
  if (idx >= 0) {
    return s.slice(idx + marker.length).replace(/^\/+/, '')
  }
  return s.replace(/^\/+/, '')
}
