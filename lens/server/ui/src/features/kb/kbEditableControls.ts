import type { Attachment } from 'svelte/attachments'
import { quotePillHslVars } from '../../utils/markdown'

export interface KbEditMeta {
  id: string
  type: 'checkbox' | 'counter' | 'quote'
  rawStart: number
  rawEnd: number
  value: string
  max?: number
  /** `type: 'quote'` only — the bracketed label, e.g. `notes` in `> [notes] text`. */
  slug?: string
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const CHECKBOX_RE = /`\[([ x])]`/g
const COUNTER_RE = /`#(-?\d+)(?:\/(\d+))?`/g

// One editable line: chevron at column 0, a bracketed slug (no whitespace,
// at least one char), then free text to end of line (may be empty).
// `> [slug] text` — the same shape as the narrative attributed-blockquote
// pill (see `preprocessBlockquotePills` in utils/markdown.ts), reused here
// so KB "live state" fields (tracker conditions, notes, …) render as a pill
// instead of a fenced code block (fenced blocks can't nest inside the outer
// ```kb fence the design operator emits).
const QUOTE_LINE_RE = /^> \[([^\s\]]+)\] ?(.*)$/
const FENCE_MARKER_RE = /^\s*(`{3,}|~{3,})/

/** Line-based scan for `> [slug] text` rows, skipping lines inside fenced code blocks. */
function scanQuoteLines(content: string): { id: string; slug: string; text: string; start: number; end: number }[] {
  const out: { id: string; slug: string; text: string; start: number; end: number }[] = []
  const lines = content.split('\n')
  let offset = 0
  let inFence = false
  let quoteIdx = 0
  for (const line of lines) {
    if (FENCE_MARKER_RE.test(line)) {
      inFence = !inFence
    } else if (!inFence) {
      const m = QUOTE_LINE_RE.exec(line)
      if (m) {
        out.push({
          id: `quote-${quoteIdx++}`,
          slug: m[1]!,
          text: m[2] ?? '',
          start: offset,
          end: offset + line.length,
        })
      }
    }
    offset += line.length + 1
  }
  return out
}

/** Serialize a quote-line control back to raw markdown; always keeps the space after `]`. */
export function buildQuoteLinePattern(slug: string, text: string): string {
  return `> [${slug}] ${text}`
}

function buildQuoteLineHtml(id: string, slug: string, text: string): string {
  const { accent, border } = quotePillHslVars(slug)
  const style = `--quote-pill-accent:${accent};--quote-pill-border:${border}`
  const textHtml = text
    ? `<span class="kb-edit-quote-text">${escapeHtml(text)}</span>`
    : `<span class="kb-edit-quote-text kb-edit-quote-text--empty">Tap to edit</span>`
  return `<button type="button" class="kb-edit-quote-line" data-kb-edit-id="${id}"><span class="quote-pill" style="${style}">${escapeHtml(slug)}</span> ${textHtml}</button>`
}

export function scanControlPositions(content: string): KbEditMeta[] {
  const meta: KbEditMeta[] = []
  let checkboxIdx = 0
  let counterIdx = 0

  const quoteLines = scanQuoteLines(content)
  const quoteRanges: { start: number; end: number }[] = []
  for (const q of quoteLines) {
    meta.push({
      id: q.id,
      type: 'quote',
      rawStart: q.start,
      rawEnd: q.end,
      value: q.text,
      slug: q.slug,
    })
    quoteRanges.push({ start: q.start, end: q.end })
  }

  let m: RegExpExecArray | null

  CHECKBOX_RE.lastIndex = 0
  while ((m = CHECKBOX_RE.exec(content)) !== null) {
    if (
      quoteRanges.some(
        (r) => m!.index >= r.start && m!.index < r.end,
      )
    )
      continue
    const id = `checkbox-${checkboxIdx++}`
    const checked = m[1] === 'x'
    meta.push({
      id,
      type: 'checkbox',
      rawStart: m.index,
      rawEnd: m.index + m[0].length,
      value: checked ? 'x' : ' ',
    })
  }

  COUNTER_RE.lastIndex = 0
  while ((m = COUNTER_RE.exec(content)) !== null) {
    if (
      quoteRanges.some(
        (r) => m!.index >= r.start && m!.index < r.end,
      )
    )
      continue
    const id = `counter-${counterIdx++}`
    const value = m[1]!
    const max = m[2] !== undefined ? parseInt(m[2], 10) : undefined
    meta.push({
      id,
      type: 'counter',
      rawStart: m.index,
      rawEnd: m.index + m[0].length,
      value,
      max,
    })
  }

  return meta
}

export function preprocessKbEditableControls(content: string): {
  processed: string
  editMeta: KbEditMeta[]
} {
  const meta = scanControlPositions(content)

  // ── Phase 3: build HTML ────────────────────────────────────────────
  // 3a. Replace quote-line rows with a tappable pill button. The leading
  // `> ` stays in place so markdown-it still wraps the line in <blockquote>.
  const quoteReplacements: { start: number; end: number; html: string }[] = meta
    .filter((m) => m.type === 'quote')
    .map((m) => ({
      start: m.rawStart,
      end: m.rawEnd,
      html: '> ' + buildQuoteLineHtml(m.id, m.slug ?? '', m.value),
    }))

  let afterQuotes = content
  for (let i = quoteReplacements.length - 1; i >= 0; i--) {
    const r = quoteReplacements[i]!
    afterQuotes = afterQuotes.slice(0, r.start) + r.html + afterQuotes.slice(r.end)
  }

  // 3b. Build quote-button ranges in afterQuotes coordinates for inline exclusion
  // (a combatant's free-typed condition text could itself contain `[x]`/`#5`
  // patterns — those must not turn into nested interactive controls).
  const afterQuoteRanges: { start: number; end: number }[] = []
  {
    const quoteRe = /<button type="button" class="kb-edit-quote-line"/g
    let tm: RegExpExecArray | null
    while ((tm = quoteRe.exec(afterQuotes)) !== null) {
      const close = afterQuotes.indexOf('</button>', tm.index)
      if (close !== -1) {
        afterQuoteRanges.push({ start: tm.index, end: close + '</button>'.length })
      }
    }
  }

  // 3c. Scan afterQuotes for inline patterns — generate HTML controls
  const inlineReplacements: { start: number; end: number; html: string }[] = []
  let checkboxIdx = 0
  let counterIdx = 0

  CHECKBOX_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = CHECKBOX_RE.exec(afterQuotes)) !== null) {
    if (
      afterQuoteRanges.some(
        (r) => m!.index >= r.start && m!.index < r.end,
      )
    )
      continue
    const id = `checkbox-${checkboxIdx++}`
    const checked = m[1] === 'x'
    inlineReplacements.push({
      start: m.index,
      end: m.index + m[0].length,
      html: `<input type="checkbox" class="kb-edit-checkbox" data-kb-edit-id="${id}"${checked ? ' checked' : ''}>`,
    })
  }

  COUNTER_RE.lastIndex = 0
  while ((m = COUNTER_RE.exec(afterQuotes)) !== null) {
    if (
      afterQuoteRanges.some(
        (r) => m!.index >= r.start && m!.index < r.end,
      )
    )
      continue
    const id = `counter-${counterIdx++}`
    const value = m[1]!
    const max = m[2] !== undefined ? parseInt(m[2], 10) : undefined
    const ariaMax = max !== undefined ? ` aria-valuemax="${max}"` : ''
    const maxLabel =
      max !== undefined
        ? `<span class="kb-edit-counter-max">/ ${max}</span>`
        : ''
    const decBtn = `<button class="kb-edit-counter-btn kb-edit-counter-btn--dec" data-kb-edit-id="${id}" data-kb-edit-action="dec" tabindex="-1" aria-label="Decrease" type="button">−</button>`
    const incBtn = `<button class="kb-edit-counter-btn kb-edit-counter-btn--inc" data-kb-edit-id="${id}" data-kb-edit-action="inc" tabindex="-1" aria-label="Increase" type="button">+</button>`
    const inputEl = `<input type="text" inputmode="numeric" role="spinbutton" data-kb-edit-id="${id}" value="${value}" aria-valuenow="${value}" aria-valuemin="0"${ariaMax}>`
    inlineReplacements.push({
      start: m.index,
      end: m.index + m[0].length,
      html: `<span class="kb-edit-counter" role="group">${decBtn}${inputEl}${maxLabel}${incBtn}</span>`,
    })
  }

  // 3d. Apply inline replacements (descending position to avoid shift)
  let result = afterQuotes
  const sorted = [...inlineReplacements].sort((a, b) => b.start - a.start)
  for (const r of sorted) {
    result = result.slice(0, r.start) + r.html + result.slice(r.end)
  }

  return { processed: result, editMeta: meta }
}

