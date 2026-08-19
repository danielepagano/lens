import { get } from 'svelte/store'
import { runWrite, runWriteManual, runEdit, runPlay, runDesign, runAdvance, runChat, runSectionStart, runSectionEnd, runCollate, runCompress, runKbEdit, renameNode, StreamBusyError, type OperatorEvent, type OperatorProgressEvent, type OperatorDoneEvent, type OperatorWorkflowEvent, type Stats } from '../services/api'
import {
  cliOutput,
  treeRefreshTrigger,
  inlineEditMode,
  inlineEditResult,
  scrollContentToBottom,
  scrollCodeMirrorToBottom,
  transactionResult,
  type InlineEditState,
} from '../stores/ui'
import { streamingPreview, currentAddress, nodeContent, type StreamingPreviewState } from '../stores/document'
import type {
  CliPayload,
  CommandContext,
  CommandDefinition,
  CommandHandler,
  CommandModule,
} from './common'
import { normalizeAddress, addressToNavAddress, normalizePromptNodeSliceMentions } from './common'
import { currentProject } from '../stores/project'
import { stats } from '../stores/stats'

function scrollMarkdownViewElToBottom(): void {
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

function previewBase(partial: Partial<StreamingPreviewState>): StreamingPreviewState {
  return {
    targetNode: '',
    text: '',
    steps: [],
    streamStartedAt: Date.now(),
    hiddenBytes: 0,
    turnCount: 1,
    ...partial,
  }
}

function applyWorkflowEvent(event: OperatorWorkflowEvent): void {
  if (event.action === 'plan' && event.steps) {
    streamingPreview.update((prev) =>
      previewBase({
        ...(prev ?? {}),
        targetNode: prev?.targetNode ?? '',
        text: prev?.text ?? '',
        steps: event.steps ?? [],
        pausedStepId: undefined,
      })
    )
    return
  }
  if (event.action === 'step_start' && event.step_id) {
    streamingPreview.update((prev) => {
      const base = prev ?? previewBase({})
      return {
        ...base,
        activeStepId: event.step_id,
        text: '',
        streamStartedAt: Date.now(),
        hiddenBytes: 0,
        turnCount: 1,
        steps: base.steps.map((s) =>
          s.id === event.step_id ? { ...s, status: 'running' as const } : s
        ),
      }
    })
    return
  }
  if (event.action === 'step_end' && event.step_id && event.status) {
    streamingPreview.update((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        activeStepId: undefined,
        steps: prev.steps.map((s) =>
          s.id === event.step_id
            ? {
                ...s,
                status: event.status!,
                ...(event.warnings?.length ? { warnings: event.warnings } : {}),
              }
            : s
        ),
      }
    })
    return
  }
  if (event.action === 'step_failed' && event.step_id) {
    streamingPreview.update((prev) => {
      const base = prev ?? previewBase({})
      return {
        ...base,
        activeStepId: event.step_id,
        pausedStepId: event.retryable ? event.step_id : undefined,
        steps: base.steps.map((s) =>
          s.id === event.step_id
            ? { ...s, status: 'failed' as const, error: event.error }
            : s
        ),
      }
    })
  }
}

function shouldStickWorkflowPanel(done: OperatorDoneEvent): boolean {
  if (done.workflow_outcome === 'failed' || done.workflow_outcome === 'partial') return true
  const steps = done.steps ?? []
  if (steps.some((s) => s.status === 'failed')) return true
  return steps.some((s) => (s.warnings?.length ?? 0) > 0)
}

function effectiveParamsHasLlmPin(stats: Stats): boolean {
  const ep = stats.effective_params_at_cursor
  if (!ep) return false
  for (const k of Object.keys(ep)) {
    if (
      k === 'global:llm_id' ||
      k.endsWith(':llm_id') ||
      k === 'global:llm' ||
      k.endsWith(':llm')
    ) {
      return true
    }
  }
  return false
}

