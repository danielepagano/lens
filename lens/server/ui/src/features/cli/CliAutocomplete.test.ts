import { describe, it, expect } from 'vitest'
import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { Stats } from '../../services/api'
import { operatorModule } from '../../commands/operators'
import {
  dashedGroupingCompletionSuffix,
  decomposeKbKeyTypingPrefix,
  filterCommandDefinitionsForViewingNode,
  getSuggestions,
  groupDenseSegmentedPrefixes,
  joinKbStemAndGroupedRest,
  kbKeyRemainderAfterStem,
  optionShouldSuggest,
  type DataSources,
} from './CliAutocomplete'

const SAMPLE_DEFS: CommandDefinition[] = [
  { trigger: 'always-op', group: 'rpg', cursorTargeting: 'always' },
  { trigger: 'never-op', group: 'rpg', cursorTargeting: 'never' },
  { trigger: 'override-op', group: 'narrative', cursorTargeting: 'can-override' },
]

describe('filterCommandDefinitionsForViewingNode', () => {
  it('returns all definitions when viewing at project cursor', () => {
    expect(filterCommandDefinitionsForViewingNode(SAMPLE_DEFS, true)).toEqual(SAMPLE_DEFS)
  })

  it('drops cursorTargeting always when not viewing at project cursor', () => {
    expect(filterCommandDefinitionsForViewingNode(SAMPLE_DEFS, false).map((d) => d.trigger)).toEqual([
      'never-op',
      'override-op',
    ])
  })
})

describe('decomposeKbKeyTypingPrefix / kbKeyRemainderAfterStem / joinKbStemAndGroupedRest', () => {
  it('uses stem after last dash when typing inside a segment (artificer-a)', () => {
    const keys = ['artificer-alchemist-x', 'artificer-armorer-y']
    expect(decomposeKbKeyTypingPrefix('artificer-a', keys)).toEqual({
      stem: 'artificer-',
      inSeg: 'a',
    })
    expect(kbKeyRemainderAfterStem('artificer-alchemist-x', 'artificer-')).toBe('alchemist-x')
  })

  it('uses full stem without trailing dash when every key branches with a dash', () => {
    const keys = ['artificer-alchemist', 'artificer-armorer']
    expect(decomposeKbKeyTypingPrefix('artificer', keys)).toEqual({ stem: 'artificer', inSeg: '' })
    expect(joinKbStemAndGroupedRest('artificer', 'alchemist')).toBe('artificer-alchemist')
    expect(joinKbStemAndGroupedRest('artificer-', 'alchemist')).toBe('artificer-alchemist')
  })

  it('first-segment fuzzy: empty stem, inSeg is whole prefix', () => {
    expect(decomposeKbKeyTypingPrefix('w', ['warlock-a', 'wizard-b'])).toEqual({
      stem: '',
      inSeg: 'w',
    })
  })
})

describe('dashedGroupingCompletionSuffix', () => {
  it('uses dash when the row is only a prefix of longer dashed keys', () => {
    const pool = ['artificer-alchemist-x', 'artificer-armorer-y']
    expect(dashedGroupingCompletionSuffix('artificer', pool)).toBe('-')
  })

  it('uses space when the row is an exact key', () => {
    const pool = ['acid-splash', 'artificer']
    expect(dashedGroupingCompletionSuffix('acid-splash', pool)).toBe(' ')
    expect(dashedGroupingCompletionSuffix('artificer', pool)).toBe(' ')
  })

  it('uses space for exact key even when longer dashed siblings exist', () => {
    const pool = ['foo', 'foo-bar']
    expect(dashedGroupingCompletionSuffix('foo', pool)).toBe(' ')
  })
})

