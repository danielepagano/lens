import { describe, it, expect } from 'vitest'
import { preprocessKbEditableControls, scanControlPositions, buildQuoteLinePattern } from './kbEditableControls'
import { renderKbMarkdown, stripKbItemFrontMatter } from './kbViewerMarkdown'

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

  it('converts a quote line into a tappable pill button', () => {
    const { processed, editMeta } = preprocessKbEditableControls('> [conditions] Prone')
    expect(processed).toContain('<button type="button" class="kb-edit-quote-line"')
    expect(processed).toContain('class="quote-pill"')
    expect(processed).toContain('conditions')
    expect(processed).toContain('Prone')
    expect(processed).not.toContain('> [conditions] Prone')
    expect(editMeta).toHaveLength(1)
    expect(editMeta[0]!.type).toBe('quote')
    expect(editMeta[0]!.slug).toBe('conditions')
    expect(editMeta[0]!.value).toBe('Prone')
  })

  it('renders an empty quote line with a placeholder', () => {
    const { processed, editMeta } = preprocessKbEditableControls('> [conditions] ')
    expect(processed).toContain('kb-edit-quote-text--empty')
    expect(editMeta[0]!.value).toBe('')
  })

  it('does not treat an indented `>` line as a quote control (chevron must be at column 0)', () => {
    const { editMeta } = preprocessKbEditableControls('  > [conditions] Prone')
    expect(editMeta.filter((m) => m.type === 'quote')).toHaveLength(0)
  })

  it('requires the slug to have no whitespace', () => {
    const { editMeta } = preprocessKbEditableControls('> [not a slug] text')
    expect(editMeta.filter((m) => m.type === 'quote')).toHaveLength(0)
  })

  it('skips checkbox/counter patterns inside a quote line\'s own text', () => {
    // A combatant's free-typed condition text could itself contain `[x]`/`#5` —
    // those must stay literal text inside the pill button, not become nested controls.
    const { processed, editMeta } = preprocessKbEditableControls('> [conditions] wearing `[x]` armor, `#5` charges left')
    expect(editMeta).toHaveLength(1)
    expect(editMeta[0]!.type).toBe('quote')
    expect(processed).not.toContain('<input type="checkbox"')
    expect(processed).not.toContain('kb-edit-counter')
  })

  it('skips quote-line patterns inside fenced code blocks', () => {
    const md = '```\n> [conditions] example\n```\n> [conditions] real'
    const { editMeta } = preprocessKbEditableControls(md)
    const quotes = editMeta.filter((m) => m.type === 'quote')
    expect(quotes).toHaveLength(1)
    expect(quotes[0]!.value).toBe('real')
  })

  it('consecutive quote lines with no blank line between them still each render and edit independently', () => {
    // Not a bug: markdown merges adjacent `>` lines with no blank line
    // between them into one shared blockquote, but each quote-line button
    // keeps its own data-kb-edit-id and its own display:block row — this is
    // the tracker template's actual (compact, intentional) shape.
    const md = '> [position] Airborne\n> [conditions] Prone'
    const { html, editMeta } = renderKbMarkdown(md, null, null, true)
    expect((html.match(/<blockquote>/g) ?? []).length).toBe(1)
    expect(editMeta.filter((m) => m.type === 'quote')).toHaveLength(2)
    expect(html.match(/data-kb-edit-id="quote-0"/g)).toHaveLength(1)
    expect(html.match(/data-kb-edit-id="quote-1"/g)).toHaveLength(1)
  })

  it('regression: a quote line right after an unclosed HTML block (no blank line) never becomes a blockquote', () => {
    // `<details>` opens a raw HTML block; CommonMark treats everything after
    // it as literal text (no lists, no blockquotes) until a blank line hands
    // control back to the block parser. Skipping that blank line is exactly
    // what regressed the tracker template — the `>` stays a stray character
    // instead of framing the pill.
    const md = ['<details><summary>X</summary>', '- Reaction Used: `[ ]`', '> [conditions] Prone', '</details>'].join(
      '\n',
    )
    const { html } = renderKbMarkdown(md, null, null, true)
    expect(html).not.toContain('<blockquote>')
    // The button itself still renders (our own preprocessing doesn't need
    // markdown-it's blockquote parsing) — but a bare `>` sits in front of it.
    expect(html).toMatch(/>\s*<button type="button" class="kb-edit-quote-line"/)
  })

  it('a blank line before the quote-line group is enough to fix it', () => {
    const md = [
      '<details><summary>X</summary>',
      '- Reaction Used: `[ ]`',
      '',
      '> [position] Airborne',
      '> [conditions] Prone',
      '</details>',
    ].join('\n')
    const { html } = renderKbMarkdown(md, null, null, true)
    expect((html.match(/<blockquote>/g) ?? []).length).toBe(1)
    expect(html.match(/data-kb-edit-id="quote-[01]"/g)).toHaveLength(2)
  })

  it('handles multiple quote lines alongside checkboxes and counters', () => {
    const md = [
      '<details><summary>13 - [Bandit 1](kb/stat.bandit). HP: `#11/11`</summary>',
      '- Reaction Used: `[ ]`',
      '> [conditions] ',
      '</details>',
      '',
      '<details><summary>13 - [Bandit 2](kb/stat.bandit). HP: `#3/11`</summary>',
      '- Reaction Used: `[x]`',
      '> [conditions] Prone',
      '</details>',
    ].join('\n')
    const { editMeta } = preprocessKbEditableControls(md)
    const quotes = editMeta.filter((m) => m.type === 'quote')
    const checkboxes = editMeta.filter((m) => m.type === 'checkbox')
    const counters = editMeta.filter((m) => m.type === 'counter')
    expect(quotes).toHaveLength(2)
    expect(checkboxes).toHaveLength(2)
    expect(counters).toHaveLength(2)
    expect(quotes[0]!.id).toBe('quote-0')
    expect(quotes[1]!.id).toBe('quote-1')
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
    // editMeta order follows scan order: quote lines → checkboxes → counters
    expect(editMeta[0]!.id).toBe('checkbox-0')
    expect(editMeta[1]!.id).toBe('checkbox-1')
    expect(editMeta[2]!.id).toBe('counter-0')
    expect(editMeta[3]!.id).toBe('counter-1')
  })

  it('assigns per-type sequence IDs for quote lines alongside inline controls', () => {
    const md = '> [conditions] x\nHP: `#10`'
    const { editMeta } = preprocessKbEditableControls(md)
    expect(editMeta[0]!.id).toBe('quote-0')
    expect(editMeta[1]!.id).toBe('counter-0')
  })

  it('editing a quote line through renderKbMarkdown bodyOffset preserves integrity', () => {
    // Full content with front matter — what renderKbMarkdown receives
    const fullContent = [
      '[',
      '    kb-details: true',
      ']: #',
      '',
      '<details><summary>13 - [Bandit 1](kb/stat.bandit). HP: `#11/11`</summary>',
      '> [conditions] ',
      '</details>',
      '',
      '<details><summary>13 - [Bandit 2](kb/stat.bandit). HP: `#3/11`</summary>',
      '> [conditions] Prone',
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

    const quoteMeta = editMeta.find((m) => m.type === 'quote' && m.id === 'quote-0')!
    expect(quoteMeta.value).toBe('')
    expect(quoteMeta.slug).toBe('conditions')

    const pattern = buildQuoteLinePattern(quoteMeta.slug!, 'stunned')
    const newContent = fullContent.slice(0, quoteMeta.rawStart) + pattern + fullContent.slice(quoteMeta.rawEnd)

    // Bandit 1's line updates in place
    expect(newContent).toContain('> [conditions] stunned')
    // Bandit 2 survives untouched
    expect(newContent).toContain('Bandit 2')
    expect(newContent).toContain('> [conditions] Prone')
  })
})

