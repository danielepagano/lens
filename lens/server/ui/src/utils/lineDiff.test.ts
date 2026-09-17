import { describe, it, expect } from 'vitest'
import { computeLineDiff } from './lineDiff'

describe('computeLineDiff', () => {
  it('marks identical input as all equal', () => {
    const text = 'one\ntwo\nthree'
    const lines = computeLineDiff(text, text)
    expect(lines.every((l) => l.kind === 'equal')).toBe(true)
    expect(lines.map((l) => l.text)).toEqual(['one', 'two', 'three'])
  })

  it('detects a pure insertion', () => {
    const lines = computeLineDiff('one\nthree', 'one\ntwo\nthree')
    expect(lines).toEqual([
      { kind: 'equal', text: 'one' },
      { kind: 'insert', text: 'two' },
      { kind: 'equal', text: 'three' },
    ])
  })

  it('detects a pure deletion', () => {
    const lines = computeLineDiff('one\ntwo\nthree', 'one\nthree')
    expect(lines).toEqual([
      { kind: 'equal', text: 'one' },
      { kind: 'delete', text: 'two' },
      { kind: 'equal', text: 'three' },
    ])
  })

  it('shows a replaced line as delete+insert', () => {
    const lines = computeLineDiff('one\ntwo\nthree', 'one\nTWO\nthree')
    expect(lines).toEqual([
      { kind: 'equal', text: 'one' },
      { kind: 'insert', text: 'TWO' },
      { kind: 'delete', text: 'two' },
      { kind: 'equal', text: 'three' },
    ])
  })

  it('treats empty current as inserts plus the empty leading line', () => {
    // ''.split('\n') is [''], not [], so the empty current still contributes
    // one line to the diff — it just has no match on the proposed side.
    const lines = computeLineDiff('', 'one\ntwo')
    expect(lines).toEqual([
      { kind: 'insert', text: 'one' },
      { kind: 'insert', text: 'two' },
      { kind: 'delete', text: '' },
    ])
  })

  it('reconstructs each side from the respective diff kinds', () => {
    const current = 'a\nb\nc\nd'
    const proposed = 'a\nB\nc\ne'
    const lines = computeLineDiff(current, proposed)

    const reconstructedCurrent = lines
      .filter((l) => l.kind === 'equal' || l.kind === 'delete')
      .map((l) => l.text)
      .join('\n')
    const reconstructedProposed = lines
      .filter((l) => l.kind === 'equal' || l.kind === 'insert')
      .map((l) => l.text)
      .join('\n')

    expect(reconstructedCurrent).toBe(current)
    expect(reconstructedProposed).toBe(proposed)
  })
})
