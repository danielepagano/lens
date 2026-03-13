import { narrativePin, type PinOperation } from '../services/api'
import { treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
} from './common'

const PIN_OPERATIONS: PinOperation[] = ['add', 'remove', 'block', 'unblock']

export const NARRATIVE_COMMANDS: CommandDefinition[] = [
  {
    trigger: 'pin',
    group: 'narrative',
    params: { kind: 'none' },
    subOptions: PIN_OPERATIONS.map((v) => ({ value: v })),
    payloadHint: 'KB object IDs',
  },
]

export const narrativeCommandHandler: CommandHandler = async (
  _command,
  payload,
  ctx: CommandContext
) => {
  const parts = payload.trim().split(/\s+/).filter(Boolean)
  const operation = parts[0] as PinOperation | undefined
  const ids = parts.slice(1)

  if (!operation || !PIN_OPERATIONS.includes(operation) || ids.length === 0) {
    return { clearInput: false }
  }

  try {
    const result = await narrativePin(operation, ids)
    if (result.status === 'ok') {
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      return { clearInput: true }
    }
    return { clearInput: false }
  } catch {
    return { clearInput: false }
  }
}
