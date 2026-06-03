import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import { COMMAND_DEFINITIONS } from '../../commands/handlers'
import { kbMentionAtCaret } from '../../utils/cliCaret'
import type { Suggestion } from './CliAutocomplete'
import {
  GO_CURSOR_CHIP,
  commandHasNoCliParameters,
  parseCommandAndPayload,
} from './cliParseHelpers'
import { displayAddrToNavAddr } from './cliAddress'
import type { TreeNode } from '../../services/api'

export type SuggestionApplyDeps = {
  getInput: () => string
  setInput: (value: string) => void
  getActiveCommandDef: () => CommandDefinition | null
  getCurrentParseState: () => ParseState | null
  getCliCaretHi: () => number
  setCliCaretHi: (pos: number) => void
  setPendingCliCaretHi: (pos: number | null) => void
  getNodeTreeCache: () => TreeNode[] | null
  getCurrentAddress: () => string | null
  navigate: ((addr: string) => Promise<void>) | undefined
  updateCommandState: () => void
  focusCliInput: () => void
  getCliInputEl: () => HTMLTextAreaElement | null
  afterTick: (fn: () => void) => void
  trySubmitIfComplete: () => void
}

export function suggestionChipRunsImmediately(suggestion: Suggestion): boolean {
  if (suggestion.kind === 'go-cursor') return true
  if (suggestion.kind !== 'command') return false
  if (suggestion.completionSuffix !== ' ') return false
  const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === suggestion.value)
  return commandHasNoCliParameters(definition)
}

function completeCommand(command: string, deps: SuggestionApplyDeps): void {
  const { payload } = parseCommandAndPayload(deps.getInput())
  deps.setInput(`/${command}${payload ? ` ${payload}` : ' '}`)
  deps.updateCommandState()
  deps.focusCliInput()
}

export function replaceCurrentToken(replacement: string, deps: SuggestionApplyDeps): void {
  const input = deps.getInput()
  const state = deps.getCurrentParseState()
  const freeformPositional =
    state?.phase === 'positional' &&
    (state.activePayload?.valueType === 'prompt' || state.activePayload?.valueType === 'string')
  if (freeformPositional) {
    const hi = Math.min(Math.max(deps.getCliCaretHi(), 0), input.length)
    const mention = kbMentionAtCaret(input, hi)
    if (mention) {
      let mentionEnd = mention.at
      while (mentionEnd < input.length && !/\s/.test(input[mentionEnd]!)) mentionEnd += 1
      deps.setInput(input.slice(0, mention.at) + replacement + input.slice(mentionEnd))
      const pos = mention.at + replacement.length
      deps.setPendingCliCaretHi(pos)
      deps.setCliCaretHi(pos)
      deps.updateCommandState()
      deps.afterTick(() => {
        deps.focusCliInput()
        deps.getCliInputEl()?.setSelectionRange(pos, pos)
        deps.setCliCaretHi(pos)
        deps.setPendingCliCaretHi(null)
      })
    } else {
      const separator = input.endsWith(' ') ? '' : ' '
      deps.setInput(input + separator + replacement)
      const pos = deps.getInput().length
      deps.setPendingCliCaretHi(pos)
      deps.setCliCaretHi(pos)
      deps.updateCommandState()
      deps.afterTick(() => {
        deps.focusCliInput()
        deps.getCliInputEl()?.setSelectionRange(pos, pos)
        deps.setCliCaretHi(pos)
        deps.setPendingCliCaretHi(null)
      })
    }
    return
  }

  const trimmed = input.trim()
  const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
  const allTokens = withoutSlash.split(/\s+/).filter(Boolean)
  const endsWithSpace = input.endsWith(' ')

  if (endsWithSpace || allTokens.length <= 1) {
    deps.setInput((endsWithSpace ? input : input + ' ') + replacement)
  } else {
    let beforeLastToken = input.slice(0, input.lastIndexOf(allTokens[allTokens.length - 1]!))
    if (replacement.startsWith('-') && beforeLastToken.length > 0 && !beforeLastToken.endsWith(' ')) {
      beforeLastToken += ' '
    }
    deps.setInput(beforeLastToken + replacement)
  }
  deps.updateCommandState()
  deps.setPendingCliCaretHi(null)
  deps.focusCliInput()
}

export function completeSuggestion(suggestion: Suggestion, deps: SuggestionApplyDeps): void {
  const activeCommandDef = deps.getActiveCommandDef()
  const currentParseState = deps.getCurrentParseState()

  switch (suggestion.kind) {
    case 'go-cursor':
      completeCommand(GO_CURSOR_CHIP, deps)
      return
    case 'command':
      if (suggestion.completionSuffix === '-') {
        deps.setInput('/' + suggestion.value + '-')
        deps.updateCommandState()
        deps.focusCliInput()
      } else {
        completeCommand(suggestion.value, deps)
      }
      return
    case 'slug':
      replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '), deps)
      return
    case 'kb-type':
      replaceCurrentToken(suggestion.value, deps)
      return
    case 'kb-key':
      replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '), deps)
      return
    case 'flag':
      if (activeCommandDef?.options && suggestion.value.startsWith('--')) {
        const optionName = suggestion.value.slice(2)
        const option = activeCommandDef.options.find((item) => item.name === optionName)
        if (option?.default) {
          const defaultValue = option.default
          const needsTrailingSpace = !defaultValue.endsWith('.')
          replaceCurrentToken(
            `${suggestion.value} ${defaultValue}${needsTrailingSpace ? ' ' : ''}`,
            deps,
          )
          deps.trySubmitIfComplete()
          return
        }
      }
      replaceCurrentToken(suggestion.value + ' ', deps)
      deps.trySubmitIfComplete()
      return
    case 'node': {
      const inAddressSlot = currentParseState?.activePayload?.valueType === 'address'
      if (suggestion.value === '/') {
        replaceCurrentToken(suggestion.nodeHasChildren ? '/' : '/ ', deps)
      } else {
        replaceCurrentToken(suggestion.value + (suggestion.nodeHasChildren ? '/' : ' '), deps)
      }
      if (inAddressSlot) {
        const displayAddr = suggestion.value.replace(/\/+$/, '') || '/'
        const navAddr = displayAddrToNavAddr(displayAddr, deps.getNodeTreeCache())
        if (navAddr && navAddr !== deps.getCurrentAddress()) void deps.navigate?.(navAddr)
      }
      return
    }
    case 'dice-roll':
    case 'time-now':
      replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ''), deps)
      return
    case 'var-prefix':
      replaceCurrentToken(suggestion.value, deps)
      return
    case 'var-key':
      replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '), deps)
      return
  }
}

export function replaceTokenForLinePick(line: number, deps: SuggestionApplyDeps): void {
  replaceCurrentToken(String(line) + ' ', deps)
}
