import MarkdownIt from 'markdown-it'

// Mirrors Python's ANNOTATION_RE: single-line [op(:id)?(/)?]: #
const ANNOTATION_RE =
  /^\s*\[(?<close>\/)?(?<operator>[a-zA-Z_][a-zA-Z0-9_]*)(:(?<id>[a-zA-Z0-9_-]+))?(?<self_close>\/)?\]:\s*#\s*$/

// Mirrors Python's ANNOTATION_OPEN_RE: opening line of a multi-line annotation block
// Line looks like `[operator(:id)?` with only whitespace after (no `]: #` ending)
const ANNOTATION_OPEN_RE =
  /^\s*\[(?:\/)?(?:[a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z0-9_-]+)?(?:\/)?\s*$/

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
 * Pre-process raw Lens markdown before passing to markdown-it.
 *
 * - Opening annotation with id + non-empty body  → HTML h2 heading link + body + optional ---
 * - Opening annotation with id + empty body       → thin divider link bar
 * - Self-closing annotation with id               → thin divider link bar
 * - Closing annotation (consumed or orphan) followed by regular text → ---
 * - All other annotations (no id, multi-line blocks) → suppressed
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
    // But must NOT also match a single-line `]: #` pattern (ANNOTATION_RE).
    // If the line ends with `]: #`, it's handled below as a single-line annotation.
    if (ANNOTATION_OPEN_RE.test(line) && !ANNOTATION_RE.test(line)) {
      // Suppress the entire block until `]: #`
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i])) {
        i++
      }
      i++ // skip the `]: #` line
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
        // Orphaned closing annotation (not consumed by opener look-ahead).
        // Emit --- if regular text follows.
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
        // Self-closing with id → divider
        result.push(renderDivider(label, childAddr))
        i++
        continue
      }

      // Opening annotation with id: look ahead for body + matching close
      const bodyLines: string[] = []
      let j = i + 1
      let hasClose = false

      while (j < lines.length) {
        const candidate = lines[j]
        // Stop at any annotation line
        if (ANNOTATION_RE.test(candidate) || ANNOTATION_OPEN_RE.test(candidate)) {
          // Check if it's the matching close
          const cm = candidate.match(ANNOTATION_RE)
          if (cm && cm.groups && cm.groups.close && cm.groups.operator === operator && cm.groups.id === id) {
            hasClose = true
          }
          break
        }
        bodyLines.push(candidate)
        j++
      }

      const bodyText = bodyLines.join('\n').trim()

      if (bodyText) {
        // Has content → heading link + body.
        // Emit --- after the body if regular text follows the close annotation.
        result.push(renderHeading(label, childAddr))
        result.push(...bodyLines)
        if (hasClose) {
          const afterClose = nextNonEmpty(lines, j + 1)
          if (afterClose >= 0 && !isAnnotationLine(lines[afterClose])) {
            result.push('\n---\n')
          }
          i = j + 1
        } else {
          i = j
        }
      } else {
        // Empty body → divider
        result.push(renderDivider(label, childAddr))
        i = hasClose ? j + 1 : j
      }
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