describe('groupDenseSegmentedPrefixes', () => {
  it('collapses four siblings under one dash prefix and leaves sparse branches', () => {
    expect(
      groupDenseSegmentedPrefixes(
        ['one-1', 'one-2', 'one-3', 'one-4', 'two-1', 'two-2'],
        '-',
      ),
    ).toEqual(['one', 'two-1', 'two-2'])
  })

  it('coalesces nested prefix and keeps sibling branches', () => {
    expect(
      groupDenseSegmentedPrefixes(
        [
          'one-thing-1',
          'one-thing-2',
          'one-thing-3',
          'one-thing-4',
          'one-1',
          'two-1',
          'two-2',
        ],
        '-',
      ),
    ).toEqual(['one-1', 'one-thing', 'two-1', 'two-2'])
  })

  it('does not collapse when exactly two leaves share a parent', () => {
    expect(groupDenseSegmentedPrefixes(['one-1', 'one-2'], '-')).toEqual(['one-1', 'one-2'])
  })

  it('collapses when exactly three leaves share a parent', () => {
    expect(groupDenseSegmentedPrefixes(['one-1', 'one-2', 'one-3'], '-')).toEqual(['one'])
  })

  it('collapses after a single-child chain to a dense fan-out', () => {
    expect(
      groupDenseSegmentedPrefixes(['ab-c-1', 'ab-c-2', 'ab-c-3', 'ab-c-4'], '-'),
    ).toEqual(['ab-c'])
  })

  it('applies at multiple levels', () => {
    expect(
      groupDenseSegmentedPrefixes(
        ['aa-bb-1', 'aa-bb-2', 'aa-bb-3', 'aa-bb-4', 'aa-cc-1'],
        '-',
      ),
    ).toEqual(['aa-bb', 'aa-cc-1'])
  })

  it('uses slash delimiter for paths', () => {
    expect(
      groupDenseSegmentedPrefixes(
        [
          'media/foo/a-1',
          'media/foo/a-2',
          'media/foo/a-3',
          'media/foo/a-4',
          'media/bar/x',
        ],
        '/',
      ),
    ).toEqual(['media/bar/x', 'media/foo'])
  })

  it('collapses many files in the same dir to the parent path (getFileSuggestions skips grouping for this reason)', () => {
    expect(
      groupDenseSegmentedPrefixes(
        ['media/a.jpg', 'media/b.jpg', 'media/c.jpg', 'media/d.jpg'],
        '/',
      ),
    ).toEqual(['media'])
  })

  it('does not fan-out collapse when a completion ends at the parent and siblings exist', () => {
    expect(
      groupDenseSegmentedPrefixes(
        ['xx-yy', 'xx-yy-1', 'xx-yy-2', 'xx-yy-3', 'xx-yy-4'],
        '-',
      ),
    ).toEqual(['xx-yy', 'xx-yy-1', 'xx-yy-2', 'xx-yy-3', 'xx-yy-4'])
  })

  it('keeps both a prefix completion and extensions (single-child chain)', () => {
    expect(groupDenseSegmentedPrefixes(['a', 'a-b'], '-')).toEqual(['a', 'a-b'])
  })

  it('dedupes inputs before counting', () => {
    expect(
      groupDenseSegmentedPrefixes(
        ['one-1', 'one-1', 'one-2', 'one-3', 'one-4', 'two-1'],
        '-',
      ),
    ).toEqual(['one', 'two-1'])
  })

  it('returns empty for empty input', () => {
    expect(groupDenseSegmentedPrefixes([], '-')).toEqual([])
  })

  it('does not collapse top-level siblings to an empty prefix', () => {
    expect(groupDenseSegmentedPrefixes(['a', 'b', 'c', 'd'], '-')).toEqual(['a', 'b', 'c', 'd'])
  })

  it('sorts output lexicographically', () => {
    expect(groupDenseSegmentedPrefixes(['z-1', 'z-2', 'z-3', 'z-4', 'a-1'], '-')).toEqual([
      'a-1',
      'z',
    ])
  })

  it('collapses many deep keys that share a prefix (e.g. feature.* artificer-*)', () => {
    expect(
      groupDenseSegmentedPrefixes(
        [
          'aasimar-celestial-revelation',
          'aasimar-healing-hands',
          'artificer-alchemist-experimental-elixir',
          'artificer-armorer-arcane-armor',
          'artificer-armorer-armor-model',
          'artificer-artillerist-eldritch-cannon',
          'artificer-battle-smith-steel-defender',
          'artificer-cartographer-adventurers-atlas',
          'artificer-cartographer-mapping-magic',
          'artificer-cartographer-superior-atlas',
          'artificer-flash-of-genius',
          'artificer-soul-of-artifice',
          'artificer-spell-storing-item',
          'astral-elf-starlight-step',
        ],
        '-',
      ),
    ).toEqual([
      'aasimar-celestial-revelation',
      'aasimar-healing-hands',
      'artificer',
      'astral-elf-starlight-step',
    ])
  })

  it('KB key grouping re-attaches type prefix the same as getKbIdSuggestions', () => {
    const typeName = 'spell'
    const keys = groupDenseSegmentedPrefixes(
      ['ancient-black-a', 'ancient-black-b', 'ancient-black-c', 'ancient-black-d', 'acid-splash'],
      '-',
    )
    expect(keys.map((k) => `${typeName}.${k}`)).toEqual([
      'spell.acid-splash',
      'spell.ancient-black',
    ])
  })
})