describe('buildQuoteLinePattern', () => {
  it('always keeps a space after the closing bracket, even for empty text', () => {
    expect(buildQuoteLinePattern('conditions', '')).toBe('> [conditions] ')
  })

  it('serializes slug and text', () => {
    expect(buildQuoteLinePattern('conditions', 'Prone, Restrained')).toBe('> [conditions] Prone, Restrained')
  })

  it('round-trips through scanControlPositions', () => {
    const pattern = buildQuoteLinePattern('notes', 'stunned')
    const meta = scanControlPositions(pattern)
    expect(meta).toHaveLength(1)
    expect(meta[0]!.slug).toBe('notes')
    expect(meta[0]!.value).toBe('stunned')
  })
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

  it('does not match controls inside a quote line', () => {
    const content = '> [conditions] `[x]` and `#42`\nOutside: `#1`'
    const meta = scanControlPositions(content)
    const quotes = meta.filter((m) => m.type === 'quote')
    const counters = meta.filter((m) => m.type === 'counter')
    expect(quotes).toHaveLength(1)
    expect(counters).toHaveLength(1)
    expect(counters[0]!.value).toBe('1')
  })

  it('returns correct positions with front matter present', () => {
    // scanControlPositions returns in type-group order: quote lines → checkboxes → counters
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

  it('preserves correct positions for a quote line after a length-changing counter edit', () => {
    // scanControlPositions returns in type-group order: quote lines → counters
    // So meta[0] is the quote line, meta[1] is the counter.
    const initial = 'HP: `#11/11`\n\n> [conditions] Prone'
    const meta0 = scanControlPositions(initial)
    expect(meta0).toHaveLength(2)
    expect(meta0[0]!.type).toBe('quote')
    expect(meta0[1]!.type).toBe('counter')
    const quoteStart0 = meta0[0]!.rawStart
    const quoteLen0 = meta0[0]!.rawEnd - meta0[0]!.rawStart

    // Edit counter-0: #11/11 → #8/11 (shorter by 1) — shifts the quote line by -1
    const modified = 'HP: `#8/11`\n\n> [conditions] Prone'
    const meta1 = scanControlPositions(modified)
    expect(meta1).toHaveLength(2)
    expect(meta1[1]!.rawEnd - meta1[1]!.rawStart).toBe(7) // `#8/11`
    expect(meta1[0]!.rawStart).toBe(quoteStart0 - 1)
    expect(meta1[0]!.rawEnd - meta1[0]!.rawStart).toBe(quoteLen0)
  })

  it('applying a quote-line edit via rawStart/rawEnd reproduces buildQuoteLinePattern', () => {
    const content = 'Before\n> [conditions] Prone\nAfter'
    const meta = scanControlPositions(content).find((m) => m.type === 'quote')!
    const newLine = buildQuoteLinePattern(meta.slug!, 'Stunned, Prone')
    const newContent = content.slice(0, meta.rawStart) + newLine + content.slice(meta.rawEnd)
    expect(newContent).toBe('Before\n> [conditions] Stunned, Prone\nAfter')
  })
})