function optionsWithLlmIfMultiple(
  options: CliPayload[] | undefined,
  stats: Stats
): CliPayload[] {
  const manyLlms = (stats.available_llms?.length ?? 0) > 1
  const list = options ?? []
  if (manyLlms || effectiveParamsHasLlmPin(stats)) return [...list]
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
      { name: 'mention', valueType: 'kb-id', repeatable: true, hint: 'KB ID to mention (one AI turn)' },
      { name: 'include', valueType: 'kb-id', repeatable: true, hint: 'KB ID to include (rest of node)' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: "LLM to use" },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
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
      {
        name: 'module',
        valueType: 'kb-id',
        repeatable: false,
        hint: 'design module to use',
        default: 'design.',
        availability: {
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'mention', valueType: 'kb-id', repeatable: true, hint: 'KB ID to mention (one AI turn)' },
      { name: 'include', valueType: 'kb-id', repeatable: true, hint: 'KB ID to include (rest of node)' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      { name: 'retry' },
      {
        name: 'end',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'design' } }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'slug',
        valueType: 'slug',
        hint: 'sub-node id (default: auto-generated)',
        availability: {
          require: { allOf: [{ statNeq: { key: 'active_session_operator', value: 'design' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
    ],
  },
  {
    trigger: 'chat',
    group: 'narrative',
    cursorTargeting: 'always',
    positional: [{ name: 'prompt', valueType: 'prompt', hint: 'dialog or stage directions' }],
    options: [
      { name: 'as', valueType: 'kb-id', hint: 'character the AI voices (e.g. npc.bob)' },
      {
        name: 'with',
        valueType: 'kb-id',
        hint: 'character you play; opens a back-and-forth session',
        availability: {
          require: { allOf: [{ statNeq: { key: 'active_session_operator', value: 'chat' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'mention', valueType: 'kb-id', repeatable: true, hint: 'KB ID to mention (one AI turn)' },
      { name: 'include', valueType: 'kb-id', repeatable: true, hint: 'KB ID to include (rest of node)' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      { name: 'retry' },
      {
        name: 'narrate',
        hint: 'in session: blockquote only, no [Name] prefix',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'chat' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'wait',
        hint: 'in session: append text only, no AI reply',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'chat' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'end',
        hint: 'close the chat session with a summary',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'chat' } }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'slug',
        valueType: 'slug',
        hint: 'sub-node id (default: auto-generated)',
        availability: {
          require: { allOf: [{ statNeq: { key: 'active_session_operator', value: 'chat' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
    ],
  },
  {
    trigger: 'play',
    group: 'rpg',
    requiresDataset: 'rpg',
    cursorTargeting: 'always',
    positional: [{ name: 'prompt', valueType: 'prompt', hint: 'what do you do?' }],
    mutuallyExclusiveOptions: [['pass', 'retry']],
    options: [
      {
        name: 'module',
        valueType: 'kb-id',
        repeatable: false,
        hint: 'rules module to use',
        default: 'rules.',
        exclude: ['rules.system', 'rules.rpg'],
        availability: {
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'mention', valueType: 'kb-id', repeatable: true, hint: 'KB ID to mention (one AI turn)' },
      { name: 'include', valueType: 'kb-id', repeatable: true, hint: 'KB ID to include (rest of node)' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: "LLM to use" },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      {
        name: 'retry',
        availability: {
          hideWhen: { anyOf: [{ optionTrue: 'pass' }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'end',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'play' } }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'pass',
        hint: 'have the GM respond now',
        availability: {
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      {
        name: 'slug',
        valueType: 'slug',
        hint: 'sub-node id (default: auto-generated)',
        availability: {
          require: { allOf: [{ statNeq: { key: 'active_session_operator', value: 'play' } }] },
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
    ],
  },
  {
    trigger: 'advance',
    group: 'rpg',
    requiresDataset: 'rpg',
    cursorTargeting: 'always',
    positional: [],
    mutuallyExclusiveOptions: [['end', 'retry']],
    options: [
      {
        name: 'days',
        valueType: 'int',
        hint: 'days to advance (default: 1)',
        availability: {
          hideWhen: { anyOf: [{ anyOptionsTrue: ['end', 'retry'] }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      { name: 'retry' },
      {
        name: 'end',
        availability: {
          require: { allOf: [{ statEq: { key: 'active_session_operator', value: 'advance' } }] },
          skipWhenPromptOrStringSlot: true,
        },
      },
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
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      { name: 'retry', hint: "retry previous edit in given location" },
      { name: 'replace', hint: "don't use AI, replace text with prompt directly" },
    ],
  },
  {
    trigger: 'structure-section',
    group: 'structure',
    cursorTargeting: 'always',
    positional: [
      {
        name: 'id',
        valueType: 'slug',
        required: false,
        hint: 'section ID to start; with --end only, optional summary guidance text',
      },
    ],
    options: [
      { name: 'end', hint: 'close the current section' },
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM for summary (when ending)' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
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
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      {
        name: 'summary-guide',
        valueType: 'prompt',
        hint: 'optional extra instructions for the collate summary LLM',
      },
    ],
  },
  {
    trigger: 'structure-compress',
    group: 'structure',
    cursorTargeting: 'can-override',
    positional: [
      {
        name: 'prompt',
        valueType: 'prompt',
        required: false,
        hint: 'what to collate (or use --aggressiveness instead)',
      },
    ],
    options: [
      {
        name: 'aggressiveness',
        valueType: 'slug',
        slugSource: 'low,medium,high',
        hint: 'without a prompt: automated range selection strength',
      },
      { name: 'node', valueType: 'address', hint: 'narrative node (default: cursor)' },
      { name: 'pin', valueType: 'kb-id', repeatable: true },
      { name: 'unpin', valueType: 'kb-id', repeatable: true },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      {
        name: 'summary-guide',
        valueType: 'prompt',
        hint: 'optional extra instructions for the collate summary LLM',
      },
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
  {
    trigger: 'kb-edit',
    group: 'knowledge',
    cursorTargeting: 'never',
    positional: [
      { name: 'id', valueType: 'kb-id', required: true, hint: 'Object ID (type.key)' },
      { name: 'instruction', valueType: 'prompt', required: true, hint: 'AI instruction' },
    ],
    options: [
      { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
      { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
      { name: 'context', valueType: 'address', hint: 'narrative context (e.g. /chapter-1)' },
      { name: 'include-template', valueType: 'flag', hint: 'include type template' },
      { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
      { name: 'reasoning', valueType: 'slug', slugSource: 'none,low,medium,high' },
      { name: 'retry' },
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

  const prompt = normalizePromptNodeSliceMentions(
    (ctx.args.positional['prompt'] as string | undefined) || undefined,
  )

  const pins = (ctx.args.options['pin'] as string[] | undefined) ?? []
  const unpins = (ctx.args.options['unpin'] as string[] | undefined) ?? []
  const mentions = (ctx.args.options['mention'] as string[] | undefined) ?? []
  const includes = (ctx.args.options['include'] as string[] | undefined) ?? []
  const llmId = (ctx.args.options['llm'] as string | undefined) || undefined
  const reasoning = (ctx.args.options['reasoning'] as string | undefined) || undefined
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
  let postOpInfoMessage = ''

  const handleEvent = (event: OperatorEvent): void => {
    if (event.type === 'error') {
      errorOutput += event.message
    } else if (event.type === 'target') {
      const current = get(currentAddress)
      if (current !== event.node) {
        // Set immediately so isStreamingToCurrentNode becomes true right away.
        // Do not call navigate() here — it fetch()es async and a slow/stale response can
        // overwrite nodeContent after onDone refreshes (empty node until manual reload).
        currentAddress.set(event.node)
        ctx.syncLocation?.(event.node)
        // Refresh tree so newly created nodes (e.g. design sub-nodes) appear.
        treeRefreshTrigger.update((n) => n + 1)
      }
      streamingPreview.update((prev) =>
        previewBase({
          targetNode: event.node,
          text: prev?.text ?? '',
          steps: prev?.steps ?? [],
          activeStepId: prev?.activeStepId,
        })
      )
    } else if (event.type === 'token') {
      streamingPreview.update((prev) => {
        const stepChanged =
          event.step_id !== undefined && prev?.activeStepId !== event.step_id
        if (prev) {
          return {
            ...prev,
            activeStepId: event.step_id ?? prev.activeStepId,
            text: stepChanged ? event.text : prev.text + event.text,
          }
        }
        return previewBase({ text: event.text, activeStepId: event.step_id })
      })
      requestAnimationFrame(scrollPreviewIntoView)
    } else if (event.type === 'progress') {
      if (event.phase === 'llm_stream_progress') {
        // Heartbeat only — reasoning/tool-call bytes, no visible text or status change.
        streamingPreview.update((prev) => {
          const base = prev ?? previewBase({ activeStepId: event.step_id })
          return {
            ...base,
            activeStepId: event.step_id ?? base.activeStepId,
            hiddenBytes: (base.hiddenBytes ?? 0) + (event.hidden_bytes_delta ?? 0),
          }
        })
      } else {
        const label = progressLabel(event)
        streamingPreview.update((prev) => {
          const base = prev ?? previewBase({})
          return {
            ...base,
            statusLine: label,
            activeStepId: event.step_id ?? base.activeStepId,
            turnCount:
              event.phase === 'llm_round'
                ? Math.max(base.turnCount ?? 1, (event.iteration ?? 0) + 1)
                : base.turnCount,
          }
        })
      }
    } else if (event.type === 'info') {
      const msg = typeof event.message === 'string' ? event.message.trim() : ''
      if (msg) postOpInfoMessage = msg
    } else if (event.type === 'tool_call') {
      const parts: string[] = ['⚙']
      if (event.name) parts.push(event.name)
      if (event.summary) parts.push(event.summary)
      streamingPreview.update((prev) => {
        if (prev) return { ...prev, statusLine: parts.join(' · ') }
        return previewBase({ statusLine: parts.join(' · ') })
      })
    } else if (event.type === 'workflow') {
      applyWorkflowEvent(event)
    }
  }

  // Scroll to bottom when starting the command
  scrollMarkdownViewElToBottom()

  // Show waiting state immediately (before first token arrives)
  streamingPreview.set(previewBase({}))

  try {
    let result: { type: string; message?: string; interrupted?: boolean } | { status: string; node: string }

    if (command === 'write') {
      result = await runWrite(
        { prompt, pins, unpins, mentions, includes, llm_id: llmId, reasoning, retry },
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
          mentions,
          includes,
          llm_id: llmId,
          reasoning,
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
        { days, pins, unpins, llm_id: llmId, reasoning, retry: retryAdvance, feedback: retryAdvance ? prompt : undefined, end: endAdvance },
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
        { prompt: designPrompt, module_id: moduleId, pins, unpins, mentions, includes, llm_id: llmId, reasoning, retry, end: endDesign, slug: designSlug },
        handleEvent
      )
    } else if (command === 'chat') {
      const endChat = ctx.args.options['end'] === true
      const asKbId = (ctx.args.options['as'] as string | undefined) || undefined
      const withKbId = (ctx.args.options['with'] as string | undefined) || undefined
      const chatPromptPresent = prompt !== undefined && String(prompt).trim() !== ''
      if (!endChat && !retry && !asKbId && !chatPromptPresent) {
        throw new Error('Chat requires a prompt, --as, --end, or --retry')
      }
      const chatSlug = (!endChat && !retry)
        ? ((ctx.args.options['slug'] as string | undefined) || undefined)
        : undefined
      const narrateChat = ctx.args.options['narrate'] === true
      const waitChat = ctx.args.options['wait'] === true
      result = await runChat(
        {
          prompt,
          as_kb_id: asKbId,
          with_kb_id: withKbId,
          ...(narrateChat ? { narrate: true } : {}),
          ...(waitChat ? { wait: true } : {}),
          pins,
          unpins,
          mentions,
          includes,
          llm_id: llmId,
          reasoning,
          retry,
          end: endChat,
          slug: chatSlug,
        },
        handleEvent
      )
    } else if (command === 'structure-section') {
      const endSection = ctx.args.options['end'] === true
      const sectionId = ctx.args.positional['id'] as string | undefined
      const sectionSummaryGuide =
        endSection && sectionId?.trim() ? sectionId.trim() : undefined
      if (endSection) {
        result = await runSectionEnd(
          { llm_id: llmId, reasoning, summary_guide: sectionSummaryGuide },
          handleEvent
        )
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
      const collateSummaryGuide =
        (ctx.args.options['summary-guide'] as string | undefined)?.trim() || undefined
      result = await runCollate(
        {
          id: collateId,
          address: address!,
          start_line: startLine,
          end_line: endLine,
          pins,
          unpins,
          llm_id: llmId,
          reasoning,
          summary_guide: collateSummaryGuide,
        },
        handleEvent
      )
    } else if (command === 'structure-compress') {
      const compressPrompt = normalizePromptNodeSliceMentions(
        (ctx.args.positional['prompt'] as string | undefined) || undefined,
      )?.trim()
      const rawAggr = (ctx.args.options['aggressiveness'] as string | undefined)?.trim().toLowerCase()
      const compressAggr =
        rawAggr === 'low' || rawAggr === 'medium' || rawAggr === 'high' ? rawAggr : undefined
      if (compressPrompt && compressAggr) {
        throw new Error('structure-compress: pass a prompt or --aggressiveness, not both')
      }
      if (!compressPrompt && !compressAggr) {
        throw new Error(
          'structure-compress: provide a prompt or --aggressiveness (low|medium|high)',
        )
      }
      const compressSummaryGuide =
        (ctx.args.options['summary-guide'] as string | undefined)?.trim() || undefined
      const compressNode = normalizeAddress(ctx.args.options['node'] as string | undefined)
      result = await runCompress(
        {
          ...(compressPrompt ? { prompt: compressPrompt } : { aggressiveness: compressAggr }),
          ...(compressNode ? { address: compressNode } : {}),
          pins,
          unpins,
          llm_id: llmId,
          reasoning,
          summary_guide: compressSummaryGuide,
        },
        handleEvent
      )
    } else if (command === 'kb-edit') {
      const kbId = ctx.args.positional['id'] as string
      const kbInstruction = ctx.args.positional['instruction'] as string
      if (!kbId) throw new Error('kb-edit requires an object ID')
      if (!kbInstruction) throw new Error('kb-edit requires an instruction')

      const handleKbEvent = (event: OperatorEvent): void => {
        if (event.type === 'error') {
          errorOutput += event.message
        } else if (event.type === 'target') {
          streamingPreview.update((prev) =>
            previewBase({
              targetNode: event.node,
              text: '',
              steps: prev?.steps ?? [],
            })
          )
        } else if (event.type === 'token') {
          // ignored — no streaming preview for kb-edit
        } else if (event.type === 'progress') {
          const label = progressLabel(event)
          streamingPreview.update((prev) => {
            if (prev) return { ...prev, statusLine: label }
            return previewBase({ statusLine: label })
          })
        } else if (event.type === 'info') {
          const msg = typeof event.message === 'string' ? event.message.trim() : ''
          if (msg) postOpInfoMessage = msg
        }
      }

      result = await runKbEdit(
        {
          id: kbId,
          instruction: kbInstruction,
          context: (ctx.args.options['context'] as string | undefined) || undefined,
          include_template: ctx.args.options['include-template'] === true,
          pins,
          unpins,
          llm_id: llmId,
          reasoning,
          retry,
        },
        handleKbEvent
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
            reasoning,
            retry,
            replace,
          },
          handleEvent
        )
      }
    }

    // Clear streaming preview before refreshing unless workflow failed/partial
    let stickPreview = false
    if ('type' in result && result.type === 'done') {
      stickPreview = shouldStickWorkflowPanel(result as OperatorDoneEvent)
    }
    if (stickPreview) {
      const done = result as OperatorDoneEvent
      streamingPreview.update((prev) =>
        prev
          ? {
              ...prev,
              sticky: true,
              pausedStepId: undefined,
              steps: done.steps ?? prev.steps,
            }
          : null
      )
    } else {
      streamingPreview.set(null)
    }

    if (ctx.onDone) await ctx.onDone()
    treeRefreshTrigger.update((n) => n + 1)

    if (command === 'kb-edit' && 'node' in result && typeof result.node === 'string' && !('interrupted' in result && result.interrupted)) {
      const slug = get(currentProject)
      const addr = get(currentAddress) || ''
      const base = [slug, addr].filter(Boolean).join('/')
      window.location.hash = `${base}?kb=${encodeURIComponent(result.node)}`
    }

    const isError = 'type' in result && result.type === 'error'
    if (isError || errorOutput) {
      const errText = errorOutput || (isError ? (result as { message?: string }).message ?? '' : '')
      if (command === 'structure-compress' && errText) {
        transactionResult.set({
          title: 'Compress',
          message: errText,
          theme: 'error',
        })
        cliOutput.set(null)
      } else {
        cliOutput.set({
          output: errText,
          exitCode: 1,
          streaming: false,
        })
      }
      return { clearInput: false }
    }

    if (command === 'edit') {
      scrollContentToBottom.update((n) => n + 1)
      scrollCodeMirrorToBottom.update((n) => n + 1)
    }

    if ('type' in result && result.type === 'done') {
      const done = result as { inserted?: string[]; updated?: string[]; errors?: string[] }
      if (done.inserted?.length) {
        cliOutput.set({ output: `KB: inserted ${done.inserted.join(', ')}`, exitCode: 0, streaming: false })
      } else if (done.updated?.length) {
        cliOutput.set({ output: `KB: updated ${done.updated.join(', ')}`, exitCode: 0, streaming: false })
      } else if (postOpInfoMessage) {
        cliOutput.set({ output: postOpInfoMessage, exitCode: 0, streaming: false })
      } else {
        cliOutput.set(null)
      }
    } else {
      if (postOpInfoMessage) {
        cliOutput.set({ output: postOpInfoMessage, exitCode: 0, streaming: false })
      } else {
        cliOutput.set(null)
      }
    }
    const interrupted = 'interrupted' in result && result.interrupted
    return { clearInput: !interrupted }
  } catch (err) {
    // Clear streaming preview on error
    streamingPreview.set(null)

    if (err instanceof StreamBusyError) {
      if (command === 'structure-compress') {
        transactionResult.set({
          title: 'Compress',
          message: err.message,
          theme: 'error',
        })
        cliOutput.set(null)
      } else {
        cliOutput.set({
          output: err.message,
          exitCode: 1,
          streaming: false,
        })
      }
      if (ctx.onDone) await ctx.onDone()
      return { clearInput: false }
    }

    const msg = err instanceof Error ? err.message : String(err)
    if (command === 'structure-compress' && msg) {
      transactionResult.set({
        title: 'Compress',
        message: msg,
        theme: 'error',
      })
      cliOutput.set(null)
    } else {
      cliOutput.set({
        output: msg,
        exitCode: 1,
        streaming: false,
      })
    }
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
