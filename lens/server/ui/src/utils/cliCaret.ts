const WS = /\s/
const NODE_MENTION_ADDR_RE = /^(?:\/[a-zA-Z0-9_/-]*|[a-zA-Z0-9_-]+\/[a-zA-Z0-9_/-]*)$/

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

export function promptNodeMentionLinePickAtCaret(
  text: string,
  caret: number,
): { address: string; startLine?: number; endLine?: number } | null {
  const c = Math.max(0, Math.min(caret, text.length))
  const prefix = text.slice(0, c)
  let at = prefix.lastIndexOf('@')
  while (at >= 0) {
    if (at === 0 || WS.test(prefix[at - 1]!)) break
    at = prefix.lastIndexOf('@', at - 1)
  }
  if (at < 0) return null
  const chunk = prefix.slice(at)
  if (!/\s/.test(chunk)) return null
  const endsWithWs = /\s$/.test(chunk)
  const parts = chunk.trim().split(/\s+/)
  if (parts.length < 1 || parts.length > 3) return null
  const addrToken = parts[0]
  if (!addrToken?.startsWith('@')) return null
  const address = addrToken.slice(1)
  if (!NODE_MENTION_ADDR_RE.test(address)) return null
  if (parts.length === 1) {
    return endsWithWs ? { address } : null
  }
  if (!parts[1] || !/^\d+$/.test(parts[1])) return null
  if (parts.length === 2) {
    return { address, startLine: Number(parts[1]) }
  }
  if (!/^\d+$/.test(parts[2] ?? '')) return null
  return { address, startLine: Number(parts[1]), endLine: Number(parts[2]) }
}
