import { cliCommandHandler } from './cli'
import type {
  CommandDefinition,
  CommandHandler,
} from './common'

export const DND_COMMANDS: CommandDefinition[] = [
  { trigger: 'play', group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'dnd',  group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
]

export const dndCommandHandler: CommandHandler = async (
  command,
  payload,
  ctx: CommandContext
) => {
  return cliCommandHandler(command, payload, ctx)
}

