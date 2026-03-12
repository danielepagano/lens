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
} from './common'

export const TRANSACTION_COMMANDS: CommandDefinition[] = [
  { trigger: 'commit', group: 'transactions' },
  { trigger: 'rollback', group: 'transactions' },
  { trigger: 'checkpoint', group: 'transactions' },
]

async function executeTransactionAction(
  command: string
): Promise<TransactionActionResponse> {
  switch (command) {
    case 'rollback':
      return rollbackTransaction()
    case 'commit':
      return commitTransaction()
    case 'checkpoint':
      return checkpointTransaction()
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
    const result = await executeTransactionAction(command)

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

