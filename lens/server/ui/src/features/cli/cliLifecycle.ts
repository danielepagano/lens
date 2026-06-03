import { tick } from 'svelte'
import { get } from 'svelte/store'
import type { Stats } from '../../services/api'
import { stats } from '../../stores/stats'
import { currentAddress } from '../../stores/document'
import { currentProject } from '../../stores/project'
import {
  cliInputRequest,
  linePickSelection,
  mountCacheRefreshTrigger,
  treeRefreshTrigger,
} from '../../stores/ui'
import type { CliDataSources } from './cliDataSources'
import { cliContainsOnlySessionOperator } from './cliParseHelpers'
import type { SuggestionApplyDeps } from './cliSuggestionApply'
import { replaceTokenForLinePick } from './cliSuggestionApply'
import { scheduleCliResize } from './cliInputHints'

export type CliLifecycleCtx = {
  getInput: () => string
  setInput: (value: string) => void
  dataSources: CliDataSources
  updateCommandState: () => void
  focusCliInput: () => void
  resizeCliInput: () => void
  suggestionApplyDeps: () => SuggestionApplyDeps
  getLastProject: () => string | null
  setLastProject: (project: string | null) => void
  getLastSessionOperator: () => string | null
  setLastSessionOperator: (op: string | null) => void
  setSessionFillSuppressed: (value: boolean) => void
  setLastAutoFilledCommand: (cmd: string | null) => void
  getPrevCliNavAddress: () => string | null | undefined
  setPrevCliNavAddress: (addr: string | null | undefined) => void
}

export function handleCliNavigationTracking(ctx: CliLifecycleCtx, addr: string | null, nextStats: Stats | null = get(stats)): void {
  const cursorAddr = nextStats?.cursor ?? null
  const sessionOp = nextStats?.active_session_operator
  const prevCliNavAddress = ctx.getPrevCliNavAddress()
  if (prevCliNavAddress !== undefined && cursorAddr !== null && sessionOp) {
    const leftCursor = prevCliNavAddress === cursorAddr && addr !== null && addr !== cursorAddr
    if (leftCursor && cliContainsOnlySessionOperator(ctx.getInput(), sessionOp)) {
      ctx.setInput('/')
      ctx.setSessionFillSuppressed(false)
      ctx.updateCommandState()
      scheduleCliResize(ctx.resizeCliInput)
    }
  }
  ctx.setPrevCliNavAddress(addr)
}

export function setupCliLifecycle(ctx: CliLifecycleCtx): () => void {
  const unsubs = [
    cliInputRequest.subscribe((value) => {
      if (value === null) return
      ctx.setInput(value)
      cliInputRequest.set(null)
      void tick().then(() => {
        ctx.updateCommandState()
        ctx.focusCliInput()
        ctx.resizeCliInput()
      })
    }),
    treeRefreshTrigger.subscribe(() => ctx.dataSources.resetTreeCaches()),
    mountCacheRefreshTrigger.subscribe(() => ctx.dataSources.resetMountCaches()),
    currentProject.subscribe((project) => {
      const lastProject = ctx.getLastProject()
      if (project !== lastProject) {
        if (lastProject !== null) {
          ctx.setInput('')
          ctx.setSessionFillSuppressed(false)
          ctx.setLastAutoFilledCommand(null)
          scheduleCliResize(ctx.resizeCliInput)
        }
        ctx.setLastProject(project)
      }
    }),
    stats.subscribe((nextStats) => {
      const newOp = nextStats?.active_session_operator ?? null
      if (newOp !== ctx.getLastSessionOperator()) {
        ctx.setLastSessionOperator(newOp)
        ctx.setSessionFillSuppressed(false)
        ctx.updateCommandState()
      }
      handleCliNavigationTracking(ctx, get(currentAddress), nextStats)
    }),
    currentAddress.subscribe((addr) => handleCliNavigationTracking(ctx, addr, get(stats))),
    linePickSelection.subscribe((selectedLine) => {
      if (selectedLine === null) return
      linePickSelection.set(null)
      replaceTokenForLinePick(selectedLine, ctx.suggestionApplyDeps())
    }),
  ]
  return () => {
    for (const unsub of unsubs) unsub()
  }
}
