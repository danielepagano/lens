import { stripForTts } from './stripForTts'

/** Same speaker line shape as `BLOCKQUOTE_PILL_LINE_RE` in markdown.ts */
const ATTRIBUTED_LINE_RE = /^(\s*(?:>\s*)+)\[([^\]]+)\]\s+(.*)$/s

export interface ParsedVnLine {
  label: string
  body: string
  /** Same vars as blockquote pills: `--quote-pill-accent`, `--quote-pill-border` */
  style: string
}

export interface VnLineAttributionPill {
  label: string
  style: string
}

/**
 * One pass over playback items: for each source `line`, record the pill from the first
 * text chunk on that line that still contains `> [Name]` (later chunks are continuations).
 * Navigate with {@link Map.get} — no per-beat rescans.
 */
export function buildLineAttributionByLine(
  items: Array<{ type: string; line: number; text?: string }>,
  quoteStyle: (label: string) => { accent: string; border: string },
): Map<number, VnLineAttributionPill> {
  const map = new Map<number, VnLineAttributionPill>()
  for (const it of items) {
    if (it.type !== 'text') continue
    if (map.has(it.line)) continue
    const chunkText = it.text
    if (chunkText === undefined) continue
    const p = parseAttributedPlaybackText(chunkText, quoteStyle)
    if (p) map.set(it.line, { label: p.label, style: p.style })
  }
  return map
}

/**
 * If chunk text is `> [Name] rest`, return label + TTS-stripped body (matches server `strip_for_tts`).
 */
export function parseAttributedPlaybackText(
  text: string,
  quoteStyle: (label: string) => { accent: string; border: string }
): ParsedVnLine | null {
  const lines = text.split('\n')
  const first = lines[0] ?? ''
  const m = first.match(ATTRIBUTED_LINE_RE)
  if (!m) return null
  const [, , label, firstRest] = m
  const { accent, border } = quoteStyle(label)
  const style = `--quote-pill-accent:${accent};--quote-pill-border:${border}`
  const restLines = lines.slice(1)
  const bodyRaw = [firstRest, ...restLines].join('\n').trimEnd()
  const body = stripForTts(bodyRaw)
  return { label, body, style }
}
