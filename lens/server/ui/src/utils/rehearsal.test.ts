import { describe, expect, it } from 'vitest'
import type { TriggerRehearsal } from '../services/api'
import { formatRehearsal } from './rehearsal'

type Run = TriggerRehearsal['runs'][number]

const base = {
  slug: 'design-cellar',
  when: 'w',
  node: 'story',
  player_line: 'I open it',
  at: '',
  targets: [] as string[],
  then: '',
  hits_after: 0,
}

function run(over: Partial<Run>): Run {
  return {
    suggested: false,
    markers: [],
    other_markers: [],
    interrupted: false,
    outcome: 'missed',
    text: '',
    then_text: null,
    then_markers: [],
    ...over,
  }
}

describe('formatRehearsal (parity with lens test-play --trigger)', () => {
  it('reports each run and the rate', () => {
    const out = formatRehearsal(
      {
        ...base,
        hits: 1,
        runs: [
          run({ suggested: true, markers: ['design-cellar'], outcome: 'suggested', text: 'a' }),
          run({ markers: ['design-loft'], other_markers: ['design-loft'], text: 'b' }),
        ],
      },
      false,
    )
    expect(out).toContain('run 1: suggested design-cellar')
    expect(out).toContain('run 2: wrong marker  ✗  (also: design-loft)')
    expect(out).toContain('1/2 suggested design-cellar')
  })

  it('shows the beats when verbose', () => {
    const out = formatRehearsal({ ...base, hits: 0, runs: [run({ text: 'Below: barrels.' })] }, true)
    expect(out).toContain('no marker')
    expect(out).toContain('Below: barrels.')
  })

  it('separates stopped short from a miss on both beats', () => {
    const out = formatRehearsal(
      {
        ...base,
        then: 'Yes.',
        hits: 0,
        hits_after: 1,
        runs: [
          run({ outcome: 'stopped-short', text: 'Up?', then_text: 'You go.', then_markers: ['design-cellar'] }),
          run({ text: 'a', then_text: 'b' }),
        ],
      },
      false,
    )
    expect(out).toContain('run 1: stopped short; suggested design-cellar on the next beat')
    expect(out).toContain('run 2: no marker, nor on the next beat')
    expect(out).toContain('0/2 suggested design-cellar, +1 after one more beat')
  })
})
