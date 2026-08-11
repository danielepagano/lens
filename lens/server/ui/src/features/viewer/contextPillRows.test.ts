import { describe, it, expect } from 'vitest'
import {
  contextSummaryParts,
  cursorKbRows,
  pillKey,
  pillLabel,
  pillTitle,
} from './contextPillRows'

const noDecorations = { isState: () => false, rememberTags: () => [] }

describe('cursorKbRows', () => {
  it('lists pins first, then includes, then mentions', () => {
    expect(cursorKbRows(['place.a'], ['rules.grappling'], ['spell.aid'])).toEqual([
      { id: 'place.a', unpin: false },
      { id: 'rules.grappling', unpin: false, scope: 'include' },
      { id: 'spell.aid', unpin: false, scope: 'mention' },
    ])
  })

  it('keeps an id that is both pinned and mentioned as two distinct rows', () => {
    const rows = cursorKbRows(['spell.aid'], [], ['spell.aid'])
    expect(rows).toHaveLength(2)
    expect(pillKey(rows[0], 0)).not.toEqual(pillKey(rows[1], 1))
  })
})

describe('pillLabel', () => {
  it('prefixes each scope distinctly', () => {
    expect(pillLabel({ id: 'place.a', unpin: false })).toBe('place.a')
    expect(pillLabel({ id: 'place.a', unpin: true })).toBe('-place.a')
    expect(pillLabel({ id: 'r.g', unpin: false, scope: 'include' })).toBe('+r.g')
    expect(pillLabel({ id: 's.aid', unpin: false, scope: 'mention' })).toBe('@s.aid')
  })
})

describe('pillTitle', () => {
  it('explains the lifetime of a scoped pill', () => {
    expect(pillTitle({ id: 's.aid', unpin: false, scope: 'mention' }, noDecorations)).toContain(
      'one more AI turn',
    )
    expect(pillTitle({ id: 'r.g', unpin: false, scope: 'include' }, noDecorations)).toContain(
      'rest of this node',
    )
  })

  it('does not call a scoped pill live state', () => {
    // A state object is diverted to the tail instead of inlined, so the two
    // decorations are mutually exclusive and the tooltip must not claim both.
    const title = pillTitle({ id: 'tracker.combat', unpin: false, scope: 'mention' }, {
      isState: () => true,
      rememberTags: () => [],
    })
    expect(title).toContain('one more AI turn')
    expect(title).not.toContain('Live state')
  })

  it('still labels an ordinary state pin', () => {
    const title = pillTitle({ id: 'tracker.combat', unpin: false }, {
      isState: () => true,
      rememberTags: () => [],
    })
    expect(title).toContain('Live state')
  })

  it('appends remember tags and returns undefined when there is nothing to say', () => {
    expect(
      pillTitle({ id: 'lore.a', unpin: false }, {
        isState: () => false,
        rememberTags: () => ['remember.notes'],
      }),
    ).toBe('remember.notes')
    expect(pillTitle({ id: 'lore.a', unpin: false }, noDecorations)).toBeUndefined()
  })
})

describe('contextSummaryParts', () => {
  it('counts includes and mentions separately from pins', () => {
    expect(
      contextSummaryParts({ pins: 2, vars: 0, params: 0, includes: 1, mentions: 3 }),
    ).toEqual(['2 pins', '1 include', '3 mentions'])
  })

  it('omits empty groups', () => {
    expect(contextSummaryParts({ pins: 0, vars: 1, params: 0 })).toEqual(['1 var'])
  })
})
