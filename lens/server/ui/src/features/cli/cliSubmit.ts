import { get } from 'svelte/store'
import type { CommandContext, CommandResult } from '../../commands/common'
import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../../commands/handlers'
import { parseCliInput, buildArgs } from '../../commands/parser'
import { stats } from '../../stores/stats'
import { currentProject } from '../../stores/project'
import { currentAddress } from '../../stores/document'
import { parsedHash } from '../../stores/parsedHash'
import { vnModeFromParsed, vnPlayback, vnCursorCliOpSnapshot } from '../../stores/visualNovel'
import { resolveVisualNovelIndex } from '../../utils/vnNavigate'
import { playbackTailTextId } from '../../utils/vnCursorCli'
import { vnNavigableIndices } from '../../utils/vnPlaybackNav'
import {
  cliHistory,
  cliHistoryIndex,
  cliOutput,
  linePickMode,
  linePickSelection,
  scrollContentToBottom,
  transactionResult,
} from '../../stores/ui'
import { GO_CURSOR_CHIP, MAX_CLI_HISTORY, parseCommandAndPayload } from './cliParseHelpers'

export type CliSubmitDeps = {
  getInput: () => string
  setInput: (value: string) => void
  setBusy: (busy: boolean) => void
  setBusyMessage: (message: string | null) => void
  setFlashInvalid: (value: boolean) => void
  setShowInvalid: (value: boolean) => void
  setSessionFillSuppressed: (value: boolean) => void
  updateCommandState: () => void
  focusCliInput: () => void
  getCliInputEl: () => HTMLTextAreaElement | null
  navigate: ((addr: string) => Promise<void>) | undefined
  onCliDone: (() => Promise<void>) | undefined
  syncLocation: ((addr: string) => void) | undefined
  afterTick: () => Promise<void>
}

function pushHistory(command: string): void {
  if (!command) return
  cliHistory.update((history) => [...history, command].slice(-MAX_CLI_HISTORY))
  cliHistoryIndex.set(-1)
}

function flashInvalidInput(deps: CliSubmitDeps): void {
  deps.setFlashInvalid(true)
  deps.setShowInvalid(true)
  setTimeout(() => deps.setFlashInvalid(false), 150)
  deps.focusCliInput()
}

export async function submitCliCommand(deps: CliSubmitDeps): Promise<void> {
  const raw = deps.getInput().trim()
  if (raw === '') {
    if (typeof window !== 'undefined' && 'ontouchstart' in window) deps.getCliInputEl()?.blur()
    return
  }

  const { command, payload } = parseCommandAndPayload(raw)
  if (!command) return

  if (command === GO_CURSOR_CHIP) {
    if (payload.trim() !== '') {
      flashInvalidInput(deps)
      return
    }
    const cursor = get(stats)?.cursor
    if (!cursor || !deps.navigate) {
      flashInvalidInput(deps)
      return
    }
    pushHistory(raw)
    try {
      await deps.navigate(cursor)
      scrollContentToBottom.update((count) => count + 1)
      deps.setInput('')
      deps.setSessionFillSuppressed(false)
      deps.updateCommandState()
    } catch (error) {
      console.error('Navigation failed:', error)
    }
    await deps.afterTick()
    deps.focusCliInput()
    return
  }

  if (!KNOWN_COMMANDS.includes(command)) {
    flashInvalidInput(deps)
    return
  }

  pushHistory(raw)
  deps.setBusy(true)
  deps.setBusyMessage(null)
  linePickMode.set(null)
  linePickSelection.set(null)
  cliOutput.set(null)
  transactionResult.set(null)

  const slug = get(currentProject)
  const addr = get(currentAddress)
  if (slug && addr && (command === 'play' || command === 'chat')) {
    const ph = get(parsedHash)
    const items = get(vnPlayback)?.items ?? []
    if (
      vnModeFromParsed(ph, slug, addr) &&
      items.length > 0 &&
      resolveVisualNovelIndex(ph, slug, addr) === vnNavigableIndices(items).length
    ) {
      vnCursorCliOpSnapshot.set({
        address: addr,
        itemCount: items.length,
        lastTextId: playbackTailTextId(items),
      })
    }
  }

  const handler = resolveHandler(command)
  const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === command) ?? null
  const state = parseCliInput(raw, definition)
  const args = buildArgs(state, definition)
  const ctx: CommandContext = {
    setBusyMessage: deps.setBusyMessage,
    onDone: deps.onCliDone,
    navigate: deps.navigate,
    syncLocation: deps.syncLocation,
    args,
  }

  try {
    const result: CommandResult = await handler(command, payload, ctx)
    if (result.clearInput) {
      deps.setInput('')
      deps.setSessionFillSuppressed(false)
      deps.updateCommandState()
    }
  } finally {
    deps.setBusy(false)
    deps.setBusyMessage(null)
    await deps.afterTick()
    deps.focusCliInput()
  }
}
