import { describe, it, expect } from 'vitest'
import type { PendingKb } from '../../services/api'
import {
  contextSummaryParts,
  cursorKbRows,
  pendingKbRows,
  pendingPillLabel,
  pillKey,
  pillLabel,
  pillTitle,
  splitPillRows,
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

  it('notes that a state-tagged mention diverts instead of inlining', () => {
    // Tagged `state`, the object never inlines at the annotation site — it
    // diverts to Live State same as a state pin (mentions.py) — so the
    // tooltip says both: why it is in scope, and where it actually renders.
    const title = pillTitle({ id: 'tracker.combat', unpin: false, scope: 'mention' }, {
      isState: () => true,
      rememberTags: () => [],
    })
    expect(title).toContain('one more AI turn')
    expect(title).toContain('diverts to Live State')
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

describe('splitPillRows', () => {
  const rows = cursorKbRows(['place.a', 'tracker.combat'], ['rules.grappling'], ['spell.aid'])
  const isState = (id: string) => id === 'tracker.combat'

  it('keeps ordinary pins plain and moves scoped rows to notable', () => {
    const { plain, notable } = splitPillRows(rows, isState)
    expect(plain).toEqual([{ id: 'place.a', unpin: false }])
    expect(notable).toEqual([
      { id: 'tracker.combat', unpin: false },
      { id: 'rules.grappling', unpin: false, scope: 'include' },
      { id: 'spell.aid', unpin: false, scope: 'mention' },
    ])
  })

  it('never treats an unpin as notable, even if the id is tagged state', () => {
    const { plain, notable } = splitPillRows(
      [{ id: 'tracker.combat', unpin: true }],
      isState,
    )
    expect(plain).toEqual([{ id: 'tracker.combat', unpin: true }])
    expect(notable).toEqual([])
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

  it('appends the pending proposal count last, singular and plural', () => {
    expect(contextSummaryParts({ pins: 0, vars: 0, params: 0, pending: 1 })).toEqual([
      '1 proposal',
    ])
    expect(
      contextSummaryParts({ pins: 1, vars: 0, params: 0, mentions: 1, pending: 2 }),
    ).toEqual(['1 pin', '1 mention', '2 proposals'])
  })

  it('omits the proposal part at zero', () => {
    expect(contextSummaryParts({ pins: 0, vars: 0, params: 0, pending: 0 })).toEqual([])
  })
})

describe('pendingKbRows', () => {
  function pending(overrides: Partial<PendingKb> = {}): PendingKb {
    return {
      node: 'chapter-1',
      ops: [],
      objects: [],
      errors: [],
      ...overrides,
    }
  }

  it('returns nothing when there is no pending layer', () => {
    expect(pendingKbRows(null)).toEqual([])
  })

  it('emits one row per changed object, in order, with no errors', () => {
    const rows = pendingKbRows(
      pending({
        objects: [
          { id: 'npc.amy', change: 'created', base: null, proposed: 'text', base_source: null },
          {
            id: 'front.siege',
            change: 'updated',
            base: 'old',
            proposed: 'new',
            base_source: 'dataset:rpg',
          },
          { id: 'loc.dungeon', change: 'removed', base: 'old', proposed: null, base_source: null },
        ],
      }),
    )
    expect(rows.map((r) => r.id)).toEqual(['npc.amy', 'front.siege', 'loc.dungeon'])
    expect(rows.map((r) => r.error)).toEqual([false, false, false])
    expect(rows.map(pendingPillLabel)).toEqual([
      '+ npc.amy',
      '⟲ front.siege',
      '− loc.dungeon',
    ])
  })

  it('flags a row only when one of ITS OWN ops errored, not another id’s', () => {
    const rows = pendingKbRows(
      pending({
        ops: [
          {
            index: 0,
            op: 'patch',
            id: 'npc.amy',
            line_start: 1,
            line_end: 1,
            summary: 'patch',
            status: 'error',
            error: 'anchor not found',
          },
          {
            index: 1,
            op: 'tag',
            id: 'front.siege',
            line_start: 2,
            line_end: 2,
            summary: 'tag',
            status: 'ok',
            error: '',
          },
        ],
        objects: [
          { id: 'npc.amy', change: 'updated', base: 'old', proposed: 'new', base_source: null },
          {
            id: 'front.siege',
            change: 'updated',
            base: 'old',
            proposed: 'new',
            base_source: null,
          },
        ],
      }),
    )
    expect(rows.find((r) => r.id === 'npc.amy')?.error).toBe(true)
    expect(rows.find((r) => r.id === 'front.siege')?.error).toBe(false)
  })

  it('builds the title from the change verb, base_source, and each op error', () => {
    const rows = pendingKbRows(
      pending({
        ops: [
          {
            index: 0,
            op: 'patch',
            id: 'front.siege',
            line_start: 1,
            line_end: 1,
            summary: 'patch',
            status: 'error',
            error: 'anchor not found',
          },
        ],
        objects: [
          {
            id: 'front.siege',
            change: 'updated',
            base: 'old',
            proposed: 'new',
            base_source: 'dataset:rpg',
          },
        ],
      }),
    )
    const title = rows[0].title
    expect(title).toContain('Changed')
    expect(title).toContain('over dataset:rpg')
    expect(title).toContain('anchor not found')
  })
})
