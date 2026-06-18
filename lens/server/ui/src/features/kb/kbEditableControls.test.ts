import { describe, it, expect } from 'vitest'
import { preprocessKbEditableControls, scanControlPositions } from './kbEditableControls'
import { stripKbItemFrontMatter } from './kbViewerMarkdown'

describe('preprocessKbEditableControls', () => {
  it('converts a single checkbox', () => {
    const { processed, editMeta } = preprocessKbEditableControls('Status: `[x]`')
    expect(processed).toContain('<input type="checkbox"')
    expect(processed).toContain('checked')
    expect(processed).not.toContain('`[x]`')
    expect(editMeta).toHaveLength(1)
  })

  it('converts a single counter', () => {
    const { processed, editMeta } = preprocessKbEditableControls('HP: `#65/65`')
    expect(processed).toContain('class="kb-edit-counter"')
    expect(processed).toContain('value="65"')
    expect(processed).toContain('/ 65')
    expect(processed).not.toContain('`#65/65`')
    expect(editMeta).toHaveLength(1)
  })

  it('handles checkbox before counter on same line', () => {
    const { processed } = preprocessKbEditableControls('Raging: `[x]`  HP: `#65/65`')
    expect(processed).toContain('checkbox')
    expect(processed).toContain('kb-edit-counter')
    // both intact, not garbled
    expect(processed).not.toMatch(/kb-ed<.*unter/)
  })

  it('handles checkbox after counter that is on an earlier line', () => {
    // This ordering exercises the sort-by-position fix — the counter (lower
    // position) is pushed to the replacement array *after* the checkbox (higher
    // position) because the checkbox RE loop runs first.
    const md = 'HP: `#65/65`\n\nActive: `[x]`'
    const { processed, editMeta } = preprocessKbEditableControls(md)
    expect(processed).toContain('kb-edit-counter')
    expect(processed).toContain('checkbox')
    // counter span must not be fractured by checkbox replacement
    expect(processed).not.toMatch(/kb-ed<.*unter/)
    expect(editMeta).toHaveLength(2)
  })

  it('handles three items: checkbox, counter, checkbox', () => {
    const md = 'Raging: `[x]`\n\nHP: `#65/65`\n\nActive: `[x]`'
    const { processed, editMeta } = preprocessKbEditableControls(md)
    // Both checkboxes and the counter converted
    expect(processed.match(/type="checkbox"/g)).toHaveLength(2)
    expect(processed.match(/role="group"/g)).toHaveLength(1)
    // Counter span intact
    expect(processed).toMatch(
      /<span class="kb-edit-counter" role="group">/,
    )
    expect(editMeta).toHaveLength(3)
  })

  it('converts unchecked checkbox', () => {
    const { processed } = preprocessKbEditableControls('Flag: `[ ]`')
    expect(processed).toContain('<input type="checkbox"')
    expect(processed).not.toContain('checked')
  })

  it('skips content inside notes fences', () => {
    const md = '```notes\n`[x]` and `#42`\n```'
    const { processed, editMeta } = preprocessKbEditableControls(md)
    expect(processed).toContain('<textarea')
    // inner backtick patterns are consumed by the notes fence
    const notesMeta = editMeta.filter((m) => m.type === 'notes')
    expect(notesMeta).toHaveLength(1)
    expect(editMeta.filter((m) => m.type !== 'notes')).toHaveLength(0)
  })

  it('returns correct editMeta offsets', () => {
    const md = 'A: `[x]`\n\nB: `#10`'
    const { editMeta } = preprocessKbEditableControls(md)
    // checkbox
    expect(editMeta[0]!.type).toBe('checkbox')
    expect(editMeta[0]!.value).toBe('x')
    expect(editMeta[0]!.rawStart).toBeGreaterThanOrEqual(0)
    expect(editMeta[0]!.rawEnd).toBeGreaterThan(editMeta[0]!.rawStart)
    // counter
    expect(editMeta[1]!.type).toBe('counter')
    expect(editMeta[1]!.value).toBe('10')
    expect(editMeta[1]!.max).toBeUndefined()
  })

  it('assigns per-type sequence IDs', () => {
    const md = 'a: `[x]`\nb: `#1`\nc: `[ ]`\nd: `#2`'
    const { editMeta } = preprocessKbEditableControls(md)
    // editMeta order follows scan order: notes → checkboxes → counters
    expect(editMeta[0]!.id).toBe('checkbox-0')
    expect(editMeta[1]!.id).toBe('checkbox-1')
    expect(editMeta[2]!.id).toBe('counter-0')
    expect(editMeta[3]!.id).toBe('counter-1')
  })

  it('assigns per-type sequence IDs for notes alongside inline controls', () => {
    const md = '```notes\nx\n```\nHP: `#10`'
    const { editMeta } = preprocessKbEditableControls(md)
    expect(editMeta[0]!.id).toBe('notes-0')
    expect(editMeta[1]!.id).toBe('counter-0')
  })

  it('counters before empty notes blocks survive position shift from earlier notes', () => {
    // Notes block BEFORE the details group causes a position shift that
    // pushes subsequent counters beyond the original notes-block start,
    // but they should NOT be incorrectly identified as inside the notes block.
    const md = [
      'before: `[x]`',
      '',
      '```notes',
      'longer content here',
      '```',
      '',
      '<details><summary>Bandit. HP: `#11/11`</summary>',
      '```notes',
      '```',
      '</details>',
    ].join('\n')
    const { editMeta } = preprocessKbEditableControls(md)
    const counters = editMeta.filter((m) => m.type === 'counter')
    // The counter must be found (should NOT be falsely excluded)
    expect(counters).toHaveLength(1)
    const notes = editMeta.filter((m) => m.type === 'notes')
    expect(notes).toHaveLength(2)
  })

  it('converts all counters in multi-bandit details with mix of empty and non-empty notes', () => {
    // Reproduction of the user's scenario
    const md = [
      '```notes',
      'content',
      '```',
      '',
      '<details><summary>B1. HP: `#11/11`</summary>',
      '```notes',
      '```',
      '</details>',
      '',
      '<details><summary>B2. HP: `#3/11`</summary>',
      '```notes',
      'prone',
      '```',
      '</details>',
      '',
      '<details><summary>B3. HP: `#10/11`</summary>',
      '```notes',
      '```',
      '</details>',
    ].join('\n')
    const { editMeta } = preprocessKbEditableControls(md)
    const counters = editMeta.filter((m) => m.type === 'counter')
    expect(counters).toHaveLength(3)
  })

  it('editing empty notes content produces valid markdown', () => {
    const body = [
      '<details><summary>13 - [Bandit 1](kb/stat.bandit). HP: `#11/11`</summary>Conditions: ',
      '```notes',
      '```',
      '</details>',
      '',
      '<details><summary>13 - [Bandit 2](kb/stat.bandit). HP: `#3/11`</summary>Conditions: ',
      '```notes',
      'Prone',
      '```',
      '</details>',
    ].join('\n')

    const { editMeta } = preprocessKbEditableControls(body)
    const notesMeta = editMeta.find((m) => m.type === 'notes' && editMeta.indexOf(m) === 0)!
    expect(notesMeta.value).toBe('')
    expect(notesMeta.rawEnd - notesMeta.rawStart).toBe(12)

    // Simulate save handler: replace empty notes with "stunned"
    const text = 'stunned'
    const pattern = '```notes\n' + text + '\n```'
    const newContent =
      body.slice(0, notesMeta.rawStart) + pattern + body.slice(notesMeta.rawEnd)

    // Bandit 1's notes block must close correctly
    const b1Match = newContent.match(/Bandit 1[\s\S]*?```notes\n([\s\S]*?)\n```/)
    expect(b1Match).not.toBeNull()
    expect(b1Match![1]).toBe('stunned')
    // Bandit 2 must survive untouched
    expect(newContent).toContain('Bandit 2')
    expect(newContent).toContain('Prone')
    // No broken fences
    expect(newContent).not.toMatch(/```nned/)
    expect(newContent).not.toMatch(/```nails/)
  })

  it('editing notes through renderKbMarkdown bodyOffset preserves integrity', () => {
    // Full content with front matter — what renderKbMarkdown receives
    const fullContent = [
      '[',
      '    kb-details: true',
      ']: #',
      '',
      '<details><summary>13 - [Bandit 1](kb/stat.bandit). HP: `#11/11`</summary>Conditions: ',
      '```notes',
      '```',
      '</details>',
      '',
      '<details><summary>13 - [Bandit 2](kb/stat.bandit). HP: `#3/11`</summary>Conditions: ',
      '```notes',
      'Prone',
      '```',
      '</details>',
    ].join('\n')

    // Simulate what renderKbMarkdown does
    const { body } = stripKbItemFrontMatter(fullContent)
    const bodyOffset = fullContent.indexOf(body)

    const result = preprocessKbEditableControls(body)
    const editMeta = result.editMeta

    // Apply bodyOffset — same as renderKbMarkdown
    for (const m of editMeta) {
      m.rawStart += bodyOffset
      m.rawEnd += bodyOffset
    }

    // Now simulate the save handler with FULL content (what getContent() returns)
    const notesMeta = editMeta.find((m) => m.type === 'notes' && m.id === 'notes-0')!
    expect(notesMeta.value).toBe('')

    const text = 'stunned'
    const pattern = '```notes\n' + text + '\n```'
    const newContent =
      fullContent.slice(0, notesMeta.rawStart) + pattern + fullContent.slice(notesMeta.rawEnd)

    // Bandit 1's notes must close correctly
    const b1Match = newContent.match(/Bandit 1[\s\S]*?```notes\n([\s\S]*?)\n```/)
    expect(b1Match).not.toBeNull()
    expect(b1Match![1]).toBe('stunned')
    // Bandit 2 must survive
    expect(newContent).toContain('Bandit 2')
    expect(newContent).toContain('Prone')
    // No corruption — "nned" must not appear on the `` ``` `` fence line itself
    expect(newContent).not.toMatch(/```nned/)
  })

describe('scanControlPositions', () => {
  it('returns correct positions for a counter', () => {
    const meta = scanControlPositions('HP: `#11/11`')
    expect(meta).toHaveLength(1)
    expect(meta[0]!.id).toBe('counter-0')
    expect(meta[0]!.rawStart).toBe(4)
    expect(meta[0]!.rawEnd).toBe(12)
    expect(meta[0]!.max).toBe(11)
  })

  it('adjusts positions when a previous counter changes digit count', () => {
    // Initial:  HP: `#11/11`\n\nAC: `#10`
    // counter-0 at pos 4 (8 chars: `#11/11`)
    // counter-1 at pos 18 (5 chars: `#10`)
    const initial = 'HP: `#11/11`\n\nAC: `#10`'
    const meta0 = scanControlPositions(initial)
    expect(meta0).toHaveLength(2)
    expect(meta0[0]!.id).toBe('counter-0')
    expect(meta0[1]!.id).toBe('counter-1')
    const c0pos0 = meta0[0]!.rawStart
    expect(c0pos0).toBe(4)
    expect(meta0[0]!.rawEnd).toBe(12) // 4 + 8
    expect(meta0[1]!.rawStart).toBe(18)
    expect(meta0[1]!.rawEnd).toBe(23) // 18 + 5

    // Simulate editing counter-0 from #11/11 to #8/11 (7 chars)
    const modified =
      initial.slice(0, c0pos0) + '`#8/11`' + initial.slice(c0pos0 + 8)
    expect(modified).toBe('HP: `#8/11`\n\nAC: `#10`')

    const meta1 = scanControlPositions(modified)
    expect(meta1).toHaveLength(2)
    // counter-0 now shorter by 1
    expect(meta1[0]!.rawStart).toBe(4)
    expect(meta1[0]!.rawEnd).toBe(11) // 4 + 7
    // counter-1 shifted by -1 (18 → 17)
    expect(meta1[1]!.rawStart).toBe(17)
    expect(meta1[1]!.rawEnd).toBe(22) // 17 + 5

    // Verify: editing counter-1 using fresh positions works
    const c1 = meta1[1]!
    const newContent =
      modified.slice(0, c1.rawStart) +
      '`#8`' +
      modified.slice(c1.rawEnd)
    expect(newContent).toBe('HP: `#8/11`\n\nAC: `#8`')
  })

  it('does not match controls inside notes fences', () => {
    const content = '```notes\n`[x]` and `#42`\n```\nOutside: `#1`'
    const meta = scanControlPositions(content)
    const notes = meta.filter((m) => m.type === 'notes')
    const counters = meta.filter((m) => m.type === 'counter')
    expect(notes).toHaveLength(1)
    expect(counters).toHaveLength(1)
    expect(counters[0]!.value).toBe('1')
  })

  it('returns correct positions with front matter present', () => {
    // scanControlPositions returns in type-group order: notes → checkboxes → counters
    const full = [
      '[',
      '    kb-details: true',
      ']: #',
      '',
      'HP: `#11/11`',
      '',
      'Active: `[x]`',
    ].join('\n')
    const meta = scanControlPositions(full)
    expect(meta).toHaveLength(2)
    // meta[0] is checkbox (type group order: checkboxes before counters)
    expect(meta[0]!.type).toBe('checkbox')
    expect(meta[0]!.id).toBe('checkbox-0')
    // meta[1] is counter
    expect(meta[1]!.type).toBe('counter')
    expect(meta[1]!.id).toBe('counter-0')
    // Positions can be used to slice full content
    expect(full.slice(meta[0]!.rawStart, meta[0]!.rawEnd)).toBe('`[x]`')
    expect(full.slice(meta[1]!.rawStart, meta[1]!.rawEnd)).toBe('`#11/11`')
  })

  it('preserves correct positions for notes after a length-changing counter edit', () => {
    // scanControlPositions returns in type-group order: notes → checkboxes → counters
    // So meta[0] is notes, meta[1] is counter.
    const initial = 'HP: `#11/11`\n\n```notes\nfoo\n```'
    const meta0 = scanControlPositions(initial)
    expect(meta0).toHaveLength(2)
    expect(meta0[0]!.type).toBe('notes')
    expect(meta0[1]!.type).toBe('counter')
    const notesStart0 = meta0[0]!.rawStart
    const notesLen0 = meta0[0]!.rawEnd - meta0[0]!.rawStart

    // Edit counter-0: #11/11 → #8/11 (shorter by 1) — shifts notes by -1
    const modified = 'HP: `#8/11`\n\n```notes\nfoo\n```'
    const meta1 = scanControlPositions(modified)
    expect(meta1).toHaveLength(2)
    expect(meta1[1]!.rawEnd - meta1[1]!.rawStart).toBe(7) // `#8/11`
    // Notes block shifted by -1
    expect(meta1[0]!.rawStart).toBe(notesStart0 - 1)
    expect(meta1[0]!.rawEnd - meta1[0]!.rawStart).toBe(notesLen0)
  })
})

  it('merges adjacent notes blocks (no closing ``` between them) into one textarea', () => {
    // When two notes blocks are adjacent — i.e. the first closes with ` ``` `
    // but the next line immediately opens ` ```notes ` — we get the ambiguous
    // pattern `\n```notes\ncontent1\n```notes\ncontent2\n```\n`.  The regex
    // `^```\s*$` does not match a line with ` ```notes `, so the lazy
    // matcher consumes everything up to the final ``` on its own line.
    const md = [
      '<details><summary>B1. HP: `#1/5`</summary>',
      '```notes',
      'stunned',
      '```notes',    // no proper closing before second opening
      'Prone',
      '```',
      '</details>',
    ].join('\n')
    const { editMeta } = preprocessKbEditableControls(md)
    const notes = editMeta.filter((m) => m.type === 'notes')
    expect(notes).toHaveLength(1)
    expect(notes[0]!.value).toBe('stunned\n```notes\nProne')
    const counters = editMeta.filter((m) => m.type === 'counter')
    expect(counters).toHaveLength(1)
    expect(counters[0]!.value).toBe('1')
  })
})
