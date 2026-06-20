import type { Attachment } from 'svelte/attachments'

export interface KbEditMeta {
  id: string
  type: 'checkbox' | 'counter' | 'notes'
  rawStart: number
  rawEnd: number
  value: string
  max?: number
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const CHECKBOX_RE = /`\[([ x])]`/g
const COUNTER_RE = /`#(-?\d+)(?:\/(\d+))?`/g
const NOTES_BLOCK_RE = /^```notes\s*$\n?([\s\S]*?)\n?^```\s*$/gm

export function scanControlPositions(content: string): KbEditMeta[] {
  const meta: KbEditMeta[] = []
  let notesIdx = 0
  let checkboxIdx = 0
  let counterIdx = 0

  const notesRanges: { start: number; end: number }[] = []
  let m: RegExpExecArray | null

  NOTES_BLOCK_RE.lastIndex = 0
  while ((m = NOTES_BLOCK_RE.exec(content)) !== null) {
    const id = `notes-${notesIdx++}`
    const raw = m[0]
    const inner = m[1]!
    meta.push({
      id,
      type: 'notes',
      rawStart: m.index,
      rawEnd: m.index + raw.length,
      value: inner,
    })
    notesRanges.push({ start: m.index, end: m.index + raw.length })
  }

  CHECKBOX_RE.lastIndex = 0
  while ((m = CHECKBOX_RE.exec(content)) !== null) {
    if (
      notesRanges.some(
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
      notesRanges.some(
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
  // 3a. Replace notes blocks with <textarea>
  const notesReplacements: { start: number; end: number; html: string }[] = meta
    .filter((m) => m.type === 'notes')
    .map((m) => ({
      start: m.rawStart,
      end: m.rawEnd,
      html: `<textarea class="kb-edit-notes" data-kb-edit-id="${m.id}">${escapeHtml(m.value)}</textarea>`,
    }))

  let afterNotes = content
  for (let i = notesReplacements.length - 1; i >= 0; i--) {
    const r = notesReplacements[i]!
    afterNotes = afterNotes.slice(0, r.start) + r.html + afterNotes.slice(r.end)
  }

  // 3b. Build notes ranges in afterNotes coordinates for inline exclusion
  const afterNotesRanges: { start: number; end: number }[] = []
  {
    const notesRe = /<textarea\b/g
    let tm: RegExpExecArray | null
    while ((tm = notesRe.exec(afterNotes)) !== null) {
      const close = afterNotes.indexOf('</textarea>', tm.index)
      if (close !== -1) {
        afterNotesRanges.push({ start: tm.index, end: close + '</textarea>'.length })
      }
    }
  }

  // 3c. Scan afterNotes for inline patterns — generate HTML controls
  const inlineReplacements: { start: number; end: number; html: string }[] = []
  let checkboxIdx = 0
  let counterIdx = 0

  CHECKBOX_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = CHECKBOX_RE.exec(afterNotes)) !== null) {
    if (
      afterNotesRanges.some(
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
  while ((m = COUNTER_RE.exec(afterNotes)) !== null) {
    if (
      afterNotesRanges.some(
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
  let result = afterNotes
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
        const text = (target as HTMLTextAreaElement).value
        const pattern = '```notes\n' + text + '\n```'
        newContent =
          fullContent.slice(0, meta.rawStart) +
          pattern +
          fullContent.slice(meta.rawEnd)
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
