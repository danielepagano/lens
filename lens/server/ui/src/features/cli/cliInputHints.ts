import { tick } from 'svelte'
import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { HTMLTextareaAttributes } from 'svelte/elements'
import { promptDiceExpressionHint } from '../../utils/cliCaret'

export function computeCliHint(
  input: string,
  cliCaretHi: number,
  activeCommandDef: CommandDefinition | null,
  isKnownCommand: boolean,
  currentParseState: ParseState | null,
): string {
  if (!activeCommandDef || !isKnownCommand) return ''
  if (
    currentParseState?.activePayload?.valueType === 'prompt' &&
    currentParseState.phase === 'positional' &&
    promptDiceExpressionHint(input, cliCaretHi)
  ) {
    return 'dice expression'
  }
  const activeHint = currentParseState?.activePayload?.hint
  if (activeHint) return activeHint
  const trimmed = input.trim()
  const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
  const hasPayload = withoutSlash.split(/\s+/).filter(Boolean).length > 1
  if (!hasPayload) return activeCommandDef.hint ?? ''
  return ''
}

export function computeCliInputAttrs(currentParseState: ParseState | null): {
  autocomplete: HTMLTextareaAttributes['autocomplete']
  autocorrect: HTMLTextareaAttributes['autocorrect']
  autocapitalize: HTMLTextareaAttributes['autocapitalize']
  spellcheck: boolean
  promptAssistEnabled: boolean
} {
  const state = currentParseState
  if (!state?.activePayload) {
    return {
      autocomplete: 'off',
      autocorrect: 'off',
      autocapitalize: 'off',
      spellcheck: false,
      promptAssistEnabled: false,
    }
  }
  const valueType = state.activePayload.valueType
  const promptAssistEnabled =
    valueType === 'prompt' && (state.phase === 'positional' || state.phase === 'option-value')
  const textAssistEnabled =
    (valueType === 'string' || valueType === 'prompt') &&
    (state.phase === 'positional' || state.phase === 'option-value')
  return {
    autocomplete: textAssistEnabled ? 'on' : 'off',
    autocorrect: promptAssistEnabled ? 'on' : 'off',
    autocapitalize: promptAssistEnabled ? 'sentences' : 'off',
    spellcheck: promptAssistEnabled,
    promptAssistEnabled,
  }
}

export function scheduleCliResize(resize: () => void): void {
  void tick().then(() => resize())
}

export function setupIosViewportHandler(): () => void {
  const clearAppViewportOverride = () => {
    const app = document.getElementById('app')
    if (!app) return
    app.style.height = ''
    app.style.marginTop = ''
  }
  const handleViewportResize = () => {
    const vv = window.visualViewport
    if (!vv) return
    const app = document.getElementById('app')
    if (!app) return
    const delta = window.innerHeight - vv.height - vv.offsetTop
    if (delta > 50) {
      app.style.height = `${vv.height}px`
      app.style.marginTop = `${vv.offsetTop}px`
      window.scrollTo(0, 0)
      return
    }
    clearAppViewportOverride()
  }
  const vv = window.visualViewport
  vv?.addEventListener('resize', handleViewportResize)
  vv?.addEventListener('scroll', handleViewportResize)
  return () => {
    vv?.removeEventListener('resize', handleViewportResize)
    vv?.removeEventListener('scroll', handleViewportResize)
    clearAppViewportOverride()
  }
}
