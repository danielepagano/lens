import { narrativePin, narrativeRewind, type PinOperation } from '../services/api'
import {
  treeRefreshTrigger,
  transactionResult,
  scrollContentToBottom,
  scrollCodeMirrorToBottom,
} from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { normalizeAddress } from './common'

const PIN_OPERATIONS: PinOperation[] = ['add', 'remove', 'block', 'unblock']

const commands: CommandDefinition[] = [
  {
    trigger: 'pin',
    group: 'narrative',
    cursorTargeting: 'can-override',
    positional: [
      { name: 'action', valueType: 'slug', required: true, slugSource: 'add,remove,block,unblock' },
      { name: 'ids', valueType: 'kb-id', required: true, repeatable: true, hint: 'KB object ID' },
    ],
    options: [
      { name: 'node', valueType: 'address', hint: 'narrative address' },
    ],
  },
  {
    trigger: 'structure-rewind',
    group: 'structure',
    cursorTargeting: 'never',
    positional: [
      { name: 'address', valueType: 'address', required: true, hint: 'node address' },
      { name: 'line', valueType: 'line', required: false, hint: 'line number' },
    ],
  },
]

const handler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)

  if (command === 'structure-rewind') {
    const rawAddress = ctx.args.positional['address'] as string | undefined
    const address = normalizeAddress(rawAddress)
    const lineRaw = ctx.args.positional['line'] as string | undefined
    const parsedLine = lineRaw !== undefined && lineRaw !== '' ? parseInt(lineRaw, 10) : NaN
    const line = Number.isInteger(parsedLine) ? parsedLine : undefined
    if (!address) {
      return { clearInput: false }
    }
    try {
      const result = await narrativeRewind({ address, line })
      if (result.status === 'ok') {
        if (ctx.onDone) await ctx.onDone()
        treeRefreshTrigger.update((n) => n + 1)
        scrollContentToBottom.update((n) => n + 1)
        scrollCodeMirrorToBottom.update((n) => n + 1)
        return { clearInput: true }
      }
      transactionResult.set({
        title: 'Rewind error',
        message: result.detail ?? 'Unknown error',
      })
      return { clearInput: false }
    } catch (err) {
      transactionResult.set({
        title: 'Rewind error',
        message: err instanceof Error ? err.message : String(err),
      })
      return { clearInput: false }
    }
  }

  const operation = ctx.args.positional['action'] as string | undefined
  const ids = ctx.args.positional['ids'] as string[] | undefined
  const node = normalizeAddress(ctx.args.options['node'] as string | undefined)

  if (!operation || !PIN_OPERATIONS.includes(operation as PinOperation) || !ids || ids.length === 0) {
    return { clearInput: false }
  }

  try {
    const result = await narrativePin(operation as PinOperation, ids, node)
    if (result.status === 'ok') {
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      return { clearInput: true }
    }
    transactionResult.set({
      title: 'Pin error',
      message: result.detail ?? 'Unknown error',
    })
    return { clearInput: false }
  } catch (err) {
    transactionResult.set({
      title: 'Pin error',
      message: err instanceof Error ? err.message : String(err),
    })
    return { clearInput: false }
  }
}

export const narrativeModule: CommandModule = { commands: () => commands, handler }
