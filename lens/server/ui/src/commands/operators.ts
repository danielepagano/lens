import { runWrite, runEdit, runPlay, StreamBusyError, type OperatorEvent } from '../services/api'
import { cliOutput, treeRefreshTrigger } from '../stores/ui'
import { streamingPreview } from '../stores/document'
import type {
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { normalizeAddress } from './common'

function scrollContentToBottom(): void {
  const content = document.querySelector('[data-testid="markdown-view"]')
  if (content) {
    content.scrollTop = content.scrollHeight
  }
}

function scrollPreviewIntoView(): void {
  const preview = document.querySelector('[data-testid="streaming-preview"]')
  if (preview) {
    preview.scrollIntoView({ block: 'end', behavior: 'instant' })
  }
}

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
    trigger: 'play',
    group: 'dnd',
    requiresDataset: 'dnd',
    positional: [{ name: 'prompt', valueType: 'string', required: true, hint: 'what do you do?' }],
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
  if (!commands.map(c => c.trigger).includes(command)) {
    throw new Error(`Unsupported operator command: ${command}`)
  }

  const prompt = (ctx.args.positional['prompt'] as string | undefined) || undefined

  const pins = (ctx.args.options['pin'] as string[] | undefined) ?? []
  const unpins = (ctx.args.options['unpin'] as string[] | undefined) ?? []
  const llmId = (ctx.args.options['llm'] as string | undefined) || undefined
  const as_pc = (ctx.args.options['as_pc'] as string | undefined) || undefined
  const retry = ctx.args.options['retry'] === true

  let errorOutput = ''

  const handleEvent = (event: OperatorEvent): void => {
    if (event.type === 'error') {
      errorOutput += event.message
    } else if (event.type === 'token') {
      streamingPreview.update((prev) => {
        if (prev && prev.targetNode === event.node) {
          return { ...prev, text: prev.text + event.text }
        }
        return { targetNode: event.node, text: event.text }
      })
      requestAnimationFrame(scrollPreviewIntoView)
    }
  }

  // Scroll to bottom when starting the command
  scrollContentToBottom()

  // Show waiting state immediately (before first token arrives)
  streamingPreview.set({ targetNode: '', text: '' })

  try {
    let result

    if (command === 'write') {
      result = await runWrite(
        { prompt, pins, unpins, llm_id: llmId, retry },
        handleEvent
      )
    } if (command === 'play') {
      if (prompt === undefined) {
        throw new Error(`Play requires a prompt`)
      }
      result = await runPlay(
        { prompt, pins, unpins, llm_id: llmId, retry, as_pc },
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

    // Clear streaming preview before refreshing
    streamingPreview.set(null)

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
    // Clear streaming preview on error
    streamingPreview.set(null)

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

const PLAY_REQUIRED_PINS = ['rules.dnd', 'rules.engagement'] as const

export const operatorModule: CommandModule = { 
  commands: (stats) => {
    const result: CommandDefinition[] = []
    
    for (const cmd of commands) {
      // Dataset check
      if (cmd.requiresDataset != null && !stats.current_datasets?.includes(cmd.requiresDataset)) {
        continue
      }
      
      // Special handling for play: requires rules + at least one PC pinned
      if (cmd.trigger === 'play') {
        const pins = stats.effective_pins_at_cursor ?? []
        const hasRequiredRules = PLAY_REQUIRED_PINS.every(r => pins.includes(r))
        const pcPins = pins.filter(p => p.startsWith('pc.'))
        
        if (!hasRequiredRules || pcPins.length === 0) {
          continue
        }
        
        // If more than one PC, add as_pc option with PC keys as slugSource
        if (pcPins.length > 1) {
          const pcKeys = pcPins.map(p => p.slice(3)).join(',')
          result.push({
            ...cmd,
            options: [
              { name: 'as_pc', valueType: 'slug', hint: 'acting as', slugSource: pcKeys },
              ...(cmd.options ?? [])
            ]
          })
          continue
        }
      }
      
      result.push(cmd)
    }
    
    return result
  }, 
  handler 
}
