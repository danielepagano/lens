import type {
  CommandContext,
  CommandDefinition,
  CommandGroup,
  CommandResult,
  CommandHandler,
} from './common'
import { cliCommandHandler, CLI_COMMANDS } from './cli'
import { transactionCommandHandler, TRANSACTION_COMMANDS } from './transaction'

export type { CommandContext, CommandResult, CommandHandler }

const GROUP_ORDER: Record<CommandGroup, number> = {
  transactions: 0,
  cli: 1,
}

const ALL_COMMAND_DEFINITIONS: CommandDefinition[] = [
  ...TRANSACTION_COMMANDS,
  ...CLI_COMMANDS,
].sort((a, b) => {
  const aOrder = GROUP_ORDER[a.group] ?? Number.MAX_SAFE_INTEGER
  const bOrder = GROUP_ORDER[b.group] ?? Number.MAX_SAFE_INTEGER
  if (aOrder !== bOrder) {
    return aOrder - bOrder
  }
  return a.trigger.localeCompare(b.trigger)
})

export const COMMAND_DEFINITIONS: readonly CommandDefinition[] =
  ALL_COMMAND_DEFINITIONS

export const KNOWN_COMMANDS: readonly string[] = ALL_COMMAND_DEFINITIONS.map(
  (c) => c.trigger
)

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
