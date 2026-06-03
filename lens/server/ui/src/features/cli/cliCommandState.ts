import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import { COMMAND_DEFINITIONS, KNOWN_COMMANDS } from '../../commands/handlers'
import { parseCliInput } from '../../commands/parser'
import type { Stats } from '../../services/api'
import { kbMentionAtCaret } from '../../utils/cliCaret'
import {
  getCommandSuggestions,
  getSuggestions,
  limitCliSuggestions,
  filterCommandDefinitionsForViewingNode,
  type Suggestion,
} from './CliAutocomplete'
import { navAddrToDisplayAddr } from './cliAddress'
import { goCursorChipMatchesToken } from './cliParseHelpers'
import { applyLinePickFromCommandState, type LinePickDeps } from './cliLinePick'
import type { CliDataSources } from './cliDataSources'

export type CliCommandStateMutable = {
  input: string
  isKnownCommand: boolean
  showInvalid: boolean
  activeCommandDef: CommandDefinition | null
  currentParseState: ParseState | null
  suggestions: Suggestion[]
  addressAutoFilled: boolean
  lastAutoFilledCommand: string | null
}

export type CliCommandStateDeps = {
  busy: boolean
  isFocused: boolean
  sessionFillSuppressed: boolean
  viewingOffCursorNode: boolean
  stats: Stats | null
  currentAddress: string | null
  cliCaretHi: number
  hasCliInputEl: boolean
  captureCliCaret: () => void
  dataSources: CliDataSources
  onUpdate: () => void
  linePickDeps: LinePickDeps
}

/** Returns true when caller should recurse into updateCommandState. */
export function updateCliCommandState(
  mutable: CliCommandStateMutable,
  deps: CliCommandStateDeps,
): boolean {
  const trimmed = mutable.input.trim()
  const cursorAddr = deps.stats?.cursor ?? null
  const viewingAtProjectCursor = cursorAddr === null || deps.currentAddress === cursorAddr
  const viewingOffCursorNode = deps.viewingOffCursorNode

  if ((trimmed === '' || trimmed === '/') && !deps.sessionFillSuppressed && !viewingOffCursorNode) {
    const sessionOp = deps.stats?.active_session_operator
    if (sessionOp && KNOWN_COMMANDS.includes(sessionOp)) {
      mutable.input = '/' + sessionOp + ' '
      return true
    }
  }

  const startsWithSlash = trimmed.startsWith('/')
  const withoutSlash = startsWithSlash ? trimmed.slice(1) : trimmed
  const parts = withoutSlash.split(/\s+/).filter(Boolean)
  const commandPart = parts[0] ?? ''
  const hasCommandText = commandPart.length > 0
  const lower = commandPart.toLowerCase()

  mutable.isKnownCommand =
    !hasCommandText || KNOWN_COMMANDS.includes(lower) || goCursorChipMatchesToken(lower)
  mutable.showInvalid =
    !deps.busy &&
    startsWithSlash &&
    hasCommandText &&
    !mutable.isKnownCommand &&
    !KNOWN_COMMANDS.some((command) => command.startsWith(lower)) &&
    !goCursorChipMatchesToken(lower)

  mutable.activeCommandDef = hasCommandText
    ? (COMMAND_DEFINITIONS.find((definition) => definition.trigger === lower) ?? null)
    : null

  const state = parseCliInput(mutable.input, mutable.activeCommandDef)
  mutable.currentParseState = state
  if (deps.isFocused && deps.hasCliInputEl) {
    deps.captureCliCaret()
  }

  const currentTrigger = mutable.activeCommandDef?.trigger ?? null
  if (currentTrigger !== mutable.lastAutoFilledCommand) {
    mutable.lastAutoFilledCommand = currentTrigger
    mutable.addressAutoFilled = false
  }

  const autofillAddressFromVisibleNode =
    mutable.activeCommandDef?.trigger === 'attach' ||
    mutable.activeCommandDef?.trigger === 'edit' ||
    mutable.activeCommandDef?.trigger === 'structure-rewind' ||
    mutable.activeCommandDef?.trigger === 'structure-rename' ||
    mutable.activeCommandDef?.trigger === 'structure-collate' ||
    (mutable.activeCommandDef?.trigger === 'media' &&
      (state.completedPositional['action'] as string | undefined) === 'attach')

  if (
    autofillAddressFromVisibleNode &&
    !mutable.addressAutoFilled &&
    state.activePayload?.valueType === 'address' &&
    state.currentToken === '' &&
    deps.currentAddress
  ) {
    deps.dataSources.fetchNodeTree(deps.onUpdate)
    const displayAddr = navAddrToDisplayAddr(deps.currentAddress, deps.dataSources.nodeTreeCache)
    if (displayAddr) {
      mutable.addressAutoFilled = true
      mutable.input = mutable.input.trimEnd() + ' ' + displayAddr + ' '
      return true
    }
  }

  const linePickEarlyReturn = applyLinePickFromCommandState(
    state,
    mutable.activeCommandDef,
    mutable.input,
    deps.cliCaretHi,
    deps.linePickDeps,
  )
  if (linePickEarlyReturn) return false

  if (!deps.isFocused) {
    mutable.suggestions = []
    return false
  }

  if (state.phase === 'command') {
    const defsForView = filterCommandDefinitionsForViewingNode(
      COMMAND_DEFINITIONS,
      viewingAtProjectCursor,
    )
    let commandSuggestions = getCommandSuggestions(defsForView, state.currentToken)
    if (viewingOffCursorNode && cursorAddr && goCursorChipMatchesToken(state.currentToken)) {
      const goCursor: Suggestion = {
        label: '@cursor',
        value: '@cursor',
        kind: 'go-cursor',
        group: 'cli',
      }
      commandSuggestions = [goCursor, ...commandSuggestions]
    }
    mutable.suggestions = limitCliSuggestions(commandSuggestions)
    return false
  }

  if (!mutable.activeCommandDef) {
    mutable.suggestions = []
    return false
  }

  if (mutable.activeCommandDef.hint && state.phase === 'positional' && !state.activePayload) {
    mutable.suggestions = []
    return false
  }

  let suggestionState = state
  if (
    state.phase === 'positional' &&
    deps.hasCliInputEl &&
    (state.activePayload?.valueType === 'prompt' || state.activePayload?.valueType === 'string')
  ) {
    const mention = kbMentionAtCaret(mutable.input, deps.cliCaretHi)
    suggestionState = {
      ...state,
      currentToken: mention ? mention.token : state.currentToken,
    }
  }

  mutable.suggestions = limitCliSuggestions(
    getSuggestions(
      suggestionState,
      mutable.activeCommandDef,
      deps.dataSources.makeDataSources(deps.stats, deps.currentAddress, deps.onUpdate),
    ),
  )
  return false
}
