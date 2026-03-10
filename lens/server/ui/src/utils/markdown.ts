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

/**
 * Pre-process raw Lens markdown before passing to markdown-it.
 *
 * - Opening annotation with id + non-empty body  → H2 heading link + body
 * - Opening annotation with id + empty body       → thin divider link bar
 * - Self-closing annotation with id               → thin divider link bar
 * - All other annotations (no id, closing, multi-line blocks) → suppressed
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

      if (!id || close) {
        // No id (cursor/state markers) or closing annotation → suppress
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
      const closeTag = `[/${operator}:${id}]: #`
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
        // Has content → heading link + body, suppress close
        result.push(`## [${label}](#${childAddr})`)
        result.push(...bodyLines)
        i = hasClose ? j + 1 : j
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
