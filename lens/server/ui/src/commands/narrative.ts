import { narrativePin, type PinOperation } from '../services/api'
import { treeRefreshTrigger, transactionResult } from '../stores/ui'
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
    positional: [
      { name: 'action', valueType: 'slug', required: true, slugSource: 'add,remove,block,unblock' },
      { name: 'ids', valueType: 'kb-id', required: true, repeatable: true, hint: 'KB object ID' },
    ],
    options: [
      { name: 'node', valueType: 'address', hint: 'narrative address' },
    ],
  },
]

export const narrativeCommandHandler: CommandHandler = async (
  _command,
  _payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)

  const operation = ctx.args.positional['action'] as string | undefined
  const ids = ctx.args.positional['ids'] as string[] | undefined
  const rawNode = ctx.args.options['node'] as string | undefined
  const normalizedNode = rawNode?.replace(/\/+$/, '') // trim trailing slashes
  const node = normalizedNode ? (normalizedNode.startsWith('/') ? normalizedNode : '/' + normalizedNode) : undefined

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