export function attachKbEditableControls(
  editMeta: KbEditMeta[],
  getContent: () => string,
  saveContent: (newContent: string) => void,
  openQuoteEditor: (meta: KbEditMeta) => void,
): Attachment<HTMLDivElement> {
  if (editMeta.length === 0) return () => () => {}

  const timers = new Map<string, ReturnType<typeof setTimeout>>()

  return (element) => {
    function handleEvent(e: Event) {
      const target = e.target as HTMLElement
      const editId = target.getAttribute('data-kb-edit-id')
      if (!editId) return

      // Rescan current content for fresh positions — the cached editMeta
      // positions become stale when a previous control changes length
      // (e.g. `#11/11`→`#8/11` shifts all subsequent patterns by -1).
      const fullContent = getContent()
      const freshMeta = scanControlPositions(fullContent)
      const meta = freshMeta.find((em) => em.id === editId)
      if (!meta) return

      let newContent: string

      if (meta.type === 'checkbox') {
        const checked = (target as HTMLInputElement).checked
        const charPos = meta.rawStart + 2
        newContent =
          fullContent.slice(0, charPos) +
          (checked ? 'x' : ' ') +
          fullContent.slice(charPos + 1)
      } else if (meta.type === 'counter') {
        const btnAction = target.getAttribute('data-kb-edit-action')
        const input = btnAction
          ? ((target as HTMLElement)
              .parentElement as HTMLElement)
              .querySelector<HTMLInputElement>('input[role="spinbutton"]')
          : (target as HTMLInputElement)
        if (!input) return
        let raw = input.value
        if (btnAction === 'inc') {
          raw = String(parseInt(raw, 10) + 1)
        } else if (btnAction === 'dec') {
          raw = String(parseInt(raw, 10) - 1)
        }
        const n = parseInt(raw, 10)
        const val = isNaN(n)
          ? '0'
          : n < 0
            ? '0'
            : meta.max !== undefined && n > meta.max
              ? String(meta.max)
              : String(n)
        input.value = val
        input.setAttribute('aria-valuenow', val)
        const pattern =
          meta.max !== undefined
            ? `\`#${val}/${meta.max}\``
            : `\`#${val}\``
        newContent =
          fullContent.slice(0, meta.rawStart) +
          pattern +
          fullContent.slice(meta.rawEnd)
      } else {
        // Quote lines are edited via dialog (see handleClick), never inline.
        return
      }

      const existing = timers.get(editId)
      if (existing) clearTimeout(existing)
      timers.set(
        editId,
        setTimeout(() => {
          saveContent(newContent)
          timers.delete(editId)
        }, 600),
      )
    }

    function handleClick(e: Event) {
      const target = e.target as HTMLElement

      const quoteBtn = target.closest('.kb-edit-quote-line') as HTMLElement | null
      if (quoteBtn) {
        const editId = quoteBtn.getAttribute('data-kb-edit-id')
        if (!editId) return
        // Rescan for a fresh position — earlier edits on the same node can
        // have shifted this line since editMeta was first computed.
        const freshMeta = scanControlPositions(getContent())
        const meta = freshMeta.find((em) => em.id === editId && em.type === 'quote')
        if (meta) openQuoteEditor(meta)
        return
      }

      if (target.getAttribute('data-kb-edit-action')) {
        handleEvent(e)
      }
      if (target.tagName === 'INPUT' && target.getAttribute('role') === 'spinbutton') {
        ;(target as HTMLInputElement).select()
      }
    }

    element.addEventListener('change', handleEvent)
    element.addEventListener('input', handleEvent)
    element.addEventListener('click', handleClick)

    return () => {
      element.removeEventListener('change', handleEvent)
      element.removeEventListener('input', handleEvent)
      element.removeEventListener('click', handleClick)
      timers.forEach((t) => clearTimeout(t))
      timers.clear()
    }
  }
}
