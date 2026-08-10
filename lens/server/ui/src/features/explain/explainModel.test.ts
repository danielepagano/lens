import { describe, expect, it } from 'vitest'
import type { ExplainBlock, ExplainComponent, ExplainReport } from '../../services/api'
import {
  MIN_SEGMENT_WIDTH,
  blockColorVar,
  blockSegments,
  blockShortLabel,
  componentRows,
  formatShare,
  formatSize,
  isDerived,
  prefixShare,
  reportHeadline,
  sizeOf,
} from './explainModel'

function component(over: Partial<ExplainComponent> = {}): ExplainComponent {
  return {
    id: 'kb:person.amy',
    kind: 'knowledge',
    block: 'relevant_knowledge',
    order: 0,
    bytes: 68,
    tokens: 17,
    percent: 2.25,
    provenance: 'kb_pin on story',
    provenance_kind: 'node_pin',
    cache: 'prefix',
    detail: {},
    ...over,
  }
}

function block(over: Partial<ExplainBlock> = {}): ExplainBlock {
  const components = over.components ?? [component()]
  return {
    id: 'relevant_knowledge',
    label: 'RELEVANT KNOWLEDGE',
    role: 'user',
    order: 1,
    bytes: components.reduce((s, c) => s + c.bytes, 0),
    tokens: components.reduce((s, c) => s + c.tokens, 0),
    percent: 0,
    framing_bytes: 0,
    framing_tokens: 0,
    cache: 'prefix',
    ...over,
    components,
  }
}

function report(blocks: ExplainBlock[], over: Partial<ExplainReport> = {}): ExplainReport {
  const bytes = blocks.reduce((s, b) => s + b.bytes, 0)
  const tokens = blocks.reduce((s, b) => s + b.tokens, 0)
  return {
    address: 'story',
    node: 'story',
    operator: 'write',
    line: null,
    blocks,
    excluded: [],
    totals: {
      bytes,
      tokens,
      accounted_bytes: bytes,
      other_bytes: 0,
      other_tokens: 0,
      messages: 2,
      message_bytes: [bytes],
    },
    chars_per_token: 4,
    active_modalities: [],
    pinned_ids: [],
    warnings: [],
    ...over,
  }
}

describe('sizeOf / formatSize', () => {
  it('swaps units as a pure field read', () => {
    const c = component({ bytes: 400, tokens: 100 })
    expect(sizeOf(c, 'bytes')).toBe(400)
    expect(sizeOf(c, 'tokens')).toBe(100)
  })

  it('formats tokens as counts and bytes with a magnitude suffix', () => {
    expect(formatSize(1234, 'tokens')).toBe('1,234 tok')
    expect(formatSize(512, 'bytes')).toBe('512 B')
    expect(formatSize(2048, 'bytes')).toBe('2.0 KB')
    expect(formatSize(3 * 1024 * 1024, 'bytes')).toBe('3.0 MB')
  })
})

describe('formatShare', () => {
  it('never rounds a real contribution down to zero', () => {
    expect(formatShare(0)).toBe('0%')
    expect(formatShare(0.04)).toBe('<0.1%')
    expect(formatShare(12.34)).toBe('12.3%')
  })
})

describe('blockSegments', () => {
  it('recomputes shares in the active unit rather than reusing byte percents', () => {
    // Byte and token weights deliberately disagree: block A is byte-heavy,
    // block B token-heavy, so a segment built off the server's byte-based
    // `percent` would be wrong in token mode.
    const a = block({ id: 'system', order: 0, bytes: 900, tokens: 100, components: [] })
    const b = block({ id: 'task', order: 1, bytes: 100, tokens: 300, components: [] })
    const r = report([a, b])

    const byBytes = blockSegments(r, 'bytes')
    expect(byBytes.map((s) => Math.round(s.share))).toEqual([90, 10])

    const byTokens = blockSegments(r, 'tokens')
    expect(byTokens.map((s) => Math.round(s.share))).toEqual([25, 75])
  })

  it('orders by prompt order and drops empty blocks', () => {
    const r = report([
      block({ id: 'task', order: 6, bytes: 40, tokens: 10, components: [] }),
      block({ id: 'extra', order: 5, bytes: 0, tokens: 0, components: [] }),
      block({ id: 'system', order: 0, bytes: 60, tokens: 15, components: [] }),
    ])
    expect(blockSegments(r, 'tokens').map((s) => s.id)).toEqual(['system', 'task'])
  })

  it('floors slivers to a tappable width and keeps the widths summing to 100', () => {
    const r = report([
      block({ id: 'system', order: 0, bytes: 9970, tokens: 9970, components: [] }),
      block({ id: 'task', order: 6, bytes: 30, tokens: 30, components: [] }),
    ])
    const segments = blockSegments(r, 'tokens')

    expect(segments[1].share).toBeCloseTo(0.3, 5)
    expect(segments[1].width).toBe(MIN_SEGMENT_WIDTH)
    expect(segments.reduce((s, seg) => s + seg.width, 0)).toBeCloseTo(100, 5)
  })

  it('handles a conversation block standing in for current_passage', () => {
    // Session operators parse the passage into turns: there is no
    // `current_passage` block at all, so colours must key off the block id.
    const r = report([
      block({ id: 'system', order: 0, bytes: 100, tokens: 25, components: [] }),
      block({
        id: 'conversation',
        label: 'CONVERSATION TURNS',
        order: 4,
        cache: 'volatile',
        bytes: 300,
        tokens: 75,
        components: [],
      }),
    ])
    const segments = blockSegments(r, 'tokens')
    expect(segments[1].shortLabel).toBe('Turns')
    expect(segments[1].colorVar).toBe(blockColorVar('current_passage'))
  })

  it('returns nothing for an empty report', () => {
    expect(blockSegments(report([]), 'tokens')).toEqual([])
  })
})

