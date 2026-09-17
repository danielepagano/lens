/**
 * Reading `[kb-op …]: #` blocks back out of a node, client-side.
 *
 * The blocks are the record of what a `design` or `advance` beat asked the
 * knowledge store to do, and they outlive the proposal: materialization leaves
 * them in the node (that is what lets `rewind` report what a discarded session
 * wrote), so a historical beat still holds the model's *intent* long after the
 * pending layer that would have diffed it is gone. There is no diff to show
 * there — the base is a git question — but the intent is right here in the
 * text, and it is the more useful half anyway.
 *
 * So this parses the block rather than the payload. The node route serves
 * `pending_kb` for the cursor only; this works on any node, in any state, with
 * no request. It mirrors `render_kb_op` in `core/kb_pending.py` field for
 * field, including the body gutter codec — see that module's docstring for why
 * a body cannot simply be indented text.
 */

export type KbOpSelector = {
  target?: string
  before?: string[]
  after?: string[]
}

export type KbOpPatch = {
  start?: KbOpSelector
  end?: KbOpSelector
  content?: string
}

export type ParsedKbOp = {
  /** `add` | `patch` | `tag` | `remove` | `applied`. */
  op: string
  id: string
  at: string
  session: string
  /** Decoded body text for `add`; null when the block carries none. */
  body: string | null
  patches: KbOpPatch[]
  tags: string[]
  removeTags: string[]
  /** `applied` only: what the close actually wrote, and what it deleted. */
  ids: string[]
  removed: string[]
  /** 1-based inclusive span in the node, the same numbers the payload uses. */
  lineStart: number
  lineEnd: number
  /** The block verbatim, for anything these fields do not cover. */
  raw: string
}

const OPEN_RE = /^\s*\[kb-op\b/
const BLOCK_BREAKER_RE = /\]:\s*#\s*$/
const FIELD_RE = /^ {2}([a-z-]+):\s*(.*)$/
const SEQUENCE_ITEM_RE = /^ {4}- (.*)$/
const BODY_LINE_RE = /^ {4}(.*)$/

const GUTTER = '|'

/** Undo the trailing backslash `_defuse` adds to a line that would end the block. */
function undefuse(line: string): string {
  return line.endsWith('\\') ? line.slice(0, -1) : line
}

/**
 * Undo the `| ` gutter.
 *
 * A bare `|` was an empty source line. Anything that is not gutter-encoded is
 * taken literally, exactly as `decode_body` does: someone fixing a proposal by
 * hand should not have to know the codec to delete a line.
 */
function decodeBodyLine(raw: string): string {
  const line = undefuse(raw)
  if (line === GUTTER) return ''
  if (line.startsWith(`${GUTTER} `)) return line.slice(GUTTER.length + 1)
  return line
}

/** Strip the quoting `_scalar` adds when a value would not read back as written. */
export function unquoteYamlScalar(raw: string): string {
  const v = raw.trim()
  const quoted =
    v.length >= 2 &&
    ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
  if (!quoted) return v
  if (v.startsWith("'")) return v.slice(1, -1)
  try {
    return JSON.parse(v) as string
  } catch {
    return v.slice(1, -1)
  }
}

function parsePatches(raw: string): KbOpPatch[] {
  // Compact JSON on one line, never block YAML — patch targets and content are
  // arbitrary model text, and `json.dumps` is what escapes the newlines in it.
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((p): p is KbOpPatch => typeof p === 'object' && p !== null)
  } catch {
    return []
  }
}

function parseBlock(lines: string[], start: number, end: number): ParsedKbOp | null {
  const op: ParsedKbOp = {
    op: '',
    id: '',
    at: '',
    session: '',
    body: null,
    patches: [],
    tags: [],
    removeTags: [],
    ids: [],
    removed: [],
    lineStart: start + 1,
    lineEnd: end,
    raw: lines.slice(start, end).join('\n'),
  }

  const sequences: Record<string, string[]> = {
    tags: op.tags,
    'remove-tags': op.removeTags,
    ids: op.ids,
    removed: op.removed,
  }

  let i = start + 1
  while (i < end) {
    const line = lines[i]!
    const field = line.match(FIELD_RE)
    if (!field) {
      i++
      continue
    }
    const key = field[1]!
    const value = field[2]!
    if (key === 'body' && value.trim() === '|') {
      const bodyLines: string[] = []
      i++
      // A sequence item is the only other thing indented four spaces, and a
      // gutter-encoded body line can never look like one.
      while (i < end && BODY_LINE_RE.test(lines[i]!) && !SEQUENCE_ITEM_RE.test(lines[i]!)) {
        bodyLines.push(decodeBodyLine(lines[i]!.slice(4)))
        i++
      }
      op.body = bodyLines.join('\n')
      continue
    }
    const sequence = sequences[key]
    if (sequence && value.trim() === '') {
      i++
      while (i < end) {
        const item = lines[i]!.match(SEQUENCE_ITEM_RE)
        if (!item) break
        sequence.push(unquoteYamlScalar(item[1]!))
        i++
      }
      continue
    }
    if (key === 'op') op.op = unquoteYamlScalar(value)
    else if (key === 'id') op.id = unquoteYamlScalar(value).toLowerCase()
    else if (key === 'at') op.at = unquoteYamlScalar(value)
    else if (key === 'session') op.session = unquoteYamlScalar(value)
    else if (key === 'patches') op.patches = parsePatches(value)
    i++
  }

  return op.op ? op : null
}

/**
 * Every block in *text*, in order.
 *
 * An unterminated block runs to end of text, matching `iter_kb_op_spans`:
 * everything from the opener on is proposal metadata, and treating the
 * remainder as prose would put a KB body into the reader's passage.
 */
export function parseKbOpBlocks(text: string): ParsedKbOp[] {
  const lines = text.split('\n')
  const out: ParsedKbOp[] = []
  let i = 0
  while (i < lines.length) {
    if (!OPEN_RE.test(lines[i]!)) {
      i++
      continue
    }
    let end = i
    while (end < lines.length && !BLOCK_BREAKER_RE.test(lines[end]!)) end++
    end = Math.min(end + 1, lines.length)
    const parsed = parseBlock(lines, i, end)
    if (parsed) out.push(parsed)
    i = end
  }
  return out
}

/** The block whose opener is at *lineStart* (1-based), which is what a marker carries. */
export function kbOpBlockAtLine(text: string, lineStart: number): ParsedKbOp | null {
  return parseKbOpBlocks(text).find((op) => op.lineStart === lineStart) ?? null
}

/** Ids this op points at: one for a proposal, the written set for `applied`. */
export function kbOpTargetIds(op: ParsedKbOp): string[] {
  if (op.id) return [op.id]
  return [...op.ids, ...op.removed]
}
