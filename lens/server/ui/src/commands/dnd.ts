import { cliCommandHandler } from './cli'
import type {
  CommandContext,
  CommandDefinition,
  CommandModule,
} from './common'

const commands: CommandDefinition[] = [
  { trigger: 'play', group: 'dnd', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'dnd',  group: 'dnd', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
]

export const dndModule: CommandModule = {
  commands: (datasets) => datasets?.includes('dnd') ? commands : [],
  handler: (command, payload, ctx: CommandContext) => cliCommandHandler(command, payload, ctx),
}