describe('componentRows', () => {
  it('reports share of total and share of block separately', () => {
    const big = component({ id: 'kb:pc.alice', bytes: 300, tokens: 75, order: 0 })
    const small = component({ id: 'kb:loc.keep', bytes: 100, tokens: 25, order: 1 })
    const knowledge = block({ components: [big, small] })
    const other = block({ id: 'system', order: 0, bytes: 400, tokens: 100, components: [] })
    const r = report([other, knowledge])

    const rows = componentRows(knowledge, r, 'tokens')
    expect(rows.map((row) => row.id)).toEqual(['kb:pc.alice', 'kb:loc.keep'])
    expect(rows[0].shareOfBlock).toBeCloseTo(75, 5)
    expect(rows[0].shareOfTotal).toBeCloseTo(37.5, 5)
  })

  it('surfaces the ancestor a pin lives on and splits tags', () => {
    const rows = componentRows(
      block({
        components: [
          component({
            detail: { kb_id: 'person.amy', pin_node: 'story', tags: 'protagonist, lead' },
          }),
        ],
      }),
      report([]),
      'tokens'
    )
    expect(rows[0].kbId).toBe('person.amy')
    expect(rows[0].pinNode).toBe('story')
    expect(rows[0].tags).toEqual(['protagonist', 'lead'])
  })

  it('marks rows that follow from another pin as derived', () => {
    const rows = componentRows(
      block({
        components: [
          component({ id: 'kb:pc.alice', provenance_kind: 'node_pin', order: 0 }),
          component({ id: 'kb:spell.aid', provenance_kind: 'expansion', order: 1 }),
          component({ id: 'rules-companion:rules.encounter', provenance_kind: 'rules_companion', order: 2 }),
          component({ id: 'modality-addenda', provenance_kind: 'modality', order: 3 }),
          component({ id: 'mention-kb:spell.bless', provenance_kind: 'mention', order: 4 }),
        ],
      }),
      report([]),
      'tokens'
    )
    expect(rows.map((row) => row.derived)).toEqual([false, true, true, true, false])
  })
})

describe('isDerived', () => {
  it('keys off provenance_kind, not the component id', () => {
    expect(isDerived(component({ id: 'kb:x', provenance_kind: 'expansion' }))).toBe(true)
    expect(isDerived(component({ id: 'rules-companion:x', provenance_kind: 'node_pin' }))).toBe(false)
  })
})

describe('blockColorVar', () => {
  it('gives system and task neutral chrome, not a series hue', () => {
    expect(blockColorVar('system')).toBe('--explain-chrome-1')
    expect(blockColorVar('task')).toBe('--explain-chrome-2')
  })

  it('is stable per block id and falls back for unknown blocks', () => {
    expect(blockColorVar('relevant_knowledge')).toBe('--explain-series-1')
    expect(blockColorVar('something_a_dataset_added')).toBe('--explain-chrome-unknown')
  })

  it('gives live state a validated series hue, not the unknown fallback', () => {
    // The same token the `state` pin pill draws from — they must not drift.
    expect(blockColorVar('live_state')).toBe('--explain-series-5')
  })
})

describe('blockShortLabel', () => {
  it('falls back to the payload label for unknown blocks', () => {
    expect(blockShortLabel(block({ id: 'weird', label: 'WEIRD BLOCK' }))).toBe('WEIRD BLOCK')
  })

  it('shortens live state so it reads beside the other legend entries', () => {
    expect(blockShortLabel(block({ id: 'live_state', label: 'LIVE STATE' }))).toBe('Live state')
  })
})

describe('prefixShare', () => {
  it('sums the cacheable blocks in the active unit', () => {
    const r = report([
      block({ id: 'system', order: 0, cache: 'prefix', bytes: 800, tokens: 200, components: [] }),
      block({ id: 'task', order: 6, cache: 'volatile', bytes: 200, tokens: 50, components: [] }),
    ])
    expect(prefixShare(r, 'tokens')).toBeCloseTo(80, 5)
    expect(prefixShare(r, 'bytes')).toBeCloseTo(80, 5)
  })
})

describe('reportHeadline', () => {
  it('mentions the line only when the report is pinned to one', () => {
    expect(reportHeadline(report([]))).toBe('story · write')
    expect(reportHeadline(report([], { line: 42, operator: 'play' }))).toBe('story · play · as of line 42')
  })
})
