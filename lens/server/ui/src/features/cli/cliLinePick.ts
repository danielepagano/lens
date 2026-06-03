import type { CommandDefinition } from '../../commands/common'
import type { ParseState } from '../../commands/parser'
import type { LinePickState } from '../../stores/ui'
import { promptNodeMentionLinePickAtCaret } from '../../utils/cliCaret'
import { displayAddrToNavAddr } from './cliAddress'

export type LinePickDeps = {
  setLinePickMode: (mode: LinePickState | null) => void
  setLinePickSelection: (line: number | null) => void
  navigate: ((addr: string) => Promise<void>) | undefined
  fetchNodeTree: () => void
  getCurrentAddress: () => string | null
  nodeTreeCache: import('../../services/api').TreeNode[] | null
}

/** Returns true when updateCommandState should return early (completed @mention range). */
export function applyLinePickFromCommandState(
  state: ParseState,
  activeCommandDef: CommandDefinition | null,
  input: string,
  cliCaretHi: number,
  deps: LinePickDeps,
): boolean {
  const activeType = state.activePayload?.valueType
  const displayToNav = (displayAddr: string) =>
    displayAddrToNavAddr(displayAddr, deps.nodeTreeCache)

  if (activeType === 'line' && activeCommandDef) {
    const addrPos = activeCommandDef.positional?.find((payload) => payload.valueType === 'address')
    const displayAddr = addrPos
      ? (state.completedPositional[addrPos.name] as string | undefined)
      : undefined
    if (displayAddr) {
      deps.fetchNodeTree()
      const navAddr = displayToNav(displayAddr)
      if (navAddr) {
        const payloadName = state.activePayload?.name
        const isEndPick = payloadName === 'end'
        const startVal = isEndPick
          ? parseInt(state.completedPositional['start'] as string, 10)
          : undefined
        const trigger = activeCommandDef.trigger
        const mediaAttach =
          trigger === 'media' &&
          (state.completedPositional['action'] as string | undefined) === 'attach'
        const operatorMode: 'edit' | 'attach' | undefined =
          trigger === 'edit' ? 'edit' : mediaAttach ? 'attach' : undefined

        deps.setLinePickMode({
          address: navAddr,
          startLine: isEndPick && startVal && !isNaN(startVal) ? startVal : undefined,
          operatorMode,
        })
        if (navAddr !== deps.getCurrentAddress()) void deps.navigate?.(navAddr)
      }
    } else {
      deps.setLinePickMode(null)
      deps.setLinePickSelection(null)
    }
    return false
  }

  if (activeType === 'prompt' || activeType === 'string') {
    const mentionPick = promptNodeMentionLinePickAtCaret(input, cliCaretHi)
    if (mentionPick) {
      if (mentionPick.endLine !== undefined) {
        deps.setLinePickMode(null)
        deps.setLinePickSelection(null)
        return true
      }
      deps.fetchNodeTree()
      const navAddr = displayToNav(mentionPick.address)
      if (navAddr) {
        deps.setLinePickMode({
          address: navAddr,
          startLine: mentionPick.startLine,
          operatorMode: undefined,
        })
        if (navAddr !== deps.getCurrentAddress()) void deps.navigate?.(navAddr)
      }
    } else {
      deps.setLinePickMode(null)
      deps.setLinePickSelection(null)
    }
    return false
  }

  deps.setLinePickMode(null)
  deps.setLinePickSelection(null)
  return false
}
