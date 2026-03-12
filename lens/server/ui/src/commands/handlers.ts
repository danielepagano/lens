import type { CommandContext, CommandResult, CommandHandler } from './common'
import { cliCommandHandler } from './cli'
import { transactionCommandHandler } from './transaction'

export type { CommandContext, CommandResult, CommandHandler }

export function resolveHandler(command: string): CommandHandler {
  switch (command) {
    case 'commit':
    case 'rollback':
    case 'checkpoint':
      return transactionCommandHandler
    default:
      return cliCommandHandler
  }
}
