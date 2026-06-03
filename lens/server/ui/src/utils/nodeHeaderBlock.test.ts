import { describe, expect, it } from 'vitest'
import { parseLensNodeHeaderBlock } from './nodeHeaderBlock'

describe('parseLensNodeHeaderBlock', () => {
  it('parses kb_pin, vars, and params from YAML block', () => {
    const md = `[
  kb_pin:
    - place.a
  vars:
    mood: tense
  params:
    global:
      llm_id: fast
    write:
      steps: 2
]: #

# Body
`
    const p = parseLensNodeHeaderBlock(md)
    expect(p.pins).toEqual(['place.a'])
    expect(p.unpins).toEqual([])
    expect(p.varsEntries).toEqual([['mood', 'tense']])
    expect(p.paramPills).toEqual(
      expect.arrayContaining([
        { scope: 'global', name: 'llm_id', value: 'fast' },
        { scope: 'write', name: 'steps', value: '2' },
      ]),
    )
    expect(p.paramPills).toHaveLength(2)
  })

  it('returns empty when no opening block', () => {
    expect(parseLensNodeHeaderBlock('# no block\n')).toEqual({
      pins: [],
      unpins: [],
      varsEntries: [],
      paramPills: [],
    })
  })
})
