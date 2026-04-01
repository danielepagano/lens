const WS = /\s/

/** First index of the whitespace-delimited run that contains `caret` (caret may be at run end). */
function runStart(text: string, caret: number): number {
  let s = Math.max(0, Math.min(caret, text.length))
  while (s > 0 && !WS.test(text[s - 1]!)) s--
  return s
}

/**
 * From `caret`, walk backward within the same whitespace run. If we see `@` that starts a
 * mention (line/start or preceded by whitespace), we are in an @-mention: token is `@` through `caret`.
 */
export function kbMentionAtCaret(text: string, caret: number): { at: number; token: string } | null {
  const c = Math.max(0, Math.min(caret, text.length))
  const rs = runStart(text, c)
  const chunk = text.slice(rs, c)
  const rel = chunk.lastIndexOf('@')
  if (rel < 0) return null
  const at = rs + rel
  if (at > 0 && !WS.test(text[at - 1]!)) return null
  return { at, token: text.slice(at, c) }
}

/** Ghost hint after `@roll` in a prompt (token or following whitespace run). */
export function promptDiceExpressionHint(text: string, caret: number): boolean {
  const m = kbMentionAtCaret(text, caret)
  if (m) {
    if (m.token === '@roll') return true
    if (m.token.length > 5 && m.token.startsWith('@roll') && WS.test(m.token[5]!)) return true
  }
  const rs = runStart(text, caret)
  const prev = text.slice(0, rs).trimEnd().split(/\s+/).filter(Boolean)
  return (prev.length ? prev[prev.length - 1]! : '') === '@roll'
}
