import MarkdownIt from 'markdown-it'
import { findFileHunks, type ParsedHunk } from './diff'

// Mirrors Python's ANNOTATION_RE: single-line [op(:id)?(/)?]: #
const ANNOTATION_RE =
  /^\s*\[(?<close>\/)?(?<operator>[a-zA-Z_][a-zA-Z0-9_]*)(:(?<id>[a-zA-Z0-9_-]+))?(?<self_close>\/)?\]:\s*#\s*$/

// Mirrors Python's ANNOTATION_OPEN_RE: opening line of a multi-line annotation block.
// Named groups so we can extract operator/id from the opening line.
const ANNOTATION_OPEN_RE =
  /^\s*\[(?<close>\/)?(?<operator>[a-zA-Z_][a-zA-Z0-9_]*)(:(?<id>[a-zA-Z0-9_-]+))?(?<self_close>\/)?\s*$/

// Closing line of a multi-line annotation: `]: #`
const ANNOTATION_END_RE = /^\s*\]:\s*#\s*$/

// Front-matter block opener: bare `[` on its own line (no operator name).
// These blocks contain YAML-like content (kb_pin, kb_unpin) and close with `]: #`.
const FRONT_MATTER_OPEN_RE = /^\s*\[\s*$/

export interface RemovedGroup {
  beforeLine: number
  lines: string[]
}

export interface NodeTransactionOverlay {
  addedLines: Set<number>
  removedGroups: RemovedGroup[]
}

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
  return `<h3 class="annotation-heading"><a href="#${href}">${label}</a></h3>`
}

/** Return true if a line is some kind of annotation (single, multi-line open, or front-matter open). */
function isAnnotationLine(line: string): boolean {
  return ANNOTATION_RE.test(line) || ANNOTATION_OPEN_RE.test(line) || FRONT_MATTER_OPEN_RE.test(line)
}

/** Find the index of the next non-empty line at or after `start`, or -1. */
function nextNonEmpty(lines: string[], start: number): number {
  for (let k = start; k < lines.length; k++) {
    if (lines[k].trim()) return k
  }
  return -1
}

/**
 * Filter annotation lines out of a list of removed lines.
 * Uses stateful tracking for multi-line annotation blocks.
 */
function filterAnnotationLines(lines: string[]): string[] {
  const result: string[] = []
  let inBlock = false
  for (const line of lines) {
    const stripped = line.trim()
    if (ANNOTATION_RE.test(stripped)) continue
    if (ANNOTATION_END_RE.test(stripped)) {
      inBlock = false
      continue
    }
    if (inBlock) continue
    if (ANNOTATION_OPEN_RE.test(stripped) || FRONT_MATTER_OPEN_RE.test(stripped)) {
      inBlock = true
      continue
    }
    result.push(line)
  }
  return result
}

function pushRemovedContent(
  into: string[],
  removedByLine: Map<number, RemovedGroup[]>,
  lineNo: number,
): void {
  const groups = removedByLine.get(lineNo)
  if (!groups?.length) return
  for (const g of groups) {
    const content = g.lines.join('\n').trim()
    if (!content) continue
    into.push('')
    into.push('<div class="transaction-removed">')
    into.push('')
    into.push(content)
    into.push('')
    into.push('</div>')
    into.push('')
  }
}

/**
 * Shared look-ahead logic: given an opening annotation at `bodyStart`, find
 * the body and optional matching close, then render the annotation.
 * Overlay is applied to body content lines (added-line wrap and removed-line blocks).
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
  overlay: NodeTransactionOverlay | null,
  removedByLine: Map<number, RemovedGroup[]>,
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
    const bodyStartLine = bodyStart + 1
    for (let k = 0; k < bodyLines.length; k++) {
      const fileLine = bodyStartLine + k
      pushRemovedContent(output, removedByLine, fileLine)

      const outLine = bodyLines[k]
      const isAdded =
        overlay &&
        overlay.addedLines.has(fileLine) &&
        outLine.trim() !== ''
      if (isAdded) {
        output.push('')
        output.push('<div class="transaction-added">')
        output.push('')
        output.push(outLine)
        output.push('')
        output.push('</div>')
        output.push('')
      } else {
        output.push(outLine)
      }
    }
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
 * When an overlay is provided, diff markers are applied to content lines
 * in the main loop only — annotation lines are never diff-marked, which
 * prevents artifacts from front-matter or operator annotation changes.
 *
 * - Opening annotation with id + non-empty body  → HTML h3 heading link + body + optional ---
 * - Opening annotation with id + empty body       → thin divider link bar
 * - Self-closing annotation with id               → thin divider link bar
 * - Closing annotation (consumed or orphan) followed by regular text → ---
 * - All other annotations (no id, multi-line blocks without id) → suppressed
 */