describe('prompt @ node mentions', () => {
  function makeSources(): DataSources {
    return {
      kbTypes: ['spell'],
      kbKeyCache: new Map([['spell', ['fireball']]]),
      fetchKbKeys: () => {},
      nodeTree: [
        {
          key: 'story',
          address: 'story',
          children: [
            { key: 'chapter-1', address: 'story/chapter-1', children: [] },
          ],
        },
      ],
      fetchNodeTree: () => {},
      stats: null,
      mountDirCache: new Map(),
      fetchMountDir: () => {},
    }
  }

  function stateWithToken(token: string): ParseState {
    return {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: token,
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: false,
    }
  }

  it('routes @/ prefix to address suggestions', () => {
    const sugs = getSuggestions(stateWithToken('@/ch'), null, makeSources())
    expect(sugs.some((s) => s.kind === 'node' && s.value === '@/chapter-1')).toBe(true)
  })

  it('routes @<narrative>/ prefix to address suggestions', () => {
    const sugs = getSuggestions(stateWithToken('@story/ch'), null, makeSources())
    expect(sugs.some((s) => s.kind === 'node' && s.value === '@/chapter-1')).toBe(true)
  })

  it('keeps KB mention behavior unchanged', () => {
    const sugs = getSuggestions(stateWithToken('@spell.f'), null, makeSources())
    expect(sugs.some((s) => s.kind === 'kb-key' && s.value === '@spell.fireball')).toBe(true)
  })
})

function baseStats(over: Partial<Stats> = {}): Stats {
  return {
    active_narrative: 'story',
    narratives: ['story'],
    cursor: 'story/play-x',
    has_pending: false,
    has_staged: false,
    pending_owner: null,
    dataset_name: null,
    current_datasets: ['rpg'],
    kb_types: [],
    kb_count: 0,
    effective_pins_at_cursor: ['pc.hero'],
    available_llms: ['fast'],
    has_mount: false,
    active_session_operator: null,
    transaction: null,
    ...over,
  }
}

describe('optionShouldSuggest / availability', () => {
  const playDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'play')!
  const chatDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'chat')!

  it('play: --pass is allowed when active_session_operator is null (not gated on play)', () => {
    const passOpt = playDef.options!.find((o) => o.name === 'pass')!
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(passOpt, st, playDef, baseStats())).toBe(true)
  })

  it('chat: --memory hidden when not in session and --with not set', () => {
    const memOpt = chatDef.options!.find((o) => o.name === 'memory')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(memOpt, st, chatDef, baseStats())).toBe(false)
  })

  it('chat: --memory shown when active_session_operator is chat', () => {
    const memOpt = chatDef.options!.find((o) => o.name === 'memory')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(memOpt, st, chatDef, baseStats({ active_session_operator: 'chat' }))).toBe(
      true,
    )
  })

  it('chat: --memory shown when --with chip is set', () => {
    const memOpt = chatDef.options!.find((o) => o.name === 'memory')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: { with: 'pc.amy' },
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(memOpt, st, chatDef, baseStats())).toBe(true)
  })

  it('chat: --memory hidden when --end is set', () => {
    const memOpt = chatDef.options!.find((o) => o.name === 'memory')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: { end: true },
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(memOpt, st, chatDef, baseStats({ active_session_operator: 'chat' }))).toBe(
      false,
    )
  })

  it('play: --end hidden unless active_session_operator is play', () => {
    const endOpt = playDef.options!.find((o) => o.name === 'end')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(endOpt, st, playDef, baseStats())).toBe(false)
    expect(optionShouldSuggest(endOpt, st, playDef, baseStats({ active_session_operator: 'play' }))).toBe(
      true,
    )
  })

  it('play: mutual exclusion hides pass when retry is already set', () => {
    const passOpt = playDef.options!.find((o) => o.name === 'pass')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: { retry: true, pass: true },
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(passOpt, st, playDef, baseStats({ active_session_operator: 'play' }))).toBe(
      false,
    )
  })

  it('getSuggestions: prompt slot still hides --slug when active_session_operator is play', () => {
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({ active_session_operator: 'play' }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const sugs = getSuggestions(st, playDef, sources)
    const flags = sugs.filter((s) => s.kind === 'flag').map((s) => s.value)
    expect(flags).not.toContain('--slug')
    expect(flags).toContain('--pass')
  })

  it('getSuggestions: prompt slot still hides --end when not in play session', () => {
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats(),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const sugs = getSuggestions(st, playDef, sources)
    const flags = sugs.filter((s) => s.kind === 'flag').map((s) => s.value)
    expect(flags).not.toContain('--end')
    expect(flags).toContain('--pass')
  })

  it('getSuggestions: --end chip for chat when inside chat session', () => {
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({ active_session_operator: 'chat' }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
    }
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const sugs = getSuggestions(st, chatDef, sources)
    expect(sugs.some((s) => s.kind === 'flag' && s.value === '--end')).toBe(true)
  })

  it('getSuggestions: typing -- partial respects availability for --end', () => {
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({ active_session_operator: null }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
    }
    const st: ParseState = {
      phase: 'idle',
      currentToken: '--en',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const sugs = getSuggestions(st, chatDef, sources)
    expect(sugs.some((s) => s.value === '--end')).toBe(false)
  })
})
