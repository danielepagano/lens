import { describe, it, expect } from 'vitest'
import {
  kbOpBlockAtLine,
  kbOpTargetIds,
  parseKbOpBlocks,
  unquoteYamlScalar,
} from './kbOpBlocks'

/**
 * The fixtures here are what `render_kb_op` (core/kb_pending.py) actually
 * writes, not a convenient approximation. The body gutter and the one-line
 * JSON for patches exist because a KB body has to materialize verbatim and a
 * line ending in `]: #` would close the block early — so a parser that only
 * handles the tidy cases is a parser that breaks on the content this channel
 * exists for.
 */

describe('parseKbOpBlocks', () => {
  it('reads the scalar fields and the line span', () => {
    const text = ['Prose.', '', '[kb-op', '  op: remove', '  id: loc.vault', ']: #', ''].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op).toMatchObject({ op: 'remove', id: 'loc.vault', lineStart: 3, lineEnd: 6 })
    expect(op!.raw).toContain('op: remove')
  })

  it('decodes a gutter-encoded body back to the original text', () => {
    // `| ` prefix per line; a bare `|` was an empty source line.
    const text = [
      '[kb-op',
      '  op: add',
      '  id: npc.warden',
      '  body: |',
      '    | # The Warden',
      '    |',
      '    |     indented, and kept so',
      ']: #',
    ].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.body).toBe('# The Warden\n\n    indented, and kept so')
  })

  it('undoes the defuse backslash on a line that would close the block', () => {
    const text = [
      '[kb-op',
      '  op: add',
      '  id: lore.links',
      '  body: |',
      '    | [footnote]: #\\',
      '    | after',
      ']: #',
    ].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.body).toBe('[footnote]: #\nafter')
  })

  it('parses patches from the one-line JSON they are written as', () => {
    const patches = JSON.stringify([
      { start: { target: '  - **Legs**: `2.0`.', before: ['## Tracking'] }, content: '  - **Legs**: `3.0`.' },
    ])
    const text = ['[kb-op', '  op: patch', '  id: front.loose-blade', `  patches: ${patches}`, ']: #'].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.patches).toHaveLength(1)
    expect(op!.patches[0]!.start!.target).toBe('  - **Legs**: `2.0`.')
    expect(op!.patches[0]!.start!.before).toEqual(['## Tracking'])
    expect(op!.patches[0]!.content).toBe('  - **Legs**: `3.0`.')
  })

  it('survives patches that are not valid JSON rather than losing the op', () => {
    const text = ['[kb-op', '  op: patch', '  id: front.x', '  patches: [{broken', ']: #'].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.op).toBe('patch')
    expect(op!.patches).toEqual([])
  })

  it('reads the tag sequences', () => {
    const text = [
      '[kb-op',
      '  op: tag',
      '  id: loc.vault',
      '  tags:',
      '    - sunken',
      '    - "2024"',
      '  remove-tags:',
      '    - draft',
      ']: #',
    ].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.tags).toEqual(['sunken', '2024'])
    expect(op!.removeTags).toEqual(['draft'])
  })

  it('reads an applied record, quoted timestamp and all', () => {
    const text = [
      '[kb-op',
      '  op: applied',
      '  at: "2026-09-17T10:00:00Z"',
      '  session: design-one',
      '  ids:',
      '    - front.loose-blade',
      '    - npc.warden',
      '  removed:',
      '    - loc.old-ford',
      ']: #',
    ].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.at).toBe('2026-09-17T10:00:00Z')
    expect(op!.session).toBe('design-one')
    expect(op!.ids).toEqual(['front.loose-blade', 'npc.warden'])
    expect(op!.removed).toEqual(['loc.old-ford'])
    expect(op!.id).toBe('')
  })

  it('keeps consecutive blocks separate and in order', () => {
    const text = [
      '[kb-op',
      '  op: add',
      '  id: npc.warden',
      '  body: |',
      '    | A warden.',
      ']: #',
      '',
      '[kb-op',
      '  op: tag',
      '  id: npc.warden',
      '  tags:',
      '    - ford',
      ']: #',
    ].join('\n')
    const ops = parseKbOpBlocks(text)
    expect(ops.map((o) => o.op)).toEqual(['add', 'tag'])
    expect(ops[1]!.lineStart).toBe(8)
  })

  it('runs an unterminated block to end of text rather than leaking a body', () => {
    const text = ['[kb-op', '  op: add', '  id: npc.warden', '  body: |', '    | A warden.'].join('\n')
    const [op] = parseKbOpBlocks(text)
    expect(op!.body).toBe('A warden.')
    expect(op!.lineEnd).toBe(5)
  })

  it('finds nothing in ordinary prose', () => {
    expect(parseKbOpBlocks('Just prose.\n\n[Amy] said something.\n')).toEqual([])
  })
})

describe('kbOpBlockAtLine', () => {
  const text = ['Prose.', '[kb-op', '  op: remove', '  id: loc.vault', ']: #'].join('\n')

  it('finds the block a marker points at', () => {
    expect(kbOpBlockAtLine(text, 2)!.id).toBe('loc.vault')
  })

  it('returns null for a line that is not an opener', () => {
    expect(kbOpBlockAtLine(text, 3)).toBeNull()
  })
})

describe('kbOpTargetIds', () => {
  it('is the single id for a proposal', () => {
    const [op] = parseKbOpBlocks('[kb-op\n  op: remove\n  id: loc.vault\n]: #')
    expect(kbOpTargetIds(op!)).toEqual(['loc.vault'])
  })

  it('is everything a close touched for an applied record', () => {
    const [op] = parseKbOpBlocks(
      ['[kb-op', '  op: applied', '  ids:', '    - npc.warden', '  removed:', '    - loc.old', ']: #'].join('\n'),
    )
    expect(kbOpTargetIds(op!)).toEqual(['npc.warden', 'loc.old'])
  })
})

describe('unquoteYamlScalar', () => {
  it('leaves a plain scalar alone', () => {
    expect(unquoteYamlScalar('  front.loose-blade  ')).toBe('front.loose-blade')
  })

  it('unwraps the quoting `_scalar` adds to values YAML would retype', () => {
    expect(unquoteYamlScalar('"2026-09-17T10:00:00Z"')).toBe('2026-09-17T10:00:00Z')
    expect(unquoteYamlScalar("'12'")).toBe('12')
  })
})
