import { runWrite, StreamBusyError, type OperatorEvent } from '../services/api'
import { cliOutput, treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
} from './common'

export const OPERATOR_COMMANDS: CommandDefinition[] = [
  {
    trigger: 'write',
    group: 'narrative',
    positional: [{ name: 'prompt', valueType: 'string', hint: 'prompt text' }],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]' },
      { name: 'retry' },
    ],
  },
]

export const operatorCommandHandler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  if (command !== 'write') {
    throw new Error(`Unsupported operator command: ${command}`)
  }

  const prompt = (ctx.args.positional['prompt'] as string | undefined) || undefined
  const pins = (ctx.args.options['pin'] as string[] | undefined) ?? []
  const unpins = (ctx.args.options['unpin'] as string[] | undefined) ?? []
  const llmId = (ctx.args.options['llm'] as string | undefined) || undefined
  const retry = ctx.args.options['retry'] === true

  cliOutput.set({ output: '', exitCode: null, streaming: true })

  try {
    const result = await runWrite(
      { prompt, pins, unpins, llm_id: llmId, retry },
      (event: OperatorEvent) => {
        if (event.type === 'token') {
          cliOutput.update((p) =>
            p ? { ...p, output: p.output + event.text } : p
          )
        } else if (event.type === 'done') {
          cliOutput.update((p) =>
            p ? { ...p, exitCode: event.interrupted ? 1 : 0, streaming: false } : p
          )
        } else if (event.type === 'error') {
          cliOutput.update((p) =>
            p ? { ...p, output: p.output + event.message, exitCode: 1, streaming: false } : p
          )
        }
      }
    )

    if (ctx.onDone) await ctx.onDone()
    treeRefreshTrigger.update((n) => n + 1)
    return { clearInput: result.type === 'done' && !result.interrupted }
  } catch (err) {
    if (err instanceof StreamBusyError) {
      ctx.setBusyMessage(err.message)
      cliOutput.update((p) =>
        p ? { ...p, output: p.output + err.message + '\n', streaming: false } : p
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
    if (ctx.onDone) await ctx.onDone()
    return { clearInput: true }
  }
}
