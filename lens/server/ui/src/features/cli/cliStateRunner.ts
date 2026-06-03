import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { Stats } from '../../services/api'
import type { Suggestion } from './CliAutocomplete'
import { updateCliCommandState } from './cliCommandState'
import type { CliDataSources } from './cliDataSources'
import type { LinePickDeps } from './cliLinePick'

export type CliStateBundle = {
  input: string
  isKnownCommand: boolean
  showInvalid: boolean
  activeCommandDef: CommandDefinition | null
  currentParseState: ParseState | null
  suggestions: Suggestion[]
  addressAutoFilled: boolean
  lastAutoFilledCommand: string | null
}

export type RunCliCommandStateDeps = {
  busy: boolean
  isFocused: boolean
  sessionFillSuppressed: boolean
  cliCaretHi: number
  hasCliInputEl: boolean
  captureCliCaret: () => void
  dataSources: CliDataSources
  onUpdate: () => void
  linePickDeps: Omit<LinePickDeps, 'nodeTreeCache' | 'fetchNodeTree' | 'getCurrentAddress'>
  getStats: () => Stats | null
  getCurrentAddress: () => string | null
}

export function runCliCommandState(
  bundle: CliStateBundle,
  deps: RunCliCommandStateDeps,
): CliStateBundle {
  const cursorAddr = deps.getStats()?.cursor ?? null
  const currentAddr = deps.getCurrentAddress()
  let recurse = true
  while (recurse) {
    recurse = updateCliCommandState(bundle, {
      busy: deps.busy,
      isFocused: deps.isFocused,
      sessionFillSuppressed: deps.sessionFillSuppressed,
      viewingOffCursorNode: cursorAddr !== null && currentAddr !== cursorAddr,
      stats: deps.getStats(),
      currentAddress: currentAddr,
      cliCaretHi: deps.cliCaretHi,
      hasCliInputEl: deps.hasCliInputEl,
      captureCliCaret: deps.captureCliCaret,
      dataSources: deps.dataSources,
      onUpdate: deps.onUpdate,
      linePickDeps: {
        ...deps.linePickDeps,
        fetchNodeTree: () => deps.dataSources.fetchNodeTree(deps.onUpdate),
        getCurrentAddress: () => deps.getCurrentAddress(),
        nodeTreeCache: deps.dataSources.nodeTreeCache,
      },
    })
  }
  return bundle
}
