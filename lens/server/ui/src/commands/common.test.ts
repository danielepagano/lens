import { describe, expect, it } from 'vitest'
import { moduleKeys, normalizePromptNodeSliceMentions } from './common'
import { unquoteShellWord } from './parser'

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

describe('moduleKeys (parity with lens/cli/options.py module_keys)', () => {
  it('accepts keys or canonical ids, repeated, deduplicated', () => {
    expect(moduleKeys(['encounter', 'design.clock', 'design.encounter', ' '], 'design.')).toEqual([
      'encounter',
      'clock',
    ])
  })

  it('takes a lone value and ignores absent ones', () => {
    expect(moduleKeys('rules.combat', 'rules.')).toEqual(['combat'])
    expect(moduleKeys(undefined, 'rules.')).toEqual([])
  })
})

describe('unquoteShellWord (a prompt reads as the shell would pass it)', () => {
  it('strips one wrapping pair', () => {
    expect(unquoteShellWord('"design the cellar"')).toBe('design the cellar')
    expect(unquoteShellWord("'design the cellar'")).toBe('design the cellar')
    expect(unquoteShellWord('"say \\"hi\\" now"')).toBe('say "hi" now')
  })

  it('leaves prose that merely starts and ends with a quote', () => {
    expect(unquoteShellWord('"Hi," she said "bye"')).toBe('"Hi," she said "bye"')
    expect(unquoteShellWord('plain words')).toBe('plain words')
    expect(unquoteShellWord('"')).toBe('"')
  })
})
