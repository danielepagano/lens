/**
 * Mirrors `strip_for_tts` in lens/core/speech/chunks.py — plain text for display/TTS parity.
 */

const ATTRIBUTED_BLOCKQUOTE_RE = /^\s*(?:>\s*)*\[[^\]]+\]\s+(.+)$/s
const HEADING_RE = /^\s*#+\s*/
const INLINE_IMAGE_RE = /!\[[^\]]*\]\([^)]*\)/g
const INLINE_LINK_RE = /\[[^\]]*\]\([^)]*\)/g
const EMPHASIS_TOKEN_RE = /\*\*|__|\*|_/

export function stripForTts(line: string): string {
  let text = line.trim()
  while (text.startsWith('>')) {
    text = text.slice(1).trimStart()
  }

  const m = text.match(ATTRIBUTED_BLOCKQUOTE_RE)
  if (m?.[1]) {
    text = m[1].trim()
  }

  text = text.replace(HEADING_RE, '')
  text = text.replace(INLINE_IMAGE_RE, '')
  text = text.replace(INLINE_LINK_RE, '')
  while (EMPHASIS_TOKEN_RE.test(text)) {
    text = text.replace(EMPHASIS_TOKEN_RE, '')
  }
  text = text.replace(/`/g, '')
  text = text.replace(/\s+/g, ' ').trim()
  return text
}
