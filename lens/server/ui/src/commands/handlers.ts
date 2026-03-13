import type {
  CommandContext,
  CommandDefinition,
  CommandGroup,
  CommandResult,
  CommandHandler,
} from './common'
import { cliCommandHandler, CLI_COMMANDS } from './cli'
import { transactionCommandHandler, TRANSACTION_COMMANDS } from './transaction'
import { dndCommandHandler, DND_COMMANDS } from './dnd'

export type { CommandContext, CommandResult, CommandHandler }

const GROUP_ORDER: Record<CommandGroup, number> = {
  transactions: 0,
  cli: 1,
}

let ALL_COMMAND_DEFINITIONS: CommandDefinition[] = []

function buildAllCommandDefinitions(includeDnd: boolean): CommandDefinition[] {
  const base: CommandDefinition[] = [
    ...TRANSACTION_COMMANDS,
    ...CLI_COMMANDS,
  ]
  const extra: CommandDefinition[] = includeDnd ? DND_COMMANDS : []
  return [...base, ...extra].sort((a, b) => {
    const aOrder = GROUP_ORDER[a.group] ?? Number.MAX_SAFE_INTEGER
    const bOrder = GROUP_ORDER[b.group] ?? Number.MAX_SAFE_INTEGER
    if (aOrder !== bOrder) {
      return aOrder - bOrder
    }
    return a.trigger.localeCompare(b.trigger)
  })
}

ALL_COMMAND_DEFINITIONS = buildAllCommandDefinitions(false)

export let COMMAND_DEFINITIONS: readonly CommandDefinition[] =
  ALL_COMMAND_DEFINITIONS

export let KNOWN_COMMANDS: readonly string[] = ALL_COMMAND_DEFINITIONS.map(
  (c) => c.trigger
)

export function updateDatasetCommands(currentDatasets: string[] | null): void {
  const hasDnd = Array.isArray(currentDatasets)
    ? currentDatasets.includes('dnd')
    : false
  ALL_COMMAND_DEFINITIONS = buildAllCommandDefinitions(hasDnd)
  COMMAND_DEFINITIONS = ALL_COMMAND_DEFINITIONS
  KNOWN_COMMANDS = ALL_COMMAND_DEFINITIONS.map((c) => c.trigger)
}

export function resolveHandler(command: string): CommandHandler {
  switch (command) {
    case 'play':
    case 'balance':
      return dndCommandHandler
    case 'commit':
    case 'rollback':
    case 'checkpoint':
      return transactionCommandHandler
    default:
      return cliCommandHandler
  }
}
