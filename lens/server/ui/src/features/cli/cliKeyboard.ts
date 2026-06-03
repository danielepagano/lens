import { get } from 'svelte/store'
import { KNOWN_COMMANDS } from '../../commands/handlers'
import { parsedHash } from '../../stores/parsedHash'
import { currentProject } from '../../stores/project'
import { currentAddress } from '../../stores/document'
import { vnModeFromParsed, vnPlayback } from '../../stores/visualNovel'
import {
  cliHistory,
  cliHistoryIndex,
  cliInputRequest,
  cliOutput,
  scrollContentToBottom,
} from '../../stores/ui'
import { stats } from '../../stores/stats'
import {
  exitVisualNovel,
  resolveVisualNovelIndex,
  resolveVisualNovelTtsSettings,
} from '../../utils/vnNavigate'
import { vnNavigableIndices } from '../../utils/vnPlaybackNav'
import type { Suggestion } from './CliAutocomplete'
import { completeSuggestion, type SuggestionApplyDeps } from './cliSuggestionApply'
import { parseCommandAndPayload } from './cliParseHelpers'
import { shouldSpaceSubmit } from './cliSubmitRules'

export type CliKeyboardDeps = {
  getInput: () => string
  setInput: (value: string) => void
  busy: boolean
  sessionFillSuppressed: boolean
  setSessionFillSuppressed: (value: boolean) => void
  suggestions: Suggestion[]
  getCliInputEl: () => HTMLTextAreaElement | null
  inputIsMultiLine: () => boolean
  updateCommandState: () => void
  focusCliInput: () => void
  submit: () => void
  completeCommand: (command: string) => void
  suggestionApplyDeps: SuggestionApplyDeps
  afterTick: (fn: () => void) => void
}

function completeCommandFromKeyboard(command: string, deps: CliKeyboardDeps): void {
  deps.completeCommand(command)
}

export function handleCliKeydown(event: KeyboardEvent, deps: CliKeyboardDeps): void {
  const input = deps.getInput()
  const isTouchDevice = typeof window !== 'undefined' && 'ontouchstart' in window
  const trimmed = input.trim()
  const isLogicalEmpty = trimmed === '' || trimmed === '/'

  if (event.key === 'Backspace' && !deps.sessionFillSuppressed) {
    const sessionOp = get(stats)?.active_session_operator
    if (sessionOp && (trimmed === '/' + sessionOp || trimmed === '/' + sessionOp + ' ')) {
      event.preventDefault()
      deps.setInput('')
      deps.setSessionFillSuppressed(true)
      let leftSceneCliBeat = false
      const slug = get(currentProject)
      const addr = get(currentAddress)
      if (slug && addr) {
        const ph = get(parsedHash)
        const items = get(vnPlayback)?.items ?? []
        if (
          vnModeFromParsed(ph, slug, addr) &&
          items.length > 0 &&
          resolveVisualNovelIndex(ph, slug, addr) === vnNavigableIndices(items).length
        ) {
          exitVisualNovel(
            slug,
            addr,
            vnNavigableIndices(items).length,
            resolveVisualNovelTtsSettings(ph),
          )
          leftSceneCliBeat = true
        }
      }
      deps.updateCommandState()
      if (leftSceneCliBeat) {
        deps.afterTick(() => {
          cliInputRequest.set('')
          scrollContentToBottom.update((count) => count + 1)
        })
      } else {
        deps.afterTick(() => deps.focusCliInput())
      }
      return
    }
  }

  if (isLogicalEmpty) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (isTouchDevice) deps.getCliInputEl()?.blur()
      return
    }
    if (event.key === 'Backspace') {
      if (get(cliOutput)) {
        event.preventDefault()
        cliOutput.set(null)
        return
      }
      if (isTouchDevice) {
        event.preventDefault()
        deps.getCliInputEl()?.blur()
        return
      }
    }
  }

  if (
    event.key === ' ' &&
    !deps.busy &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !event.isComposing
  ) {
    const el = deps.getCliInputEl()
    if (el) {
      const start = el.selectionStart ?? input.length
      const end = el.selectionEnd ?? input.length
      const candidate = input.slice(0, start) + ' ' + input.slice(end)
      if (shouldSpaceSubmit(candidate)) {
        event.preventDefault()
        deps.setInput(candidate)
        deps.updateCommandState()
        deps.submit()
        return
      }
    }
  }

  if (event.key === 'Tab' && !event.shiftKey && deps.suggestions.length > 0) {
    event.preventDefault()
    const first = deps.suggestions[0]
    if (!first) return
    if (first.kind === 'command') {
      const { command } = parseCommandAndPayload(input)
      if (command && KNOWN_COMMANDS.includes(command)) {
        const idx = KNOWN_COMMANDS.findIndex((item) => item === command)
        const next = idx === -1 ? 0 : (idx + 1) % KNOWN_COMMANDS.length
        completeCommandFromKeyboard(KNOWN_COMMANDS[next] ?? KNOWN_COMMANDS[0] ?? '', deps)
        return
      }
    }
    completeSuggestion(first, deps.suggestionApplyDeps)
    return
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    deps.submit()
    return
  }

  if (event.key === 'ArrowUp') {
    if (deps.inputIsMultiLine()) return
    event.preventDefault()
    const history = get(cliHistory)
    const historyIndex = get(cliHistoryIndex)
    if (history.length === 0) return
    if (historyIndex === -1) {
      cliHistoryIndex.set(history.length - 1)
      deps.setInput(history[history.length - 1] ?? '')
    } else if (historyIndex > 0) {
      cliHistoryIndex.set(historyIndex - 1)
      deps.setInput(history[historyIndex - 1] ?? '')
    }
    deps.updateCommandState()
    return
  }

  if (event.key === 'ArrowDown') {
    if (deps.inputIsMultiLine()) return
    event.preventDefault()
    const history = get(cliHistory)
    const historyIndex = get(cliHistoryIndex)
    if (historyIndex === -1) {
      deps.setInput('')
    } else if (historyIndex < history.length - 1) {
      cliHistoryIndex.set(historyIndex + 1)
      deps.setInput(history[historyIndex + 1] ?? '')
    } else {
      cliHistoryIndex.set(-1)
      deps.setInput('')
    }
    deps.updateCommandState()
  }
}

export function isFocusCliShortcut(event: KeyboardEvent): boolean {
  if (event.code !== 'Backquote') return false
  if (!event.ctrlKey || event.metaKey || event.altKey) return false
  if (event.shiftKey) return false
  return true
}
