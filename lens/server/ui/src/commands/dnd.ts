import { CliRunBusyError, runCliStream } from '../services/api'
import { cliOutput, treeRefreshTrigger } from '../stores/ui'
import { cliCommandHandler } from './cli'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
} from './common'

const DND_HINT = 'args or --help'

export const DND_COMMANDS: CommandDefinition[] = [
  { trigger: 'play', group: 'cli', params: { kind: 'form', schema: {
    hint: DND_HINT,
    fields: [{ kind: 'string', name: 'args', optional: true }],
  } } },
  { trigger: 'dnd', group: 'cli', params: { kind: 'form', schema: {
    hint: DND_HINT,
    fields: [{ kind: 'string', name: 'args', optional: true }],
  } } },
]

export const dndCommandHandler: CommandHandler = async (
  command,
  payload,
  ctx: CommandContext
) => {
  return cliCommandHandler(command, payload, ctx)
}

