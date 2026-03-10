import MarkdownIt from 'markdown-it'

// Mirrors Python's ANNOTATION_RE: single-line [op(:id)?(/)?]: #
const ANNOTATION_RE =
  /^\s*\[(?<close>\/)?(?<operator>[a-zA-Z_][a-zA-Z0-9_]*)(:(?<id>[a-zA-Z0-9_-]+))?(?<self_close>\/)?\]:\s*#\s*$/

// Mirrors Python's ANNOTATION_OPEN_RE: opening line of a multi-line annotation block.
// Named groups so we can extract operator/id from the opening line.
const ANNOTATION_OPEN_RE =
  /^\s*\[(?<close>\/)?(?<operator>[a-zA-Z_][a-zA-Z0-9_]*)(:(?<id>[a-zA-Z0-9_-]+))?(?<self_close>\/)?\s*$/

// Closing line of a multi-line annotation: `]: #`
const ANNOTATION_END_RE = /^\s*\]:\s*#\s*$/

function toLabel(id: string): string {
  return id
    .split(/[-_]/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ''))
    .join(' ')
}

function renderDivider(label: string, href: string): string {
  return `<div class="annotation-divider"><a href="#${href}">${label}</a></div>`
}

function renderHeading(label: string, href: string): string {
  // Use an explicit HTML element so CSS can target it precisely without
  // affecting any other h2 elements in the rendered document.
  return `<h2 class="annotation-heading"><a href="#${href}">${label}</a></h2>`
}

/** Return true if a line is some kind of annotation (single or multi-line open). */
function isAnnotationLine(line: string): boolean {
  return ANNOTATION_RE.test(line) || ANNOTATION_OPEN_RE.test(line)
}

/** Find the index of the next non-empty line at or after `start`, or -1. */
function nextNonEmpty(lines: string[], start: number): number {
  for (let k = start; k < lines.length; k++) {
    if (lines[k].trim()) return k
  }
  return -1
}

/**
 * Shared look-ahead logic: given an opening annotation at `bodyStart`, find
 * the body and optional matching close, then render the annotation.
 *
 * Returns the result lines to append and the new value of `i`.
 */
function renderAnnotationWithBody(
  lines: string[],
  bodyStart: number,
  operator: string,
  id: string,
  childAddr: string,
  label: string,
): { output: string[]; nextI: number } {
  const bodyLines: string[] = []
  let j = bodyStart
  let hasClose = false

  while (j < lines.length) {
    const candidate = lines[j]
    if (ANNOTATION_RE.test(candidate) || ANNOTATION_OPEN_RE.test(candidate)) {
      const cm = candidate.match(ANNOTATION_RE)
      if (cm?.groups?.close && cm.groups.operator === operator && cm.groups.id === id) {
        hasClose = true
      }
      break
    }
    bodyLines.push(candidate)
    j++
  }

  const bodyText = bodyLines.join('\n').trim()
  const output: string[] = []

  if (bodyText) {
    output.push(renderHeading(label, childAddr))
    output.push(...bodyLines)
    if (hasClose) {
      const afterClose = nextNonEmpty(lines, j + 1)
      if (afterClose >= 0 && !isAnnotationLine(lines[afterClose])) {
        output.push('\n---\n')
      }
    }
    return { output, nextI: hasClose ? j + 1 : j }
  } else {
    output.push(renderDivider(label, childAddr))
    return { output, nextI: hasClose ? j + 1 : j }
  }
}

/**
 * Pre-process raw Lens markdown before passing to markdown-it.
 *
 * - Opening annotation with id + non-empty body  → HTML h2 heading link + body + optional ---
 * - Opening annotation with id + empty body       → thin divider link bar
 * - Self-closing annotation with id               → thin divider link bar
 * - Closing annotation (consumed or orphan) followed by regular text → ---
 * - All other annotations (no id, multi-line blocks without id) → suppressed
 */
export function preprocessAnnotations(
  markdown: string,
  baseAddress: string | null,
): string {
  const lines = markdown.split('\n')
  const result: string[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // --- Multi-line annotation block: [op(:id)? ← whole line, no `]: #`
    if (ANNOTATION_OPEN_RE.test(line) && !ANNOTATION_RE.test(line)) {
      const openMatch = line.match(ANNOTATION_OPEN_RE)
      const og = openMatch?.groups
      // Advance past the parameter lines to the `]: #` closing line
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i])) {
        i++
      }
      i++ // skip `]: #`; i now points to line after the block

      if (og?.id && !og.close && !og.self_close && og.operator) {
        // Multi-line opening with id: same look-ahead as single-line
        const childAddr = baseAddress ? `${baseAddress}/${og.id}` : og.id
        const label =
          toLabel(og.id) + (og.operator !== 'section' ? ` (${toLabel(og.operator)})` : '')
        const { output, nextI } = renderAnnotationWithBody(
          lines, i, og.operator, og.id, childAddr, label,
        )
        result.push(...output)
        i = nextI
      }
      // else: multi-line without id → already advanced, just continue
      continue
    }

    // --- Single-line annotations: [op(:id)?(/)?]: #
    const m = line.match(ANNOTATION_RE)
    if (m && m.groups) {
      const { close, operator, id, self_close } = m.groups

      if (!id) {
        // No id (cursor/state marker) → suppress
        i++
        continue
      }

      if (close) {
        // Orphaned closing annotation → emit --- if regular text follows
        const nxt = nextNonEmpty(lines, i + 1)
        if (nxt >= 0 && !isAnnotationLine(lines[nxt])) {
          result.push('\n---\n')
        }
        i++
        continue
      }

      const childAddr = baseAddress ? `${baseAddress}/${id}` : id
      const label = toLabel(id) + (operator !== 'section' ? ` (${toLabel(operator)})` : '')

      if (self_close) {
        result.push(renderDivider(label, childAddr))
        i++
        continue
      }

      const { output, nextI } = renderAnnotationWithBody(
        lines, i + 1, operator, id, childAddr, label,
      )
      result.push(...output)
      i = nextI
      continue
    }

    result.push(line)
    i++
  }

  return result.join('\n')
}

/** Shared markdown-it instance with settings matching the app's rendering needs. */
export function createMarkdownRenderer(): MarkdownIt {
  return new MarkdownIt({ html: true, linkify: true, typographer: true })
}
