import { CliRunBusyError, runCliStream } from '../services/api'
import { cliOutput, treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
} from './common'

export const CLI_COMMANDS: CommandDefinition[] = [
  { trigger: 'design',  group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'edit',    group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'kb',      group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'rewind',  group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'section', group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
  { trigger: 'stats',   group: 'cli', positional: [{ name: 'args', valueType: 'string' }], hint: 'args or --help' },
]

export const cliCommandHandler: CommandHandler = async (
  command,
  payload,
  ctx: CommandContext
) => {
  cliOutput.set({ output: '', exitCode: null, streaming: true })

  try {
    await runCliStream(command, payload, (event) => {
      if (event.type === 'out' || event.type === 'err') {
        cliOutput.update((p) =>
          p ? { ...p, output: p.output + (event.text ?? '') } : p
        )
      } else if (event.type === 'done') {
        cliOutput.update((p) =>
          p
            ? {
                ...p,
                exitCode: event.exit_code ?? null,
                streaming: false,
              }
            : p
        )
      }
    })
    if (ctx.onDone) {
      await ctx.onDone()
    }
    treeRefreshTrigger.update((n) => n + 1)
    return { clearInput: true }
  } catch (err) {
    if (err instanceof CliRunBusyError) {
      ctx.setBusyMessage(err.message)
      cliOutput.update((p) =>
        p
          ? { ...p, output: p.output + err.message + '\n', streaming: false }
          : p
      )
      return { clearInput: false }
    }

    cliOutput.update((p) =>
      p
        ? {
            ...p,
            output: p.output + (err instanceof Error ? err.message : String(err)),
            exitCode: 1,
            streaming: false,
          }
        : p
    )
    if (ctx.onDone) {
      await ctx.onDone()
    }
    return { clearInput: true }
  }
}
