import { describe, expect, it } from 'vitest'
import { moduleKeys, normalizePromptNodeSliceMentions } from './common'
import { buildArgs, parseCliInput, unquoteShellWord } from './parser'
import type { CommandDefinition } from './common'

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

describe('quoted option values (parity with the shell)', () => {
  const def: CommandDefinition = {
    trigger: 'test-play',
    group: 'rpg',
    cursorTargeting: 'always',
    positional: [{ name: 'id', valueType: 'kb-id' }],
    options: [
      { name: 'prompt', valueType: 'prompt' },
      { name: 'at', valueType: 'string' },
      { name: 'trigger', valueType: 'slug' },
    ],
  }
  const parse = (line: string) => buildArgs(parseCliInput(line, def), def)

  it('takes a quoted multi-word value as one option value', () => {
    const args = parse('/test-play location.graysteps --trigger play-glow --at "Day 7, before first light" --prompt \'I walk on\' ')
    expect(args.options['at']).toBe('Day 7, before first light')
    expect(args.options['prompt']).toBe('I walk on')
    expect(args.options['trigger']).toBe('play-glow')
    expect(args.positional['id']).toBe('location.graysteps')
  })

  it('leaves unquoted single tokens alone', () => {
    expect(parse('/test-play --trigger play-glow ').options['trigger']).toBe('play-glow')
  })
})
