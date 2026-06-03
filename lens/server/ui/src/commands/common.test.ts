import { describe, expect, it } from 'vitest'
import { normalizePromptNodeSliceMentions } from './common'

describe('normalizePromptNodeSliceMentions', () => {
  it('normalizes active narrative friendly mentions', () => {
    expect(normalizePromptNodeSliceMentions('use @/chapter-1 32 34 now')).toBe(
      'use @/chapter-1@32:34 now',
    )
  })

  it('normalizes explicit narrative friendly mentions', () => {
    expect(normalizePromptNodeSliceMentions('check @story/chapter-1 8 12 please')).toBe(
      'check @story/chapter-1@8:12 please',
    )
  })

  it('leaves canonical mentions and KB mentions unchanged', () => {
    expect(
      normalizePromptNodeSliceMentions(
        'keep @/chapter-1@32:34 and @person.amy as-is',
      ),
    ).toBe('keep @/chapter-1@32:34 and @person.amy as-is')
  })
})
