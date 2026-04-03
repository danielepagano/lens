import { get } from 'svelte/store'
import { runWrite, runWriteManual, runEdit, runPlay, runDesign, runAdvance, runSectionStart, runSectionEnd, runCollate, renameNode, StreamBusyError, type OperatorEvent, type OperatorProgressEvent, type Stats } from '../services/api'
import { cliOutput, treeRefreshTrigger, inlineEditMode, inlineEditResult, type InlineEditState } from '../stores/ui'
import { streamingPreview, currentAddress, nodeContent } from '../stores/document'
import type {
  CliPayload,
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { normalizeAddress, addressToNavAddress } from './common'
import { stats } from '../stores/stats'

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

function progressLabel(event: OperatorProgressEvent): string {
  if (event.message) return event.message
  switch (event.phase) {
    case 'operator_started':
      return event.operator ? `Starting ${event.operator}…` : 'Starting…'
    case 'llm_configured':
      return 'Preparing LLM…'
    case 'llm_round':
      return 'Calling model…'
    case 'http_request':
      return 'Connecting to API…'
    case 'http_stream_open':
      return 'Receiving response…'
    case 'http_stream_closed':
      return 'Finishing…'
    default:
      return 'Working…'
  }
}

function optionsWithLlmIfMultiple(
  options: CliPayload[] | undefined,
  stats: Stats
): CliPayload[] {
  const manyLlms = (stats.available_llms?.length ?? 0) > 1
  const list = options ?? []
  if (manyLlms) return [...list]
  return list.filter((o) => o.name !== 'llm')
}

const commands: CommandDefinition[] = [
  {
    trigger: 'write',
    group: 'narrative',
    cursorTargeting: 'always',
    positional: [{ name: 'prompt', valueType: 'prompt', hint: 'prompt text' }],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: "LLM to use" },
      { name: 'retry' },
      { name: 'manual', hint: 'append text directly without AI' },
    ],
  },
  {
    trigger: 'design',
    group: 'narrative',
    cursorTargeting: 'always',
    positional: [
      { name: 'prompt', valueType: 'prompt', hint: 'design prompt' },
    ],
    options: [
      { name: 'module', valueType: 'kb-id', repeatable: false, hint: 'design module to use', default: 'design.' },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'retry' },
      { name: 'end' },
      { name: 'slug', valueType: 'slug', hint: 'sub-node id (default: auto-generated)' },
    ],
  },
  {
    trigger: 'play',
    group: 'rpg',
    requiresDataset: 'rpg',
    cursorTargeting: 'always',
    positional: [{ name: 'prompt', valueType: 'prompt', hint: 'what do you do?' }],
    options: [
      { name: 'module', valueType: 'kb-id', repeatable: false, hint: 'rules module to use', default: 'rules.', exclude: ['rules.system', 'rules.rpg'] },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: "LLM to use" },
      { name: 'retry' },
      { name: 'end' },
      { name: 'pass', hint: 'have the GM respond now' },
      { name: 'slug', valueType: 'slug', hint: 'sub-node id (default: auto-generated)' },
    ],
  },
  {
    trigger: 'advance',
    group: 'rpg',
    requiresDataset: 'rpg',
    cursorTargeting: 'always',
    positional: [],
    options: [
      { name: 'days', valueType: 'int', hint: 'days to advance (default: 1)' },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'retry' },
      { name: 'end' },
    ],
  },
  {
    trigger: 'edit',
    group: 'narrative',
    cursorTargeting: 'never',
    positional: [
      { name: 'address', valueType: 'address', required: true, hint: "node to edit" },
      { name: 'start', valueType: 'line', required: true, hint: 'start line number' },
      { name: 'end', valueType: 'line', required: true, hint: 'end line number' },
      { name: 'prompt', valueType: 'prompt', required: false, hint: "prompt or text to --replace" },
    ],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]' },
      { name: 'retry', hint: "retry previous edit in given location" },
      { name: 'replace', hint: "don't use AI, replace text with prompt directly" },
    ],
  },
  {
    trigger: 'structure-section',
    group: 'structure',
    cursorTargeting: 'always',
    positional: [{ name: 'id', valueType: 'slug', required: false, hint: 'section ID to start (or use --end to close)' }],
    options: [
      { name: 'end', hint: 'close the current section' },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM for summary (when ending)' },
    ],
  },
  {
    trigger: 'structure-collate',
    group: 'structure',
    cursorTargeting: 'never',
    positional: [
      { name: 'id', valueType: 'slug', required: true, hint: 'section ID for the new child' },
      { name: 'address', valueType: 'address', required: true, hint: 'node address to section' },
      { name: 'start', valueType: 'line', required: true, hint: 'start line' },
      { name: 'end', valueType: 'line', required: true, hint: 'end line' },
    ],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true },
      { name: 'unpin', valueType: 'kb-id', repeatable: true },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]' },
    ],
  },
  {
    trigger: 'structure-rename',
    group: 'structure',
    cursorTargeting: 'never',
    positional: [
      { name: 'address', valueType: 'address', required: true, hint: 'node to rename (e.g. /chapter-1/design-old)' },
      { name: 'new_slug', valueType: 'slug', required: true, hint: 'new slug' },
    ],
    options: [],
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
  const as_pc = (ctx.args.options['as'] as string | undefined) || undefined
  const retry = ctx.args.options['retry'] === true

  const isManual = ctx.args.options['manual'] === true

  // write --manual with no prompt text: open inline append editor
  if (command === 'write' && isManual && !prompt) {
    const cursor = get(stats)?.cursor
    if (!cursor) {
      cliOutput.set({ output: 'No cursor position', exitCode: 1, streaming: false })
      return { clearInput: false }
    }
    streamingPreview.set(null)
    if (ctx.navigate) {
      await ctx.navigate(cursor)
    }
    // Pad the current content with one blank line so the user has an editable line at the end.
    const rawContent = get(nodeContent)
    const paddedContent = rawContent.endsWith('\n') ? rawContent + '\n' : rawContent + '\n\n'
    const appendLine = paddedContent.split('\n').length
    inlineEditResult.set(null)
    const editState: InlineEditState = {
      address: cursor,
      startLine: appendLine,
      endLine: appendLine,
      originalText: '',
      linesAfterSelection: 0,
      appendMode: true,
    }
    inlineEditMode.set(editState)

    const editedText = await new Promise<string | null>((resolve) => {
      const unsubResult = inlineEditResult.subscribe((val) => {
        if (val !== null) {
          unsubResult()
          unsubMode()
          resolve(val)
        }
      })
      const unsubMode = inlineEditMode.subscribe((val) => {
        if (val === null) {
          unsubResult()
          unsubMode()
          resolve(get(inlineEditResult))
        }
      })
    })

    if (editedText === null) {
      return { clearInput: false }
    }

    try {
      await runWriteManual({ text: editedText })
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      cliOutput.set(null)
      return { clearInput: true }
    } catch (err) {
      cliOutput.set({
        output: err instanceof Error ? err.message : String(err),
        exitCode: 1,
        streaming: false,
      })
      if (ctx.onDone) await ctx.onDone()
      return { clearInput: false }
    }
  }

  // write --manual SOME TEXT: append directly without opening editor
  if (command === 'write' && isManual && prompt) {
    try {
      await runWriteManual({ text: prompt })
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      cliOutput.set(null)
      return { clearInput: true }
    } catch (err) {
      cliOutput.set({
        output: err instanceof Error ? err.message : String(err),
        exitCode: 1,
        streaming: false,
      })
      if (ctx.onDone) await ctx.onDone()
      return { clearInput: false }
    }
  }

  let errorOutput = ''

  const handleEvent = (event: OperatorEvent): void => {
    if (event.type === 'error') {
      errorOutput += event.message
    } else if (event.type === 'target') {
      const current = get(currentAddress)
      if (current !== event.node) {
        // Set immediately so isStreamingToCurrentNode becomes true right away,
        // then load node content in the background.
        currentAddress.set(event.node)
        ctx.navigate?.(event.node)
        // Refresh tree so newly created nodes (e.g. design sub-nodes) appear.
        treeRefreshTrigger.update((n) => n + 1)
      }
      streamingPreview.update((prev) => ({
        targetNode: event.node,
        text: prev?.text ?? '',
      }))
    } else if (event.type === 'token') {
      streamingPreview.update((prev) => {
        if (prev) return { ...prev, text: prev.text + event.text, statusLine: undefined }
        return { targetNode: '', text: event.text }
      })
      requestAnimationFrame(scrollPreviewIntoView)
    } else if (event.type === 'progress') {
      const label = progressLabel(event)
      streamingPreview.update((prev) => {
        if (prev) return { ...prev, statusLine: label }
        return { targetNode: '', text: '', statusLine: label }
      })
    }
  }

  // Scroll to bottom when starting the command
  scrollContentToBottom()

  // Show waiting state immediately (before first token arrives)
  streamingPreview.set({ targetNode: '', text: '' })

  try {
    let result: { type: string; message?: string; interrupted?: boolean } | { status: string; node: string }

    if (command === 'write') {
      result = await runWrite(
        { prompt, pins, unpins, llm_id: llmId, retry },
        handleEvent
      )
    } else if (command === 'play') {
      const endPlay = ctx.args.options['end'] === true
      const passPlay = ctx.args.options['pass'] === true
      if (passPlay && retry) {
        throw new Error('Play --pass cannot be combined with --retry')
      }
      if (!endPlay && !retry && !passPlay && prompt === undefined) {
        throw new Error(`Play requires a prompt (unless using --end, --retry, or --pass)`)
      }
      const rawPlayModule = (ctx.args.options['module'] as string | undefined) || undefined
      let playModuleId: string | undefined
      if (!endPlay && rawPlayModule) {
        if (!rawPlayModule.startsWith('rules.')) {
          throw new Error(`Play module must start with 'rules.': ${rawPlayModule}`)
        }
        playModuleId = rawPlayModule.slice('rules.'.length)
        if (!playModuleId) {
          throw new Error(`Play module must include a key after 'rules.': ${rawPlayModule}`)
        }
      }
      const playSlug = (!endPlay && !retry)
        ? ((ctx.args.options['slug'] as string | undefined) || undefined)
        : undefined
      result = await runPlay(
        {
          prompt,
          module_id: playModuleId,
          pins,
          unpins,
          llm_id: llmId,
          retry,
          end: endPlay,
          as_pc,
          do_pass: passPlay,
          slug: playSlug,
        },
        handleEvent
      )
    } else if (command === 'advance') {
      const endAdvance = ctx.args.options['end'] === true
      const retryAdvance = retry
      if (endAdvance && retryAdvance) {
        throw new Error('Cannot use advance --end and --retry together')
      }
      const rawDays = ctx.args.options['days'] as string | undefined
      const days = rawDays ? parseInt(rawDays, 10) : undefined
      if (!endAdvance && days !== undefined && (!Number.isInteger(days) || days < 1)) {
        throw new Error('days must be a positive integer')
      }
      result = await runAdvance(
        { days, pins, unpins, llm_id: llmId, retry: retryAdvance, feedback: retryAdvance ? prompt : undefined, end: endAdvance },
        handleEvent
      )
    } else if (command === 'design') {
      const endDesign = ctx.args.options['end'] === true
      const designPrompt = (ctx.args.positional['prompt'] as string | undefined) || undefined
      const rawModule = (ctx.args.options['module'] as string | undefined) || undefined
      let moduleId: string | undefined
      if (!endDesign && rawModule) {
        if (!rawModule.startsWith('design.')) {
          throw new Error(`Design module must start with 'design.': ${rawModule}`)
        }
        moduleId = rawModule.slice('design.'.length)
        if (!moduleId) {
          throw new Error(`Design module must include a key after 'design.': ${rawModule}`)
        }
      }
      const designSlug = (!endDesign && !retry)
        ? ((ctx.args.options['slug'] as string | undefined) || undefined)
        : undefined
      result = await runDesign(
        { prompt: designPrompt, module_id: moduleId, pins, unpins, llm_id: llmId, retry, end: endDesign, slug: designSlug },
        handleEvent
      )
    } else if (command === 'structure-section') {
      const endSection = ctx.args.options['end'] === true
      const sectionId = ctx.args.positional['id'] as string | undefined
      if (endSection && sectionId) {
        throw new Error('Cannot use section ID and --end together')
      }
      if (endSection) {
        result = await runSectionEnd({ llm_id: llmId }, handleEvent)
      } else if (sectionId) {
        result = await runSectionStart({ id: sectionId, pins, unpins })
      } else {
        throw new Error('Section requires an ID or --end')
      }
    } else if (command === 'structure-rename') {
      const renameAddress = normalizeAddress(ctx.args.positional['address'] as string)
      const newSlug = ctx.args.positional['new_slug'] as string
      if (!renameAddress) throw new Error('rename requires an address')
      if (!newSlug) throw new Error('rename requires a new slug')
      streamingPreview.set(null)
      const renameResult = await renameNode({ address: renameAddress, new_slug: newSlug })
      if (ctx.onDone) await ctx.onDone()
      treeRefreshTrigger.update((n) => n + 1)
      if (renameResult.status === 'error') {
        cliOutput.set({ output: renameResult.detail ?? 'rename failed', exitCode: 1, streaming: false })
        return { clearInput: false }
      }
      cliOutput.set(null)
      return { clearInput: true }
    } else if (command === 'structure-collate') {
      const address = normalizeAddress(ctx.args.positional['address'] as string)
      const startLine = parseInt(ctx.args.positional['start'] as string, 10)
      const endLine = parseInt(ctx.args.positional['end'] as string, 10)
      const collateId = ctx.args.positional['id'] as string
      result = await runCollate(
        {
          id: collateId,
          address: address!,
          start_line: startLine,
          end_line: endLine,
          pins,
          unpins,
          llm_id: llmId,
        },
        handleEvent
      )
    } else {
      const address = normalizeAddress(ctx.args.positional['address'] as string)
      const startLine = parseInt(ctx.args.positional['start'] as string, 10)
      const endLine = parseInt(ctx.args.positional['end'] as string, 10)
      const replace = ctx.args.options['replace'] === true

      if (replace && !prompt) {
        // Inline edit mode: show CodeMirror editor instead of sending to server
        streamingPreview.set(null)
        const root =
          get(stats)?.active_narrative ??
          (() => {
            const cur = get(currentAddress)
            if (!cur) return ''
            const i = cur.indexOf('/')
            return i === -1 ? cur : cur.slice(0, i)
          })()
        const navAddress = root ? addressToNavAddress(address!, root) : address!
        if (ctx.navigate) {
          await ctx.navigate(navAddress)
        }
        const content = get(nodeContent)
        const lines = content.split('\n')
        const originalText = lines.slice(startLine - 1, endLine).join('\n')
        const linesAfterSelection = lines.length - endLine
        inlineEditResult.set(null)
        inlineEditMode.set({
          address: navAddress,
          startLine,
          endLine,
          originalText,
          linesAfterSelection,
        })

        const editedText = await new Promise<string | null>((resolve) => {
          const unsubResult = inlineEditResult.subscribe((val) => {
            if (val !== null) {
              unsubResult()
              unsubMode()
              resolve(val)
            }
          })
          const unsubMode = inlineEditMode.subscribe((val) => {
            if (val === null) {
              unsubResult()
              unsubMode()
              // If result was already set, it resolved above; otherwise cancelled
              resolve(get(inlineEditResult))
            }
          })
        })

        if (editedText === null) {
          return { clearInput: false }
        }

        result = await runEdit(
          {
            address: address!,
            start_line: startLine,
            end_line: endLine,
            prompt: editedText,
            replace: true,
            pins,
            unpins,
          },
          handleEvent
        )
      } else {
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
    }

    // Clear streaming preview before refreshing
    streamingPreview.set(null)

    if (ctx.onDone) await ctx.onDone()
    treeRefreshTrigger.update((n) => n + 1)

    const isError = 'type' in result && result.type === 'error'
    if (isError || errorOutput) {
      cliOutput.set({
        output: errorOutput || (isError ? (result as { message?: string }).message ?? '' : ''),
        exitCode: 1,
        streaming: false,
      })
      return { clearInput: false }
    }

    if ('type' in result && result.type === 'done') {
      const done = result as { inserted?: string[]; updated?: string[]; errors?: string[] }
      if (done.inserted?.length) {
        cliOutput.set({ output: `KB: inserted ${done.inserted.join(', ')}`, exitCode: 0, streaming: false })
      } else if (done.updated?.length) {
        cliOutput.set({ output: `KB: updated ${done.updated.join(', ')}`, exitCode: 0, streaming: false })
      } else {
        cliOutput.set(null)
      }
    } else {
      cliOutput.set(null)
    }
    const interrupted = 'interrupted' in result && result.interrupted
    return { clearInput: !interrupted }
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

export const operatorModule: CommandModule = {
  commands: (stats) => {
    const result: CommandDefinition[] = []

    for (const cmd of commands) {
      // Dataset check
      if (cmd.requiresDataset != null && !stats.current_datasets?.includes(cmd.requiresDataset)) {
        continue
      }

      // Special handling for play: requires at least one PC pinned
      // (rules.system and rules.rpg are auto-pinned by the play session)
      if (cmd.trigger === 'play') {
        const pins = stats.effective_pins_at_cursor ?? []
        const pcPins = pins.filter(p => p.startsWith('pc.'))

        if (pcPins.length === 0) {
          continue
        }

        // Always expose --as (parsed as `as`; API receives as_pc) so the user can
        // speak in-character; default is over-the-table Player voice.
        const pcKeys = pcPins.map(p => p.slice(3)).join(',')
        result.push({
          ...cmd,
          options: [
            { name: 'as', valueType: 'slug', hint: 'speaking as', slugSource: pcKeys },
            ...optionsWithLlmIfMultiple(cmd.options, stats),
          ],
        })
        continue
      }

      result.push({ ...cmd, options: optionsWithLlmIfMultiple(cmd.options, stats) })
    }
    
    return result
  }, 
  handler 
}
