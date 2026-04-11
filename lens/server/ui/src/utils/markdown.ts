import MarkdownIt from 'markdown-it'
import type { LinePickRowState } from '../features/editor/cmLinePick'
import { findFileHunks } from './diff'

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

// Blockquote line: `> [label] rest` (nested `> >` allowed). Label becomes a pill in HTML output.
const BLOCKQUOTE_PILL_LINE_RE = /^(\s*(?:>\s*)+)\[([^\]]+)\]\s+(.*)$/

function escapeHtmlText(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** FNV-1a 32-bit — stable, distinct hues per speaker label. */
function fnv1aLabelSeed(label: string): number {
  const t = label.trim().toLowerCase()
  let h = 2125136265
  for (let i = 0; i < t.length; i++) {
    h ^= t.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Space-separated H S% L% for `hsl(var(--x))` / `hsl(var(--x) / α)`. */
function quotePillHslVars(label: string): { accent: string; border: string } {
  const u = fnv1aLabelSeed(label)
  const hue = u % 360
  const sat = 38 + ((u >>> 8) % 24)
  const light = 26 + ((u >>> 16) % 12)
  const borderLight = Math.min(light + 9, 42)
  return {
    accent: `${hue} ${sat}% ${light}%`,
    border: `${hue} ${sat}% ${borderLight}%`,
  }
}

/**
 * Turn `> [speaker] …` blockquote lines into inline HTML so the bracketed tag
 * renders as a pill. Requires markdown-it `html: true` (see createMarkdownRenderer).
 * Run before preprocessAnnotations.
 */
export function preprocessBlockquotePills(markdown: string): string {
  return markdown
    .split('\n')
    .map((line) => {
      const m = line.match(BLOCKQUOTE_PILL_LINE_RE)
      if (!m) return line
      const [, prefix, label, rest] = m
      const { accent, border } = quotePillHslVars(label)
      const style = `--quote-pill-accent:${accent};--quote-pill-border:${border}`
      return `${prefix}<span class="quote-pill" style="${style}">${escapeHtmlText(label)}</span> ${rest}`
    })
    .join('\n')
}

// Canonical id with exactly one `.` (type.key); no dots inside type or key segments.
const KB_PIN_ID = '[a-z][a-z0-9_-]*\\.[a-z0-9][a-z0-9_-]*'
const KB_PIN_RE = new RegExp(
  `KB\\['(${KB_PIN_ID})'\\]|(?<![a-zA-Z0-9])@(${KB_PIN_ID})\\b`,
  'g',
)

function replaceKbReferencesInPlainLine(line: string): string {
  return line.replace(KB_PIN_RE, (full, kbQuoted: string | undefined, atForm: string | undefined, offset) => {
    const id = kbQuoted ?? atForm
    if (!id) return full
    const before = line.slice(0, offset)
    if ((before.match(/`/g) ?? []).length % 2 === 1) return full
    return `<button type="button" class="pin-pill markdown-kb-ref" data-kb-open-id="${escapeHtmlText(id)}">${escapeHtmlText(id)}</button>`
  })
}

/**
 * Turn `KB['type.key']` (same token as `KnowledgeObject.format()`) and `@type.key`
 * into pin-style buttons (`data-kb-open-id`). Each id must contain exactly one
 * period (no `a.b.c`). `@` is not matched after alphanumerics (avoids `user@host`).
 * Skips fenced code blocks and inline `` `...` `` spans.
 * Run after `preprocessBlockquotePills`, before `preprocessAnnotations`.
 */
export function preprocessKbReferencePills(markdown: string): string {
  const lines = markdown.split('\n')
  const out: string[] = []
  let inFence = false
  let fenceMarker: '`' | '~' = '`'
  let fenceLen = 3

  for (const line of lines) {
    if (inFence) {
      if (isFenceCloser(line, fenceMarker, fenceLen)) inFence = false
      out.push(line)
      continue
    }

    const info = fenceInfo(line)
    if (info) {
      inFence = true
      fenceMarker = info.marker
      fenceLen = info.length
      out.push(line)
      continue
    }

    out.push(replaceKbReferencesInPlainLine(line))
  }

  return out.join('\n')
}

export interface RemovedGroup {
  beforeLine: number
  lines: string[]
}

export interface NodeTransactionOverlay {
  addedLines: Set<number>
  removedGroups: RemovedGroup[]
}

/** First segment of a session sub-node slug that maps to an inline type pill. */
const SECTION_TYPE_TOKENS = ['play', 'design', 'chat', 'collate', 'advance']

function toLabelParts(id: string): { html: string; plainTitle: string; pillHtml: string; typePrefix: string | null } {
  const parts = id.split(/[-_]/)
  const first = parts[0]
  const hasTypePrefix =
    first !== undefined && first !== '' && SECTION_TYPE_TOKENS.includes(first)
  const words = hasTypePrefix ? parts.slice(1) : parts
  const plainTitle = words
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ''))
    .join(' ')
  const pillHtml =
    hasTypePrefix && first !== undefined
      ? ` <span class="pin-pill pin-pill-inline">${escapeHtmlText(first)}</span>`
      : ''
  const html =
    hasTypePrefix && first !== undefined
      ? plainTitle
        ? `${plainTitle}${pillHtml}`
        : escapeHtmlText(`[${first}]`)
      : plainTitle
  return {
    html,
    plainTitle,
    pillHtml,
    typePrefix: hasTypePrefix && first !== undefined ? first : null,
  }
}

function toLabel(id: string): string {
  return toLabelParts(id).html
}

/** Title text for annotation dividers when operator pills follow — no duplicate type pill. */
function dividerTitleOnlyHtml(id: string): string {
  const { plainTitle, typePrefix } = toLabelParts(id)
  if (plainTitle.trim()) return escapeHtmlText(plainTitle)
  if (typePrefix !== null) return escapeHtmlText(`[${typePrefix}]`)
  return escapeHtmlText(plainTitle)
}

export interface ParsedChatDividerParams {
  asKbId?: string
  withKbId?: string
  memoryKbIds: string[]
}

/** Parse chat annotation YAML lines between `[chat:id` and `]: #` (as_kb_id, with_kb_id, memory_kb_ids). */
export function parseChatDividerParams(paramBlock: string): ParsedChatDividerParams {
  const out: ParsedChatDividerParams = { memoryKbIds: [] }
  let memoryList = false

  for (const raw of paramBlock.split('\n')) {
    const t = raw.trim()
    if (!t) continue

    const listItem = t.match(/^-\s+(.+)$/)
    if (listItem && memoryList) {
      const id = listItem[1].trim().replace(/\s+#.*$/, '')
      if (id) out.memoryKbIds.push(id)
      continue
    }

    const scalar = t.match(/^([a-zA-Z0-9_]+):\s*(.*)$/)
    if (!scalar) continue
    const key = scalar[1]
    const val = scalar[2].trim()
    memoryList = false

    if (key === 'memory_kb_ids') {
      memoryList = true
      const inline = val.match(/^\[(.*)\]\s*$/)
      if (inline) {
        const inner = inline[1].trim()
        if (inner) {
          for (const part of inner.split(',')) {
            const s = part.trim().replace(/^['"]|['"]$/g, '')
            if (s) out.memoryKbIds.push(s)
          }
        }
        memoryList = false
      }
    } else if (key === 'as_kb_id') {
      out.asKbId = val
    } else if (key === 'with_kb_id') {
      out.withKbId = val
    }
  }

  return out
}

function kbIdToSlugKey(kbId: string): string {
  const tail = kbId.includes('.') ? kbId.slice(kbId.indexOf('.') + 1) : kbId
  return tail
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function chatDividerKeysFromSlugId(id: string): string | null {
  const parts = id.split('-')
  if (parts.length < 2 || parts[0] !== 'chat') return null
  if (parts.length >= 3) return `${parts[1]}-${parts[2]}`
  return parts[1] ?? null
}

/**
 * HTML inside the annotation divider link. When `operator` is `chat`, adds
 * `chat:as-with` and memory pills after the title (no duplicate inline type pill);
 * all other operators use {@link toLabel} only.
 */
export function buildAnnotationDividerLabelHtml(
  operator: string,
  id: string,
  paramBlock: string | null,
): string {
  if (operator !== 'chat') return toLabel(id)

  const meta = paramBlock ? parseChatDividerParams(paramBlock) : null
  const extras: string[] = []

  let keys: string | null = null
  if (meta?.asKbId) {
    const a = kbIdToSlugKey(meta.asKbId)
    const w = meta.withKbId ? kbIdToSlugKey(meta.withKbId) : ''
    keys = w ? `${a}-${w}` : a
  } else {
    keys = chatDividerKeysFromSlugId(id)
  }
  if (keys) {
    const main = escapeHtmlText(`chat:${keys}`)
    extras.push(`<span class="pin-pill pin-pill-annotation-divider">${main}</span>`)
    for (const mid of meta?.memoryKbIds ?? []) {
      extras.push(`<span class="pin-pill pin-pill-unpin">${escapeHtmlText(mid)}</span>`)
    }
  }

  if (extras.length === 0) return toLabel(id)
  return `<span class="annotation-divider-title">${dividerTitleOnlyHtml(id)}</span>${extras.join('')}`
}

function renderDivider(innerHtml: string, href: string): string {
  return `<div class="annotation-divider"><a href="#${href}">${innerHtml}</a></div>`
}

const SECTION_SUMMARY_COMMENT_RE = /^\s*<!--\s*section:[a-zA-Z0-9_-]+\s*-->\s*$/
const SECTION_SUMMARY_MD_TITLE_RE = /^\s*###\s+(.+?)\s*$/

/** Strip duplicate markdown title when body matches canonical Lens summary shape. */
function parseCanonicalSummaryLinesToOmit(bodyLines: string[]): {
  omit: Set<number>
  aiTitle: string | null
} {
  const omit = new Set<number>()
  let i = 0
  while (i < bodyLines.length && !bodyLines[i].trim()) i++
  if (i >= bodyLines.length || !SECTION_SUMMARY_COMMENT_RE.test(bodyLines[i])) {
    return { omit, aiTitle: null }
  }
  i++
  while (i < bodyLines.length && !bodyLines[i].trim()) i++
  const line = i < bodyLines.length ? bodyLines[i] : ''
  const m = line.match(SECTION_SUMMARY_MD_TITLE_RE)
  if (!m?.[1]) return { omit, aiTitle: null }
  const aiTitle = m[1]
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/^#+\s*/, '')
    .replace(/<[^>]+>/g, '')
    .trim()
  omit.add(i)
  i++
  if (i < bodyLines.length && !bodyLines[i].trim()) omit.add(i)
  return { omit, aiTitle: aiTitle || null }
}

function annotationHeadingInnerHtml(id: string, aiTitle: string | null): string {
  const { plainTitle, pillHtml, typePrefix } = toLabelParts(id)
  const fromFile = aiTitle?.trim()
  const titleText = fromFile && fromFile.length > 0 ? fromFile : plainTitle
  if (!titleText) {
    if (typePrefix !== null) {
      return escapeHtmlText(`[${typePrefix}]`)
    }
    return escapeHtmlText(plainTitle)
  }
  return escapeHtmlText(titleText) + pillHtml
}

function annotationHeadingHtml(childAddr: string, id: string, aiTitle: string | null): string {
  const inner = annotationHeadingInnerHtml(id, aiTitle)
  return `<h3 class="annotation-heading"><a href="#${escapeHtmlAttr(childAddr)}">${inner}</a></h3>`
}

function escapeHtmlAttr(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
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

/**
 * Flush a contiguous run of added lines into `into` as a single transaction-added
 * wrapper so markdown-it sees one document fragment (blockquotes, HTML comments,
 * lists, etc. stay structurally intact).
 */
function flushAddedTransactionRun(into: string[], run: string[]): void {
  if (run.length === 0) return
  const hasVisible = run.some((l) => l.trim() !== '')
  if (!hasVisible) {
    for (const l of run) into.push(l)
  } else {
    into.push('')
    into.push('<div class="transaction-added">')
    into.push('')
    for (const l of run) into.push(l)
    into.push('')
    into.push('</div>')
    into.push('')
  }
  run.length = 0
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

function fenceInfo(line: string): { marker: '`' | '~'; length: number } | null {
  const match = line.match(/^\s*(`{3,}|~{3,})/)
  if (!match) return null
  const fence = match[1]
  if (fence.startsWith('`')) return { marker: '`', length: fence.length }
  return { marker: '~', length: fence.length }
}

function isFenceCloser(line: string, marker: '`' | '~', length: number): boolean {
  if (marker === '`') {
    return /^\s*`{3,}\s*$/.test(line) && line.trim().length >= length
  }
  return /^\s*~{3,}\s*$/.test(line) && line.trim().length >= length
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
  openingLineNo: number,
  operator: string,
  id: string,
  childAddr: string,
  paramBlock: string | null,
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
  const closingLineNo = j + 1

  if (bodyText) {
    const { omit: omitBodyLine, aiTitle } = parseCanonicalSummaryLinesToOmit(bodyLines)
    const bodyStartLine = bodyStart + 1
    for (let lineNo = openingLineNo; lineNo <= closingLineNo; lineNo++) {
      pushRemovedContent(output, removedByLine, lineNo)
    }
    output.push('')
    output.push(annotationHeadingHtml(childAddr, id, aiTitle))
    output.push('')
    const addedRun: string[] = []
    for (let k = 0; k < bodyLines.length; ) {
      if (omitBodyLine.has(k)) {
        const outLine = bodyLines[k]
        const fileLine = bodyStartLine + k
        if (overlay?.addedLines.has(fileLine)) {
          flushAddedTransactionRun(output, addedRun)
          output.push(outLine)
        }
        k += 1
        continue
      }
      const outLine = bodyLines[k]
      const info = fenceInfo(outLine)
      if (info) {
        flushAddedTransactionRun(output, addedRun)
        let end = k
        while (end + 1 < bodyLines.length) {
          end += 1
          if (isFenceCloser(bodyLines[end], info.marker, info.length)) break
        }
        const hasAddedInFence = overlay
          ? Array.from({ length: end - k + 1 }).some((_, idx) => overlay.addedLines.has(bodyStartLine + k + idx))
          : false
        if (hasAddedInFence) {
          output.push('')
          output.push('<div class="transaction-added">')
          output.push('')
          for (let p = k; p <= end; p++) output.push(bodyLines[p])
          output.push('')
          output.push('</div>')
          output.push('')
        } else {
          for (let p = k; p <= end; p++) output.push(bodyLines[p])
        }
        k = end + 1
        continue
      }

      const fileLine = bodyStartLine + k
      if (overlay?.addedLines.has(fileLine)) {
        addedRun.push(outLine)
      } else {
        flushAddedTransactionRun(output, addedRun)
        output.push(outLine)
      }
      k += 1
    }
    flushAddedTransactionRun(output, addedRun)
    if (hasClose) {
      const afterClose = nextNonEmpty(lines, j + 1)
      if (afterClose >= 0 && !isAnnotationLine(lines[afterClose])) {
        output.push('\n---\n')
      }
    }
    return { output, nextI: hasClose ? j + 1 : j }
  } else {
    output.push(
      renderDivider(buildAnnotationDividerLabelHtml(operator, id, paramBlock), childAddr),
    )
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
 * - Opening annotation with id + non-empty body  → HTML h3 (link + type pill)
 *   + body + optional --- (canonical summaries omit duplicate `###` title line)
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
  const addedRun: string[] = []

  while (i < lines.length) {
    const lineNo = i + 1
    const line = lines[i]

    // --- Front-matter block: bare `[` ... `]: #` (no operator name)
    // Contains YAML-like content (kb_pin, kb_unpin). Consumed silently.
    if (FRONT_MATTER_OPEN_RE.test(line)) {
      flushAddedTransactionRun(result, addedRun)
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i])) {
        i++
      }
      i++ // skip `]: #`
      continue
    }

    // --- Multi-line annotation block: [op(:id)? ← whole line, no `]: #`
    if (ANNOTATION_OPEN_RE.test(line) && !ANNOTATION_RE.test(line)) {
      flushAddedTransactionRun(result, addedRun)
      const openMatch = line.match(ANNOTATION_OPEN_RE)
      const og = openMatch?.groups
      const multiLineOpeningLineNo = lineNo
      i++
      const paramLines: string[] = []
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i]!)) {
        paramLines.push(lines[i]!)
        i++
      }
      const paramBlock = paramLines.join('\n')
      if (i < lines.length) {
        i++ // skip `]: #`; i now points to line after the block
      }

      if (og?.id && !og.close && !og.self_close && og.operator) {
        const childAddr = baseAddress ? `${baseAddress}/${og.id}` : og.id
        const { output, nextI } = renderAnnotationWithBody(
          lines,
          i,
          multiLineOpeningLineNo,
          og.operator,
          og.id,
          childAddr,
          paramBlock,
          overlay,
          removedByLine,
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
      flushAddedTransactionRun(result, addedRun)
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

      if (self_close) {
        result.push(
          renderDivider(buildAnnotationDividerLabelHtml(operator, id, null), childAddr),
        )
        i++
        continue
      }

      const { output, nextI } = renderAnnotationWithBody(
        lines,
        i + 1,
        lineNo,
        operator,
        id,
        childAddr,
        null,
        overlay,
        removedByLine,
      )
      result.push(...output)
      i = nextI
      continue
    }

    // --- Regular content line: apply diff overlay if present
    const info = fenceInfo(line)
    if (info) {
      flushAddedTransactionRun(result, addedRun)
      let end = i
      while (end + 1 < lines.length) {
        end += 1
        if (isFenceCloser(lines[end], info.marker, info.length)) break
      }
      for (let p = i; p <= end; p++) {
        pushRemovedContent(result, removedByLine, p + 1)
      }
      const hasAddedInFence = overlay
        ? Array.from({ length: end - i + 1 }).some((_, idx) => overlay.addedLines.has(lineNo + idx))
        : false
      if (hasAddedInFence) {
        result.push('')
        result.push('<div class="transaction-added">')
        result.push('')
        for (let p = i; p <= end; p++) result.push(lines[p])
        result.push('')
        result.push('</div>')
        result.push('')
      } else {
        for (let p = i; p <= end; p++) result.push(lines[p])
      }
      i = end + 1
      continue
    }

    pushRemovedContent(result, removedByLine, lineNo)
    if (overlay?.addedLines.has(lineNo)) {
      addedRun.push(line)
    } else {
      flushAddedTransactionRun(result, addedRun)
      result.push(line)
    }
    i++
  }

  flushAddedTransactionRun(result, addedRun)

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

/**
 * Return the set of 1-indexed line numbers that are part of annotation or
 * front-matter blocks in the given raw markdown content. These lines are
 * structural and not valid targets for line-pick operations.
 *
 * Only marks the tag lines themselves (open tag, params, close tag, front
 * matter), NOT the body content between open and close tags.
 */
export function buildAnnotationLineSet(content: string): Set<number> {
  const lines = content.split('\n')
  const result = new Set<number>()
  let inBlock = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!
    const lineNo = i + 1
    if (inBlock) {
      result.add(lineNo)
      if (ANNOTATION_END_RE.test(line)) inBlock = false
    } else if (ANNOTATION_RE.test(line)) {
      result.add(lineNo)
    } else if (ANNOTATION_OPEN_RE.test(line) || FRONT_MATTER_OPEN_RE.test(line)) {
      result.add(lineNo)
      inBlock = true
    }
  }
  return result
}

/**
 * 1-based line numbers that cannot be used as “insert after this line” for media attach.
 * Matches Python `validate_attach_insertion_point`: front matter (all lines including `]: #`),
 * and strict interiors of multiline annotation tags (excluding the closing `]: #` line).
 */
export function collectAttachForbiddenLines(content: string): Set<number> {
  const lines = content.split('\n')
  const forbidden = new Set<number>()
  let inBlock = false
  let isFm = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!
    const lineNo = i + 1

    if (inBlock) {
      if (ANNOTATION_END_RE.test(line)) {
        if (isFm) forbidden.add(lineNo)
        inBlock = false
        isFm = false
        continue
      }
      forbidden.add(lineNo)
      continue
    }

    if (ANNOTATION_RE.test(line)) {
      continue
    }
    if (ANNOTATION_OPEN_RE.test(line) && !ANNOTATION_END_RE.test(line)) {
      inBlock = true
      isFm = false
      forbidden.add(lineNo)
      continue
    }
    if (FRONT_MATTER_OPEN_RE.test(line)) {
      inBlock = true
      isFm = true
      forbidden.add(lineNo)
      continue
    }
  }

  return forbidden
}

export function buildAttachLinePickStates(content: string): Map<number, LinePickRowState> {
  const forbidden = collectAttachForbiddenLines(content)
  const m = new Map<number, LinePickRowState>()
  const n = content.split('\n').length
  for (let L = 1; L <= n; L++) {
    m.set(L, forbidden.has(L) ? 'annotation' : 'pickable')
  }
  return m
}

/**
 * A parsed annotation or front-matter block with span information.
 * All line numbers are 1-indexed inclusive.
 */
export interface AnnotationBlock {
  /** First line of the opening tag (1-indexed). */
  lineStart: number
  /** Last line of the block (inclusive, 1-indexed).
   *  For closed blocks: last line of the close tag.
   *  For unclosed blocks: last line of the open tag. */
  lineEnd: number
  operator: string
  id: string | null
  isClosing: boolean
  isSelfClosing: boolean
  isFrontMatter: boolean
  isClosed: boolean
  /** First line of the close tag (1-indexed), if closed. */
  closeLineStart?: number
  /** Last line of the close tag (1-indexed), if closed. */
  closeLineEnd?: number
}

/**
 * Parse raw markdown into structured annotation block info.
 *
 * Returns one entry per annotation or front-matter block. For annotations
 * that have a matching close tag, the block spans from open through close.
 * Mirrors Python's `parse_annotations()` + `parse_segments()` pairing logic.
 */
export function buildAnnotationBlocks(content: string): AnnotationBlock[] {
  const lines = content.split('\n')
  const blocks: AnnotationBlock[] = []

  // First pass: collect all raw annotation spans (open, close, self-closing, front-matter)
  interface RawSpan {
    lineStart: number  // 1-indexed
    lineEnd: number    // 1-indexed inclusive
    operator: string
    id: string | null
    isClosing: boolean
    isSelfClosing: boolean
    isFrontMatter: boolean
  }
  const spans: RawSpan[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    const lineNo = i + 1

    // Front-matter: bare `[` on its own line
    if (FRONT_MATTER_OPEN_RE.test(line)) {
      const start = lineNo
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i]!)) i++
      const end = i < lines.length ? i + 1 : i // include `]: #`
      spans.push({
        lineStart: start, lineEnd: end,
        operator: '', id: null,
        isClosing: false, isSelfClosing: false, isFrontMatter: true,
      })
      i++
      continue
    }

    // Multi-line annotation: [op(:id)? on its own line (no `]: #`)
    if (ANNOTATION_OPEN_RE.test(line) && !ANNOTATION_RE.test(line)) {
      const m = line.match(ANNOTATION_OPEN_RE)
      const start = lineNo
      i++
      while (i < lines.length && !ANNOTATION_END_RE.test(lines[i]!)) i++
      const end = i < lines.length ? i + 1 : i
      if (m?.groups) {
        spans.push({
          lineStart: start, lineEnd: end,
          operator: m.groups.operator ?? '',
          id: m.groups.id ?? null,
          isClosing: Boolean(m.groups.close),
          isSelfClosing: Boolean(m.groups.self_close),
          isFrontMatter: false,
        })
      }
      i++
      continue
    }

    // Single-line annotation: [op(:id)?(/)?]: #
    const m = line.match(ANNOTATION_RE)
    if (m?.groups) {
      spans.push({
        lineStart: lineNo, lineEnd: lineNo,
        operator: m.groups.operator ?? '',
        id: m.groups.id ?? null,
        isClosing: Boolean(m.groups.close),
        isSelfClosing: Boolean(m.groups.self_close),
        isFrontMatter: false,
      })
      i++
      continue
    }

    i++
  }

  // Second pass: pair opens with closes (mirrors parse_segments logic)
  const closesByKey = new Map<string, RawSpan[]>()
  for (const s of spans) {
    if (s.isClosing) {
      const key = `${s.operator}:${s.id ?? ''}`
      const arr = closesByKey.get(key) ?? []
      arr.push(s)
      closesByKey.set(key, arr)
    }
  }
  const closePtr = new Map<string, number>()

  for (const span of spans) {
    if (span.isFrontMatter) {
      blocks.push({
        lineStart: span.lineStart, lineEnd: span.lineEnd,
        operator: '', id: null,
        isClosing: false, isSelfClosing: false,
        isFrontMatter: true, isClosed: false,
      })
      continue
    }

    if (span.isClosing) {
      // Standalone close tags are included as blocks (they occupy lines)
      blocks.push({
        lineStart: span.lineStart, lineEnd: span.lineEnd,
        operator: span.operator, id: span.id,
        isClosing: true, isSelfClosing: false,
        isFrontMatter: false, isClosed: false,
      })
      continue
    }

    if (span.isSelfClosing) {
      blocks.push({
        lineStart: span.lineStart, lineEnd: span.lineEnd,
        operator: span.operator, id: span.id,
        isClosing: false, isSelfClosing: true,
        isFrontMatter: false, isClosed: true,
      })
      continue
    }

    // Opening annotation: try to find matching close
    const key = `${span.operator}:${span.id ?? ''}`
    const closes = closesByKey.get(key) ?? []
    let ptr = closePtr.get(key) ?? 0
    let matchedClose: RawSpan | null = null
    while (ptr < closes.length) {
      if (closes[ptr].lineStart > span.lineStart) {
        matchedClose = closes[ptr]
        closePtr.set(key, ptr + 1)
        break
      }
      ptr++
    }
    if (!matchedClose) closePtr.set(key, ptr)

    if (matchedClose) {
      blocks.push({
        lineStart: span.lineStart, lineEnd: matchedClose.lineEnd,
        operator: span.operator, id: span.id,
        isClosing: false, isSelfClosing: false,
        isFrontMatter: false, isClosed: true,
        closeLineStart: matchedClose.lineStart,
        closeLineEnd: matchedClose.lineEnd,
      })
    } else {
      blocks.push({
        lineStart: span.lineStart, lineEnd: span.lineEnd,
        operator: span.operator, id: span.id,
        isClosing: false, isSelfClosing: false,
        isFrontMatter: false, isClosed: false,
      })
    }
  }

  return blocks
}

/**
 * Compute valid end lines for a line-pick operation given a start line.
 *
 * For **edit** mode: mirrors `operator.py:1395-1402` — rejects ranges where
 * any annotation's opening line falls within [startLine, endLine].
 *
 * For **collate** mode: mirrors `collate.py:54-109` — rejects ranges that
 * split closed blocks, overlap unclosed annotations, or split front matter.
 */
export function computeValidEndLines(
  content: string,
  startLine: number,
  mode: 'edit' | 'collate',
): Set<number> {
  const totalLines = content.split('\n').length
  const annoSet = buildAnnotationLineSet(content)
  const blocks = buildAnnotationBlocks(content)

  const result = new Set<number>()

  if (mode === 'edit') {
    // Edit rule: range [startLine, L] must not contain any annotation's lineStart.
    // Find the first annotation lineStart > startLine — that's the ceiling.
    // (startLine itself is already a non-annotation line since the user picked it)
    let ceiling = totalLines
    for (const block of blocks) {
      // Only care about opening annotations (not standalone close tags, not front matter)
      // The Python check is: for a in anns: if start_line <= a.line_start <= end_line
      // So any annotation start within the range invalidates it.
      if (block.lineStart > startLine && block.lineStart <= totalLines) {
        ceiling = Math.min(ceiling, block.lineStart - 1)
      }
    }
    // Valid end lines: non-annotation lines in [startLine, ceiling]
    for (let l = startLine; l <= ceiling; l++) {
      if (!annoSet.has(l)) result.add(l)
    }
  } else {
    // Collate mode: more complex validation
    // For each candidate end line L >= startLine, check all blocks
    for (let l = startLine; l <= totalLines; l++) {
      if (annoSet.has(l)) continue  // annotation lines are not pickable

      let valid = true
      for (const block of blocks) {
        if (block.isClosing) continue  // standalone close tags handled via their paired open

        if (block.isFrontMatter) {
          // Front matter: cannot split
          const fmFirst = block.lineStart
          const fmLast = block.lineEnd
          const overlaps = fmFirst <= l && fmLast >= startLine
          const fullyInside = fmFirst >= startLine && fmLast <= l
          if (overlaps && !fullyInside) { valid = false; break }
          continue
        }

        if (block.isSelfClosing) continue  // self-closing: single line, already filtered by annoSet

        if (!block.isClosed) {
          // Unclosed annotation: any overlap is invalid
          // The unclosed annotation extends to end of file conceptually
          const segFirst = block.lineStart
          const segLast = totalLines
          const overlaps = segFirst <= l && segLast >= startLine
          if (overlaps) { valid = false; break }
          continue
        }

        // Closed annotation: cannot partially overlap
        const segFirst = block.lineStart
        const segLast = block.lineEnd  // includes close tag
        const overlaps = segFirst <= l && segLast >= startLine
        const fullyInside = segFirst >= startLine && segLast <= l
        if (overlaps && !fullyInside) { valid = false; break }
      }
      if (valid) result.add(l)
    }
  }

  return result
}

/**
 * Compute valid start lines for a line-pick operation.
 *
 * For **edit** mode: any non-annotation line (same as before — every
 * non-annotation start line has at least itself as a valid end).
 *
 * For **collate** mode: a start line is only valid if at least one end line
 * exists for it. Lines inside the body of a closed annotation block or after
 * an unclosed annotation are never valid starts because the range would always
 * partially overlap that block.
 */
export function computeValidStartLines(
  content: string,
  mode: 'edit' | 'collate',
): Set<number> {
  const annoSet = buildAnnotationLineSet(content)

  if (mode === 'edit') {
    // For edit, any non-annotation line is a valid start
    const totalLines = content.split('\n').length
    const result = new Set<number>()
    for (let l = 1; l <= totalLines; l++) {
      if (!annoSet.has(l)) result.add(l)
    }
    return result
  }

  // Collate mode: a start line is invalid if it's inside a block body
  // (between open and close tags of a closed block, or after an unclosed open tag)
  // because the range would always partially overlap that block.
  const totalLines = content.split('\n').length
  const blocks = buildAnnotationBlocks(content)

  // Build a set of lines that are "trapped" inside block bodies
  const trappedLines = new Set<number>()
  for (const block of blocks) {
    if (block.isClosing || block.isSelfClosing) continue

    if (block.isFrontMatter) {
      // Lines inside front matter body are annotation lines (already filtered)
      continue
    }

    if (block.isClosed) {
      // Any start line inside a closed block (after its open tag) can never
      // fully contain the block, so the range always partially overlaps → trapped.
      for (let l = block.lineStart + 1; l <= block.lineEnd; l++) {
        trappedLines.add(l)
      }
    } else {
      // Unclosed: everything from this annotation to end of file is trapped
      for (let l = block.lineStart; l <= totalLines; l++) {
        trappedLines.add(l)
      }
    }
  }

  const result = new Set<number>()
  for (let l = 1; l <= totalLines; l++) {
    if (!annoSet.has(l) && !trappedLines.has(l)) result.add(l)
  }
  return result
}

function fenceLang(info: string): string {
  return info.trim().split(/\s+/)[0] ?? ''
}

function renderToolCallFence(md: MarkdownIt, content: string): string {
  const body = content.replace(/\n$/, '')
  const lines = body.split('\n')
  const esc = md.utils.escapeHtml
  if (lines.length <= 1) {
    return `<pre><code class="language-tool-call">${esc(body)}</code></pre>\n`
  }
  const first = lines[0] ?? ''
  const rest = lines.slice(1).join('\n')
  const code = `<pre><code class="language-tool-call">${esc(rest)}</code></pre>\n`
  const preview = first.trim() === '' ? esc('(empty line)') : esc(first)
  return (
    `<details class="md-fence-tool-call">` +
    `<summary class="md-fence-tool-call-summary">` +
    `<span class="md-fence-tool-call-preview">${preview}</span>` +
    `<span class="md-fence-tool-call-expand" aria-hidden="true"></span>` +
    `</summary>` +
    code +
    `</details>\n`
  )
}

const THINKING_BLOCK_RE = /<(think|thinking)\b[^>]*>([\s\S]*?)<\/\1>/gi

export function preprocessThinkingTags(markdown: string): string {
  return markdown.replace(THINKING_BLOCK_RE, (_fullMatch, _tag, content: string) => {
    const body = content.replace(/^\n+|\n+$/g, '')
    return (
      `\n<details class="md-fence-tool-call md-fence-thinking">` +
      `<summary class="md-fence-tool-call-summary">` +
      `<span class="md-fence-tool-call-preview">Thinking</span>` +
      `<span class="md-fence-tool-call-expand" aria-hidden="true"></span>` +
      `</summary>` +
      `\n\n${body}\n\n` +
      `</details>\n`
    )
  })
}

/** Shared markdown-it instance with settings matching the app's rendering needs. */
export function createMarkdownRenderer(): MarkdownIt {
  const md = new MarkdownIt({ html: true, linkify: true, typographer: true })
  const fallback: NonNullable<typeof md.renderer.rules.link_open> = (tokens, idx, options, _env, self) =>
    self.renderToken(tokens, idx, options)
  const defaultLinkOpen = md.renderer.rules.link_open ?? fallback
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    const href = tokens[idx].attrGet('href')
    if (href?.startsWith('/mount/file/') || href?.startsWith('/mount/preview/')) {
      tokens[idx].attrSet('target', '_blank')
      tokens[idx].attrSet('rel', 'noopener')
    }
    return defaultLinkOpen(tokens, idx, options, env, self)
  }

  const defaultFence = md.renderer.rules.fence
  if (!defaultFence) {
    throw new Error('markdown-it: default fence rule missing')
  }
  md.renderer.rules.fence = (tokens, idx, options, env, self) => {
    const token = tokens[idx]
    if (token && fenceLang(token.info) === 'tool-call') {
      return renderToolCallFence(md, token.content)
    }
    return defaultFence(tokens, idx, options, env, self)
  }

  return md
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
