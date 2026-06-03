import { describe, it, expect, vi } from 'vitest'
import { replaceCurrentToken } from './cliSuggestionApply'
import type { SuggestionApplyDeps } from './cliSuggestionApply'
import type { ParseState } from '../../commands/parser'

function parseState(partial: Partial<ParseState> & Pick<ParseState, 'phase' | 'currentToken'>): ParseState {
  return {
    completedPositional: {},
    completedOptions: {},
    canOfferOptions: false,
    ...partial,
  }
}

function makeDeps(input: string, parse: ParseState | null, caretHi = input.length): SuggestionApplyDeps & {
  readInput: () => string
} {
  let value = input
  let caret = caretHi
  return {
    getInput: () => value,
    setInput: (next) => {
      value = next
    },
    readInput: () => value,
    getActiveCommandDef: () => null,
    getCurrentParseState: () => parse,
    getCliCaretHi: () => caret,
    setCliCaretHi: (pos) => {
      caret = pos
    },
    setPendingCliCaretHi: vi.fn(),
    getNodeTreeCache: () => null,
    getCurrentAddress: () => null,
    navigate: undefined,
    updateCommandState: vi.fn(),
    focusCliInput: vi.fn(),
    getCliInputEl: () => null,
    afterTick: (fn) => fn(),
    trySubmitIfComplete: vi.fn(),
  }
}

describe('replaceCurrentToken', () => {
  it('replaces the current positional token when not in freeform mode', () => {
    const deps = makeDeps(
      '/kb list pers',
      parseState({
        phase: 'positional',
        currentToken: 'pers',
        activePayload: { name: 'type', valueType: 'slug' },
      }),
    )
    replaceCurrentToken('person ', deps)
    expect(deps.readInput()).toBe('/kb list person ')
  })

  it('replaces @-mention token in freeform prompt mode', () => {
    const deps = makeDeps(
      '/write hello @pers',
      parseState({
        phase: 'positional',
        currentToken: '',
        activePayload: { name: 'prompt', valueType: 'prompt' },
      }),
      17,
    )
    replaceCurrentToken('person.amy', deps)
    expect(deps.readInput()).toBe('/write hello person.amy')
  })

  it('appends replacement when freeform prompt has no active mention', () => {
    const deps = makeDeps(
      '/write hello ',
      parseState({
        phase: 'positional',
        currentToken: '',
        activePayload: { name: 'prompt', valueType: 'prompt' },
      }),
      13,
    )
    replaceCurrentToken('world', deps)
    expect(deps.readInput()).toBe('/write hello world')
  })
})
