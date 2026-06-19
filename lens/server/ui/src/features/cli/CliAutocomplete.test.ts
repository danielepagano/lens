import { describe, it, expect } from 'vitest'
import type { CommandDefinition } from '../../commands/common'
import { parseCliInput, type ParseState } from '../../commands/parser'
import type { ImageBackendStats, Stats } from '../../services/api'
import { mediaModule } from '../../commands/media'
import { narrativeModule } from '../../commands/narrative'
import { operatorModule } from '../../commands/operators'
import {
  canonicalParamKeyForCliFlag,
  pinnedParamKeyVariantsForCliFlag,
  dashedGroupingCompletionSuffix,
  decomposeKbKeyTypingPrefix,
  filterCommandDefinitionsForViewingNode,
  getSuggestions,
  groupDenseSegmentedPrefixes,
  joinKbStemAndGroupedRest,
  kbKeyRemainderAfterStem,
  operatorSlugFromCliTrigger,
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
  function makeSources(over: Partial<DataSources> = {}): DataSources {
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
      viewingAtProjectCursor: true,
      ...over,
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

describe('prompt @var mentions', () => {
  function sourcesWithVars(over: Partial<DataSources> = {}): DataSources {
    return {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({ effective_vars_at_cursor: { mood: 'dark', tone: 'dry' } }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
      ...over,
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

  it('offers @var chip when at cursor and effective vars exist', () => {
    const sugs = getSuggestions(stateWithToken('@'), null, sourcesWithVars())
    const v = sugs.find((s) => s.kind === 'var-prefix')
    expect(v?.label).toBe('@var')
    expect(v?.value).toBe('@var:')
  })

  it('hides @var chip when not viewing the narrative cursor', () => {
    const sugs = getSuggestions(stateWithToken('@'), null, sourcesWithVars({ viewingAtProjectCursor: false }))
    expect(sugs.some((s) => s.kind === 'var-prefix')).toBe(false)
  })

  it('does not offer @var when no effective vars', () => {
    const sugs = getSuggestions(stateWithToken('@'), null, sourcesWithVars({ stats: baseStats({ effective_vars_at_cursor: {} }) }))
    expect(sugs.some((s) => s.kind === 'var-prefix')).toBe(false)
  })

  it('lists var keys after @var: with colon form', () => {
    const sugs = getSuggestions(stateWithToken('@var:'), null, sourcesWithVars())
    expect(sugs.map((s) => s.value).sort()).toEqual(['@var:mood', '@var:tone'].sort())
  })

  it('filters var keys by typed prefix', () => {
    const sugs = getSuggestions(stateWithToken('@var:mo'), null, sourcesWithVars())
    expect(sugs).toEqual([
      expect.objectContaining({ kind: 'var-key', value: '@var:mood', label: 'mood' }),
    ])
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
    effective_vars_at_cursor: {},
    effective_params_at_cursor: {},
    remember_pins_at_cursor: {},
    available_llms: ['fast'],
    image_backends: [],
    has_mount: false,
    cloud_mount: false,
    reference_images_supported: false,
    tts_available: false,
    active_session_operator: null,
    transaction: null,
    dataset_configs: {},
    ...over,
  }
}

function cliSources(over: Partial<DataSources> = {}): DataSources {
  return {
    kbTypes: [],
    kbKeyCache: new Map(),
    fetchKbKeys: () => {},
    nodeTree: null,
    fetchNodeTree: () => {},
    stats: baseStats(),
    mountDirCache: new Map(),
    fetchMountDir: () => {},
    viewingAtProjectCursor: true,
    ...over,
  }
}

describe('pinned param styling helpers', () => {
  it('maps CLI triggers to params slug keys', () => {
    expect(operatorSlugFromCliTrigger('write')).toBe('write')
    expect(operatorSlugFromCliTrigger('structure-collate')).toBe('collate')
    expect(operatorSlugFromCliTrigger('structure-section')).toBe('section')
  })

  it('maps flags to canonical pinned keys', () => {
    expect(canonicalParamKeyForCliFlag('write', 'llm')).toBe('llm_id')
    expect(canonicalParamKeyForCliFlag('chat', 'as')).toBe('as_kb_id')
    expect(canonicalParamKeyForCliFlag('play', 'as')).toBe('as_pc')
    expect(canonicalParamKeyForCliFlag('advance', 'days')).toBe('increment')
  })

  it('llm flag matches stats keys llm or llm_id', () => {
    expect(pinnedParamKeyVariantsForCliFlag('write', 'llm')).toEqual(['llm_id', 'llm'])
  })
})

describe('pin-param slug suggestions', () => {
  const pinParamDef = narrativeModule.commands(baseStats()).find((d) => d.trigger === 'pin-param')!

  it('uses slug payloads for scope and key', () => {
    const scope = pinParamDef.positional!.find((p) => p.name === 'scope')
    const key = pinParamDef.positional!.find((p) => p.name === 'key')
    expect(scope?.valueType).toBe('slug')
    expect(key?.valueType).toBe('slug')
  })

  it('suggests global first, then operator scopes', () => {
    const state = parseCliInput('/pin-param set ', pinParamDef)
    const values = getSuggestions(state, pinParamDef, cliSources()).map((s) => s.value)
    expect(values).toEqual([
      'global',
      'write',
      'edit',
      'section',
      'collate',
      'compress',
      'design',
      'chat',
      'play',
      'advance',
    ])
  })

  it('filters scope suggestions by prefix', () => {
    const state = parseCliInput('/pin-param set co', pinParamDef)
    const values = getSuggestions(state, pinParamDef, cliSources()).map((s) => s.value)
    expect(values).toEqual(['collate', 'compress'])
  })

  it('suggests canonical param keys including llm_id and excluding llm', () => {
    const state = parseCliInput('/pin-param set global ', pinParamDef)
    const values = getSuggestions(state, pinParamDef, cliSources()).map((s) => s.value)
    expect(values).toContain('llm_id')
    expect(values).not.toContain('llm')
    expect(values).toContain('as_kb_id')
    expect(values).toContain('with_kb_id')
  })

  it('filters param key suggestions by prefix', () => {
    const state = parseCliInput('/pin-param set global llm', pinParamDef)
    const values = getSuggestions(state, pinParamDef, cliSources()).map((s) => s.value)
    expect(values).toEqual(['llm_id'])
  })
})

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
      viewingAtProjectCursor: true,
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
      viewingAtProjectCursor: true,
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
      viewingAtProjectCursor: true,
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

  it('global pinned params highlight matching flags (reasoning is always listed)', () => {
    const writeDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'write')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        effective_params_at_cursor: { 'global:reasoning': 'medium' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const sugs = getSuggestions(st, writeDef, sources)
    const reasoning = sugs.find((s) => s.kind === 'flag' && s.value === '--reasoning')
    expect(reasoning?.effectiveParamPin).toBe(true)
    const llm = sugs.find((s) => s.kind === 'flag' && s.value === '--llm')
    expect(llm?.effectiveParamPin).toBeUndefined()
  })

  it('stats key global:llm (no _id) highlights --llm', () => {
    const writeDef = operatorModule.commands(
      baseStats({ available_llms: ['a', 'b'] }),
    ).find((d) => d.trigger === 'write')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        available_llms: ['a', 'b'],
        effective_params_at_cursor: { 'global:llm': 'deepseek' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const llm = getSuggestions(st, writeDef, sources).find((s) => s.value === '--llm')
    expect(llm?.effectiveParamPin).toBe(true)
  })

  it('global llm_id pin: single LLM still shows --llm (pin styling)', () => {
    const writeDef = operatorModule.commands(
      baseStats({
        available_llms: ['only'],
        effective_params_at_cursor: { 'global:llm_id': 'only' },
      }),
    ).find((d) => d.trigger === 'write')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        available_llms: ['only'],
        effective_params_at_cursor: { 'global:llm_id': 'only' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const llm = getSuggestions(st, writeDef, sources).find((s) => s.value === '--llm')
    expect(llm?.effectiveParamPin).toBe(true)
  })

  it('global reasoning pin: typing -- partial still carries effectiveParamPin', () => {
    const writeDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'write')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        effective_params_at_cursor: { 'global:reasoning': 'medium' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '-reason',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const row = getSuggestions(st, writeDef, sources).find((s) => s.value === '--reasoning')
    expect(row?.effectiveParamPin).toBe(true)
  })

  it('slug-scoped pins only highlight on that operator', () => {
    const writeDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'write')!
    const chatDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'chat')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        effective_params_at_cursor: { 'chat:reasoning': 'high' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: true,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(
      getSuggestions(st, writeDef, sources).find((s) => s.value === '--reasoning')?.effectiveParamPin,
    ).toBeUndefined()
    expect(
      getSuggestions(st, chatDef, sources).find((s) => s.value === '--reasoning')?.effectiveParamPin,
    ).toBe(true)
  })

  it('does not mark pinned flags when viewing off the narrative cursor', () => {
    const writeDef = operatorModule.commands(baseStats()).find((d) => d.trigger === 'write')!
    const sources: DataSources = {
      kbTypes: [],
      kbKeyCache: new Map(),
      fetchKbKeys: () => {},
      nodeTree: null,
      fetchNodeTree: () => {},
      stats: baseStats({
        effective_params_at_cursor: { 'global:reasoning': 'medium' },
      }),
      mountDirCache: new Map(),
      fetchMountDir: () => {},
      viewingAtProjectCursor: false,
    }
    const st: ParseState = {
      phase: 'positional',
      activePayload: { name: 'prompt', valueType: 'prompt' },
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    const reasoning = getSuggestions(st, writeDef, sources).find((s) => s.value === '--reasoning')
    expect(reasoning?.effectiveParamPin).toBeUndefined()
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
      viewingAtProjectCursor: true,
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

const SAMPLE_IMAGE_BACKEND: ImageBackendStats = {
  id: 'a2e',
  api: 'a2e',
  model: 'm',
  aspect_ratios: ['1:1'],
  sizes: ['1k'],
  default_aspect: '1:1',
  default_size: '1k',
  default_batch: 1,
  max_batch: 4,
  max_prompt_chars: 200,
  supports_reference_images: true,
}

describe('media-generate --ref availability', () => {
  it('does not suggest --ref when cloud_mount is false', () => {
    const stats = baseStats({
      has_mount: true,
      image_backends: [SAMPLE_IMAGE_BACKEND],
      cloud_mount: false,
    })
    const gen = mediaModule.commands(stats).find((d) => d.trigger === 'media-generate')!
    const refOpt = gen.options!.find((o) => o.name === 'ref')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(refOpt, st, gen, stats)).toBe(false)
  })

  it('suggests --ref when cloud_mount and reference_images_supported', () => {
    const stats = baseStats({
      has_mount: true,
      image_backends: [SAMPLE_IMAGE_BACKEND],
      cloud_mount: true,
      reference_images_supported: true,
    })
    const gen = mediaModule.commands(stats).find((d) => d.trigger === 'media-generate')!
    const refOpt = gen.options!.find((o) => o.name === 'ref')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(refOpt, st, gen, stats)).toBe(true)
  })

  it('does not suggest --ref when cloud_mount but no API supports reference images', () => {
    const stats = baseStats({
      has_mount: true,
      image_backends: [{ ...SAMPLE_IMAGE_BACKEND, supports_reference_images: false }],
      cloud_mount: true,
      reference_images_supported: false,
    })
    const gen = mediaModule.commands(stats).find((d) => d.trigger === 'media-generate')!
    const refOpt = gen.options!.find((o) => o.name === 'ref')!
    const st: ParseState = {
      phase: 'idle',
      currentToken: '',
      completedPositional: {},
      completedOptions: {},
      canOfferOptions: true,
    }
    expect(optionShouldSuggest(refOpt, st, gen, stats)).toBe(false)
  })
})

describe('media-generate --from', () => {
  it('exposes --from as file-path option', () => {
    const stats = baseStats({
      has_mount: true,
      image_backends: [SAMPLE_IMAGE_BACKEND],
    })
    const gen = mediaModule.commands(stats).find((d) => d.trigger === 'media-generate')!
    const fromOpt = gen.options!.find((o) => o.name === 'from')
    expect(fromOpt?.valueType).toBe('file-path')
  })

  it('prompt positional is optional so --from-only works', () => {
    const stats = baseStats({
      has_mount: true,
      image_backends: [SAMPLE_IMAGE_BACKEND],
    })
    const gen = mediaModule.commands(stats).find((d) => d.trigger === 'media-generate')!
    const promptPos = gen.positional!.find((p) => p.name === 'prompt')!
    expect(promptPos.required).toBe(false)
  })
})
