import { runWrite, runEdit, StreamBusyError, type OperatorEvent } from '../services/api'
import { cliOutput, treeRefreshTrigger } from '../stores/ui'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { normalizeAddress } from './common'

const commands: CommandDefinition[] = [
  {
    trigger: 'write',
    group: 'narrative',
    positional: [{ name: 'prompt', valueType: 'string', hint: 'prompt text' }],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: "LLM to use" },
      { name: 'retry' },
    ],
  },
  {
    trigger: 'edit',
    group: 'narrative',
    positional: [
      { name: 'address', valueType: 'address', required: true, hint: "node to edit" },
      { name: 'start', valueType: 'int', required: true, hint: 'start line number' },
      { name: 'end', valueType: 'int', required: true, hint: 'end line number' },
      { name: 'prompt', valueType: 'string', required: false, hint: "prompt or text to --replace" },
    ],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]' },
      { name: 'retry', hint: "retry previous edit in given location" },
      { name: 'replace', hint: "don't use AI, replace text with prompt directly" },
    ],
  },
]

const handler: CommandHandler = async (
  command,
  _payload,
  ctx: CommandContext
) => {
  if (command !== 'write' && command !== 'edit') {
    throw new Error(`Unsupported operator command: ${command}`)
  }

  const prompt = (ctx.args.positional['prompt'] as string | undefined) || undefined
  const pins = (ctx.args.options['pin'] as string[] | undefined) ?? []
  const unpins = (ctx.args.options['unpin'] as string[] | undefined) ?? []
  const llmId = (ctx.args.options['llm'] as string | undefined) || undefined
  const retry = ctx.args.options['retry'] === true

  let errorOutput = ''

  const handleEvent = (event: OperatorEvent): void => {
    if (event.type === 'error') {
      errorOutput += event.message
    }
  }

  try {
    let result

    if (command === 'write') {
      result = await runWrite(
        { prompt, pins, unpins, llm_id: llmId, retry },
        handleEvent
      )
    } else {
      const address = normalizeAddress(ctx.args.positional['address'] as string)
      const startLine = parseInt(ctx.args.positional['start'] as string, 10)
      const endLine = parseInt(ctx.args.positional['end'] as string, 10)
      const replace = ctx.args.options['replace'] === true

      result = await runEdit(
        {
          address: address!,
          start_line: startLine,
          end_line: endLine,
          prompt,
          pins,
          unpins,
          llm_id: llmId,
          retry,
          replace,
        },
        handleEvent
      )
    }

    if (ctx.onDone) await ctx.onDone()
    treeRefreshTrigger.update((n) => n + 1)

    if (result.type === 'error' || errorOutput) {
      cliOutput.set({
        output: errorOutput || (result.type === 'error' ? result.message : ''),
        exitCode: 1,
        streaming: false,
      })
      return { clearInput: false }
    }

    cliOutput.set(null)
    return { clearInput: !result.interrupted }
  } catch (err) {
    if (err instanceof StreamBusyError) {
      ctx.setBusyMessage(err.message)
      return { clearInput: false }
    }

    cliOutput.set({
      output: err instanceof Error ? err.message : String(err),
      exitCode: 1,
      streaming: false,
    })
    if (ctx.onDone) await ctx.onDone()
    return { clearInput: false }
  }
}

export const operatorModule: CommandModule = { commands: () => commands, handler }
