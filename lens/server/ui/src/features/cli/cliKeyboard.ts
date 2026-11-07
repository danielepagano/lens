import { get } from 'svelte/store'
import { KNOWN_COMMANDS } from '../../commands/handlers'
import { parsedHash } from '../../stores/parsedHash'
import { currentProject } from '../../stores/project'
import { currentAddress } from '../../stores/document'
import { vnModeFromParsed, vnPlayback } from '../../stores/visualNovel'
import {
  cliHistory,
  cliHistoryNav,
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
import { caretLineInfo, positionOnLine } from './cliCaretLines'
import {
  historyNewer,
  historyOlder,
  historyToDraft,
  type HistoryStep,
} from '../../utils/cliHistoryNav'

export type CliKeyboardDeps = {
  getInput: () => string
  setInput: (value: string) => void
  busy: boolean
  sessionFillSuppressed: boolean
  setSessionFillSuppressed: (value: boolean) => void
  suggestions: Suggestion[]
  getCliInputEl: () => HTMLTextAreaElement | null
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

  if (event.key === 'Escape' && get(cliHistoryNav).index !== -1) {
    const step = historyToDraft(get(cliHistory), get(cliHistoryNav), input)
    if (step) {
      event.preventDefault()
      applyHistoryStep(step, null, deps)
    }
    return
  }

  if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    if (event.shiftKey || event.altKey || event.metaKey || event.ctrlKey || event.isComposing) return
    const el = deps.getCliInputEl()
    if (!el) return
    // A selection collapses natively; inside a wrapped or multi-line value the
    // caret moves natively until it is on the first (Up) or last (Down) line.
    const where = caretLineInfo(el)
    if (!where) return
    const older = event.key === 'ArrowUp'
    if (older ? !where.onFirstLine : !where.onLastLine) return
    const history = get(cliHistory)
    const nav = get(cliHistoryNav)
    const step = older ? historyOlder(history, nav, input) : historyNewer(history, nav, input)
    // Nothing further: the native move takes the caret to the line's start/end.
    if (!step) return
    event.preventDefault()
    applyHistoryStep(step, { line: older ? 'last' : 'first', x: where.x }, deps)
  }
}

type CaretLanding = { line: 'first' | 'last'; x: number }

/**
 * Show a history slot. Browsing reads like one continuous text, as in a shell
 * or Claude Code: Up lands on the older entry's last line and Down on the newer
 * entry's first line, both at the caret's horizontal position, so every press
 * moves exactly one line. Without a landing (Escape) the caret goes to the end.
 */
function applyHistoryStep(step: HistoryStep, landing: CaretLanding | null, deps: CliKeyboardDeps): void {
  const apply = deps.suggestionApplyDeps
  cliHistoryNav.set(step.nav)
  deps.setInput(step.value)
  apply.setPendingCliCaretHi(step.value.length)
  deps.updateCommandState()
  deps.afterTick(() => {
    const el = deps.getCliInputEl()
    const pos = el && landing ? positionOnLine(el, landing.line, landing.x) : step.value.length
    el?.setSelectionRange(pos, pos)
    apply.setCliCaretHi(pos)
    apply.setPendingCliCaretHi(null)
    deps.updateCommandState()
  })
}

export function isFocusCliShortcut(event: KeyboardEvent): boolean {
  if (event.code !== 'Backquote') return false
  if (!event.ctrlKey || event.metaKey || event.altKey) return false
  if (event.shiftKey) return false
  return true
}
