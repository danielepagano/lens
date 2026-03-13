import {
  rollbackTransaction,
  commitTransaction,
  checkpointTransaction,
  type TransactionActionResponse,
} from '../services/api'
import { transactionResult, treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  ResolvedParams,
} from './common'

export const TRANSACTION_COMMANDS: CommandDefinition[] = [
  { trigger: 'commit', group: 'transactions', params: { kind: 'none' } },
  { trigger: 'rollback', group: 'transactions', params: { kind: 'none' } },
  {
    trigger: 'checkpoint',
    group: 'transactions',
    params: {
      kind: 'form',
      schema: {
        hint: '[commit message]',
        fields: [
          { kind: 'string', name: 'message', hint: 'Commit message', optional: true },
          { kind: 'bool', name: 'push', label: 'Push to remote', default: true },
        ],
      },
    },
  },
]

async function executeTransactionAction(
  command: string,
  resolvedParams?: ResolvedParams
): Promise<TransactionActionResponse> {
  switch (command) {
    case 'rollback':
      return rollbackTransaction()
    case 'commit':
      return commitTransaction()
    case 'checkpoint':
      return checkpointTransaction({
        message: (resolvedParams?.['message'] as string | undefined) || undefined,
        push: resolvedParams?.['push'] !== undefined
          ? (resolvedParams['push'] as boolean)
          : true,
      })
    default:
      throw new Error(`Unsupported transaction command: ${command}`)
  }
}

export const transactionCommandHandler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)

  try {
    const result = await executeTransactionAction(command, ctx.resolvedParams)

    if (result.status === 'ok') {
      if (ctx.onDone) {
        await ctx.onDone()
      }
      treeRefreshTrigger.update((n) => n + 1)
      return { clearInput: true }
    }

    transactionResult.set({
      title: 'Transaction error',
      message: result.detail ?? 'Unknown transaction error',
    })
    return { clearInput: false }
  } catch (err) {
    transactionResult.set({
      title: 'Transaction error',
      message: err instanceof Error ? err.message : String(err),
    })
    return { clearInput: false }
  }
}
