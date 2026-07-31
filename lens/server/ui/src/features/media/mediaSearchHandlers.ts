const RESERVED_METADATA_KEYS = new Set(['relative_path', 'name', 'extension', 'type', '_score'])

/**
 * Count of words in `text` that are "committed" — i.e. not the one the
 * cursor is currently sitting inside of (or touching an edge of). Used to
 * detect when the user has just finished typing/editing a whole word
 * (added or changed one) or deleted back through one (removed one),
 * without firing on every keystroke of a still-in-progress word.
 *
 * Cursor-relative rather than tail-only: editing an earlier word (or
 * inserting one) while a later, already-finished word sits untouched must
 * still count that later word as committed, regardless of whether the
 * string happens to end in whitespace. Pass `cursorPos = -1` (or any
 * position outside every word's span) to treat the whole string as
 * committed, e.g. right after an explicit Enter-triggered search.
 */
export function committedWordCount(text: string, cursorPos: number): number {
  let count = 0
  const re = /\S+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const start = m.index
    const end = start + m[0].length
    const cursorTouchesWord = cursorPos >= start && cursorPos <= end
    if (!cursorTouchesWord) count++
  }
  return count
}

/** Sidecar/metadata fields worth showing in a search result row, excluding path-derived reserved keys. */
export function extraMetadataFields(item: Record<string, unknown>): [string, unknown][] {
  return Object.entries(item).filter(([key]) => !RESERVED_METADATA_KEYS.has(key))
}

export function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(formatMetadataValue).join(', ')
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${formatMetadataValue(v)}`)
      .join(', ')
  }
  return String(value)
}

/** Directory portion of a mount-relative path, or '' if the path has none. */
export function dirnameOfPath(path: string): string {
  const lastSlash = path.lastIndexOf('/')
  return lastSlash >= 0 ? path.slice(0, lastSlash) : ''
}

/**
 * `amy/house` → `amy! house! ` — a starting-point query that (roughly)
 * reproduces the current folder's contents as required search terms, so
 * opening search from a subfolder with no query yet doesn't start from
 * scratch: press Enter to see the same files, or keep typing to narrow
 * further. Trailing space lets the user continue typing immediately.
 */
export function requiredKeywordsForDir(dir: string): string {
  const segments = dir.split('/').filter(Boolean)
  if (segments.length === 0) return ''
  return segments.map((seg) => `${seg}!`).join(' ') + ' '
}
