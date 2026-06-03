import { describe, expect, it } from 'vitest'
import { promptNodeMentionLinePickAtCaret } from './cliCaret'

describe('promptNodeMentionLinePickAtCaret', () => {
  it('enters address-pick mode after address plus space', () => {
    const input = '/play say @/chapter-1 '
    expect(promptNodeMentionLinePickAtCaret(input, input.length)).toEqual({
      address: '/chapter-1',
    })
  })

  it('keeps line-pick mode after first selected line', () => {
    const input = '/play say @/chapter-1 12 '
    expect(promptNodeMentionLinePickAtCaret(input, input.length)).toEqual({
      address: '/chapter-1',
      startLine: 12,
    })
  })

  it('reports completed range after second selected line', () => {
    const input = '/play say @/chapter-1 12 18 '
    expect(promptNodeMentionLinePickAtCaret(input, input.length)).toEqual({
      address: '/chapter-1',
      startLine: 12,
      endLine: 18,
    })
  })
})