export function preprocessAnnotations(
  markdown: string,
  baseAddress: string | null,
  overlay: NodeTransactionOverlay | null = null,
 ): string {
  const lines = markdown.split('\n')
  const result: string[] = []
  const removedByLine = new Map<number, RemovedGroup[]>()
  const trailingRemoved: RemovedGroup[] = []

  if (overlay) {
    for (const group of overlay.removedGroups) {
      if (group.beforeLine <= lines.length) {
        const existing = removedByLine.get(group.beforeLine) ?? []
        existing.push(group)
        removedByLine.set(group.beforeLine, existing)
      } else {
        trailingRemoved.push(group)
      }
    }
  }

  let i = 0

  while (i < lines.length) {
    const lineNo = i + 1
    const line = lines[i]

    // --- Front-matter block: bare `[` ... `]: #` (no operator name)
    // Contains YAML-like content (kb_pin, kb_unpin). Consumed silently.
    if (FRONT_MATTER_OPEN_RE.test(line)) {
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i])) {
        i++
      }
      i++ // skip `]: #`
      continue
    }

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
        const childAddr = baseAddress ? `${baseAddress}/${og.id}` : og.id
        const label =
          toLabel(og.id) + (og.operator !== 'section' ? ` (${toLabel(og.operator)})` : '')
        const { output, nextI } = renderAnnotationWithBody(
          lines, i, og.operator, og.id, childAddr, label, overlay, removedByLine,
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
        lines, i + 1, operator, id, childAddr, label, overlay, removedByLine,
      )
      result.push(...output)
      i = nextI
      continue
    }

    // --- Regular content line: apply diff overlay if present
    pushRemovedContent(result, removedByLine, lineNo)

    const isAdded =
      overlay &&
      overlay.addedLines.has(lineNo) &&
      line.trim() !== ''
    if (isAdded) {
      result.push('')
      result.push('<div class="transaction-added">')
      result.push('')
      result.push(line)
      result.push('')
      result.push('</div>')
      result.push('')
    } else {
      result.push(line)
    }
    i++
  }

  if (trailingRemoved.length > 0) {
    for (const g of trailingRemoved) {
      const content = g.lines.join('\n').trim()
      if (!content) continue
      result.push('')
      result.push('<div class="transaction-removed">')
      result.push('')
      result.push(content)
      result.push('')
      result.push('</div>')
      result.push('')
    }
  }

  return result.join('\n')
}

/** Shared markdown-it instance with settings matching the app's rendering needs. */
export function createMarkdownRenderer(): MarkdownIt {
  return new MarkdownIt({ html: true, linkify: true, typographer: true })
}

export function buildNodeTransactionOverlay(
  rawDiff: string | null,
  currentAddress: string | null,
): NodeTransactionOverlay | null {
  if (!rawDiff || !currentAddress) return null

  const hunks = findFileHunks(rawDiff, currentAddress)
  if (!hunks || hunks.length === 0) return null

  const addedLines = new Set<number>()
  const removedGroups: RemovedGroup[] = []

  for (const hunk of hunks) {
    let newLine = hunk.newStart
    let pendingRemoved: string[] = []
    let pendingBefore = newLine

    for (const line of hunk.lines) {
      if (line.kind === 'context') {
        if (pendingRemoved.length > 0) {
          removedGroups.push({ beforeLine: pendingBefore, lines: pendingRemoved })
          pendingRemoved = []
        }
        newLine += 1
      } else if (line.kind === 'add') {
        addedLines.add(newLine)
        if (pendingRemoved.length > 0) {
          removedGroups.push({ beforeLine: pendingBefore, lines: pendingRemoved })
          pendingRemoved = []
        }
        newLine += 1
      } else if (line.kind === 'remove') {
        if (pendingRemoved.length === 0) pendingBefore = newLine
        pendingRemoved.push(line.text)
      }
    }

    if (pendingRemoved.length > 0) {
      removedGroups.push({ beforeLine: pendingBefore, lines: pendingRemoved })
    }
  }

  // Filter annotation lines out of removed groups
  const filteredGroups: RemovedGroup[] = []
  for (const g of removedGroups) {
    const filtered = filterAnnotationLines(g.lines)
    if (filtered.length > 0) {
      filteredGroups.push({ beforeLine: g.beforeLine, lines: filtered })
    }
  }

  if (addedLines.size === 0 && filteredGroups.length === 0) {
    return null
  }

  return { addedLines, removedGroups: filteredGroups }
}
