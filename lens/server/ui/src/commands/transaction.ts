import {
  rollbackTransaction,
  commitTransaction,
  checkpointTransaction,
  refreshTransaction,
  getTxStatus,
  type TxStatusCommit,
} from '../services/api'
import { transactionResult, treeRefreshTrigger, cliOutput } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'

const commands: CommandDefinition[] = [
  { trigger: 'tx-commit', group: 'transactions', cursorTargeting: 'never' },
  { trigger: 'tx-rollback', group: 'transactions', cursorTargeting: 'never' },
  {
    trigger: 'tx-checkpoint',
    group: 'transactions',
    cursorTargeting: 'never',
    positional: [{ name: 'message', valueType: 'string', hint: '(optional message)' }],
    options: [{ name: 'no-push' }],
  },
  {
    trigger: 'tx-refresh',
    group: 'transactions',
    cursorTargeting: 'never',
    options: [{ name: 'reset' }],
  },
  { trigger: 'tx-status', group: 'transactions', cursorTargeting: 'never' },
]

function formatCommit(c: TxStatusCommit): string {
  return `  ${c.hash}  ${c.message}`
}

function formatTxStatus(status: Awaited<ReturnType<typeof getTxStatus>>): string {
  const lines: string[] = []

  if (status.pending_files.length > 0) {
    lines.push('Unstaged:')
    for (const f of status.pending_files) lines.push('  ' + f)
  } else {
    lines.push('Unstaged:  none')
  }

  lines.push('')

  if (status.staged_files.length > 0) {
    lines.push('Staged:')
    for (const f of status.staged_files) lines.push('  ' + f)
  } else {
    lines.push('Staged:    none')
  }

  lines.push('')

  if (!status.has_remote) {
    lines.push('Remote:    not configured')
  } else if (status.fetch_error) {
    lines.push('Remote:    fetch failed — ' + status.fetch_error)
  } else if (!status.has_upstream) {
    lines.push('Remote:    no upstream branch')
  } else {
    const inCount = status.incoming.length
    if (inCount > 0) {
      lines.push(`Incoming:  ${inCount} commit${inCount !== 1 ? 's' : ''} (run /tx-refresh to pull)`)
      for (const c of status.incoming) lines.push(formatCommit(c))
    } else {
      lines.push('Incoming:  none')
    }

    lines.push('')

    const upCount = status.unpushed.length
    if (upCount > 0) {
      lines.push(`Unpushed:  ${upCount} commit${upCount !== 1 ? 's' : ''}`)
      for (const c of status.unpushed) lines.push(formatCommit(c))
    } else {
      lines.push('Unpushed:  none')
    }

    if (status.remote_head) {
      lines.push('')
      lines.push('Remote:   ' + formatCommit(status.remote_head))
    }
  }

  return lines.join('\n')
}

const handler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  transactionResult.set(null)

  if (command === 'tx-status') {
    ctx.setBusyMessage('Fetching…')
    try {
      const status = await getTxStatus()
      cliOutput.set({ output: formatTxStatus(status), exitCode: 0, streaming: false })
      return { clearInput: true }
    } catch (err) {
      cliOutput.set({
        output: err instanceof Error ? err.message : String(err),
        exitCode: 1,
        streaming: false,
      })
      return { clearInput: false }
    }
  }

  try {
    let result
    switch (command) {
      case 'tx-rollback':
        result = await rollbackTransaction()
        break
      case 'tx-commit':
        result = await commitTransaction()
        break
      case 'tx-checkpoint': {
        const message = (ctx.args.positional['message'] as string | undefined) || undefined
        const noPush = ctx.args.options['no-push'] === true
        result = await checkpointTransaction({ message, push: !noPush })
        break
      }
      case 'tx-refresh': {
        const reset = ctx.args.options['reset'] === true
        result = await refreshTransaction({ reset })
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
