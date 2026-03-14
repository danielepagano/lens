import {
  rollbackTransaction,
  commitTransaction,
  checkpointTransaction,
} from '../services/api'
import { transactionResult, treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'

const commands: CommandDefinition[] = [
  { trigger: 'commit', group: 'transactions' },
  { trigger: 'rollback', group: 'transactions' },
  {
    trigger: 'checkpoint',
    group: 'transactions',
    positional: [{ name: 'message', valueType: 'string', hint: '(optional message)' }],
    options: [{ name: 'no-push' }],
  },
]

const handler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)

  try {
    let result
    switch (command) {
      case 'rollback':
        result = await rollbackTransaction()
        break
      case 'commit':
        result = await commitTransaction()
        break
      case 'checkpoint': {
        const message = (ctx.args.positional['message'] as string | undefined) || undefined
        const noPush = ctx.args.options['no-push'] === true
        result = await checkpointTransaction({ message, push: !noPush })
        break
      }
      default:
        throw new Error(`Unsupported transaction command: ${command}`)
    }

    if (result.status === 'ok') {
      if (ctx.onDone) await ctx.onDone()
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

export const transactionModule: CommandModule = { commands: () => commands, handler }
