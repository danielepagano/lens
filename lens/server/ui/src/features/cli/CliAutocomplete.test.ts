import { describe, it, expect } from 'vitest'
import type { CommandDefinition } from '../../commands/common'
import {
  dashedGroupingCompletionSuffix,
  decomposeKbKeyTypingPrefix,
  filterCommandDefinitionsForViewingNode,
  groupDenseSegmentedPrefixes,
  joinKbStemAndGroupedRest,
  kbKeyRemainderAfterStem,
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
