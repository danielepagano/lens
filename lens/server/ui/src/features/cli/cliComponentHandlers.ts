import { tick } from 'svelte'
import { get } from 'svelte/store'
import type { Suggestion } from './CliAutocomplete'
import { completeSuggestion, suggestionChipRunsImmediately } from './cliSuggestionApply'
import type { SuggestionApplyDeps } from './cliSuggestionApply'
import { displayAddrToNavAddr } from './cliAddress'
import { GO_CURSOR_CHIP, parseCommandAndPayload } from './cliParseHelpers'
import { shouldSpaceSubmit } from './cliSubmitRules'
import type { CliSubmitDeps } from './cliSubmit'
import { handleCliKeydown } from './cliKeyboard'
import type { ParseState } from '../../commands/parser'
import type { CommandDefinition } from '../../commands/common'
import { currentAddress } from '../../stores/document'
import type { CliDataSources } from './cliDataSources'

export type CliComponentRefs = {
  getInput: () => string
  setInput: (value: string) => void
  getActiveCommandDef: () => CommandDefinition | null
  getCurrentParseState: () => ParseState | null
  getCliCaretHi: () => number
  setCliCaretHi: (pos: number) => void
  setPendingCliCaretHi: (pos: number | null) => void
  getBusy: () => boolean
  setBusy: (value: boolean) => void
  setBusyMessage: (value: string | null) => void
  setFlashInvalid: (value: boolean) => void
  setShowInvalid: (value: boolean) => void
  getSessionFillSuppressed: () => boolean
  setSessionFillSuppressed: (value: boolean) => void
  getSuggestions: () => Suggestion[]
  getCliInputEl: () => HTMLTextAreaElement | null
  dataSources: CliDataSources
  updateCommandState: () => void
  focusCliInput: () => void
  inputIsMultiLine: () => boolean
  navigate: ((addr: string) => Promise<void>) | undefined
  onCliDone: (() => Promise<void>) | undefined
  syncLocation: ((addr: string) => void) | undefined
  submit: () => Promise<void>
}

export function buildSuggestionApplyDeps(refs: CliComponentRefs): SuggestionApplyDeps {
  return {
    getInput: refs.getInput,
    setInput: refs.setInput,
    getActiveCommandDef: refs.getActiveCommandDef,
    getCurrentParseState: refs.getCurrentParseState,
    getCliCaretHi: refs.getCliCaretHi,
    setCliCaretHi: refs.setCliCaretHi,
    setPendingCliCaretHi: refs.setPendingCliCaretHi,
    getNodeTreeCache: () => refs.dataSources.nodeTreeCache,
    getCurrentAddress: () => get(currentAddress),
    navigate: refs.navigate,
    updateCommandState: refs.updateCommandState,
    focusCliInput: refs.focusCliInput,
    getCliInputEl: refs.getCliInputEl,
    afterTick: (fn) => {
      void tick().then(fn)
    },
    trySubmitIfComplete: () => {
      if (shouldSpaceSubmit(refs.getInput())) void refs.submit()
    },
  }
}

export function buildSubmitDeps(refs: CliComponentRefs): CliSubmitDeps {
  return {
    getInput: refs.getInput,
    setInput: refs.setInput,
    setBusy: refs.setBusy,
    setBusyMessage: refs.setBusyMessage,
    setFlashInvalid: refs.setFlashInvalid,
    setShowInvalid: refs.setShowInvalid,
    setSessionFillSuppressed: refs.setSessionFillSuppressed,
    updateCommandState: refs.updateCommandState,
    focusCliInput: refs.focusCliInput,
    getCliInputEl: refs.getCliInputEl,
    navigate: refs.navigate,
    onCliDone: refs.onCliDone,
    syncLocation: refs.syncLocation,
    afterTick: () => tick(),
  }
}

export function handleCliSuggestionChipClick(suggestion: Suggestion, refs: CliComponentRefs): void {
  if (refs.getBusy()) return
  if (suggestionChipRunsImmediately(suggestion)) {
    refs.setInput(suggestion.kind === 'go-cursor' ? `/${GO_CURSOR_CHIP}` : `/${suggestion.value}`)
    refs.updateCommandState()
    void tick().then(() => void refs.submit())
    return
  }
  completeSuggestion(suggestion, buildSuggestionApplyDeps(refs))
}

export function handleCliTextInput(event: Event, refs: CliComponentRefs): void {
  if (!(event.target instanceof HTMLTextAreaElement)) return
  let value = event.target.value
  if (!value.startsWith('/')) value = '/' + value.replace(/^\/+/, '')
  refs.setInput(value)
  refs.updateCommandState()
  const state = refs.getCurrentParseState()
  if (state?.activePayload?.valueType === 'address' && state.currentToken.endsWith('/')) {
    const displayPartial = state.currentToken.replace(/\/+$/, '') || '/'
    const navAddr = displayAddrToNavAddr(displayPartial, refs.dataSources.nodeTreeCache)
    if (navAddr && navAddr !== get(currentAddress)) void refs.navigate?.(navAddr)
  }
}

export function handleCliInputKeydown(event: KeyboardEvent, refs: CliComponentRefs): void {
  handleCliKeydown(event, {
    getInput: refs.getInput,
    setInput: refs.setInput,
    busy: refs.getBusy(),
    sessionFillSuppressed: refs.getSessionFillSuppressed(),
    setSessionFillSuppressed: refs.setSessionFillSuppressed,
    suggestions: refs.getSuggestions(),
    getCliInputEl: refs.getCliInputEl,
    inputIsMultiLine: refs.inputIsMultiLine,
    updateCommandState: refs.updateCommandState,
    focusCliInput: refs.focusCliInput,
    submit: () => void refs.submit(),
    completeCommand: (command) => {
      const { payload } = parseCommandAndPayload(refs.getInput())
      refs.setInput(`/${command}${payload ? ` ${payload}` : ' '}`)
      refs.updateCommandState()
      refs.focusCliInput()
    },
    suggestionApplyDeps: buildSuggestionApplyDeps(refs),
    afterTick: (fn) => {
      void tick().then(fn)
    },
  })
}

export function handleCliInputKeyup(event: KeyboardEvent, refs: CliComponentRefs): void {
  if (refs.getBusy()) return
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) {
    refs.updateCommandState()
  }
}

export function handleCliBeforeInput(event: InputEvent, refs: CliComponentRefs): void {
  if (refs.getBusy() || event.isComposing) return
  if (event.inputType === 'insertLineBreak' || event.inputType === 'insertParagraph') {
    event.preventDefault()
    void refs.submit()
  }
}

export function handleCliFocus(refs: CliComponentRefs, setFocused: (value: boolean) => void): void {
  setFocused(true)
  refs.updateCommandState()
}

export function handleCliBlur(
  event: FocusEvent,
  refs: CliComponentRefs,
  setFocused: (value: boolean) => void,
): void {
  const next = event.relatedTarget
  const container = (event.currentTarget as HTMLTextAreaElement | null)?.closest('.bottom-bar')
  if (next instanceof Node && container?.contains(next)) return
  setFocused(false)
  refs.updateCommandState()
}
