<script lang="ts">
  import type { CommandContext, CommandResult, CommandDefinition, BoolField, ResolvedParams } from '../commands/common'
  import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../commands/handlers'
  import { cliOutput, transactionResult } from '../stores/ui'
  import type { CommandGroup } from '../commands/common'

  const MAX_HISTORY = 50

  type CommandHint = {
    trigger: string
    group: CommandGroup
  }

  export let onCliDone: (() => Promise<void>) | undefined = undefined

  let input = ''
  let busy = false
  let busyMessage: string | null = null
  let cliInputEl: HTMLTextAreaElement | null = null
  let history: string[] = []
  let historyIndex = -1
  let suggestions: CommandHint[] = []
  let hasCommandText = false
  let hasPayload = false
  let isKnownCommand = true
  let flashInvalid = false
  let showInvalid = false
  let isFocused = false
  let activeCommandDef: CommandDefinition | null = null
  let resolvedParams: ResolvedParams = {}
  let paramRefs: Array<HTMLInputElement | null> = []

  function resizeCliInput(_value: string) {
    if (!cliInputEl) return
    cliInputEl.style.height = '0px'
    const maxHeightPx = window.innerHeight ? Math.round(window.innerHeight * 0.4) : 240
    const newHeight = Math.min(cliInputEl.scrollHeight + 3, maxHeightPx)
    cliInputEl.style.height = `${newHeight}px`
  }

  $: resizeCliInput(input)

  $: activeSchema = activeCommandDef?.params?.kind === 'form'
    ? activeCommandDef.params.schema
    : null

  $: boolFields = (activeSchema?.fields.filter((f) => f.kind === 'bool') ?? []) as BoolField[]

  $: hasParamControls = boolFields.length > 0 && isKnownCommand

  $: showParamWarning = activeCommandDef?.params?.kind === 'none' && hasPayload && isKnownCommand

  $: showHint = !!(activeSchema?.hint ?? activeCommandDef?.hint) && !hasPayload && isKnownCommand

  $: activeHint = activeSchema?.hint ?? activeCommandDef?.hint ?? ''

  function focusCliInput() {
    setTimeout(() => {
      if (!cliInputEl) return
      try {
        cliInputEl.focus({ preventScroll: true })
      } catch {
        cliInputEl.focus()
      }
    }, 0)
  }

  function pushHistory(command: string) {
    if (!command) return
    history = [...history, command].slice(-MAX_HISTORY)
    historyIndex = -1
  }

  function parseCommandAndPayload(value: string): {
    command: string | null
    payload: string
  } {
    const trimmed = value.trim()
    if (!trimmed.startsWith('/')) {
      return { command: null, payload: '' }
    }
    const withoutSlash = trimmed.slice(1)
    if (!withoutSlash) return { command: null, payload: '' }
    const parts = withoutSlash.split(/\s+/)
    const command = parts[0]?.toLowerCase() ?? null
    const payload = parts.slice(1).join(' ').trimStart()
    return { command, payload }
  }

  function updateCommandState() {
    const trimmed = input.trim()
    const startsWithSlash = trimmed.startsWith('/')
    const withoutSlash = startsWithSlash ? trimmed.slice(1) : trimmed
    const parts = withoutSlash.split(/\s+/).filter((p) => p.length > 0)
    const commandPart = parts[0] ?? ''
    const payloadPart = parts.slice(1).join(' ').trimStart()

    hasCommandText = commandPart.length > 0
    hasPayload = payloadPart.length > 0

    const lower = commandPart.toLowerCase()

    if (!isFocused) {
      suggestions = []
    } else if (!hasCommandText && !hasPayload) {
      // Empty CLI while focused: show full list
      suggestions = COMMAND_DEFINITIONS.map((def) => ({
        trigger: def.trigger,
        group: def.group,
      }))
    } else if (hasCommandText && !hasPayload) {
      const matches = COMMAND_DEFINITIONS.filter((def) =>
        def.trigger.startsWith(lower)
      ).map((def) => ({
        trigger: def.trigger,
        group: def.group,
      }))
      // Keep showing the full list if there are no matches
      suggestions =
        matches.length > 0
          ? matches
          : COMMAND_DEFINITIONS.map((def) => ({
              trigger: def.trigger,
              group: def.group,
            }))
    } else {
      suggestions = []
    }

    isKnownCommand = !hasCommandText || KNOWN_COMMANDS.includes(lower)
    showInvalid = !busy && startsWithSlash && hasCommandText && !isKnownCommand

    // Resolve active command definition
    const newDef = hasCommandText
      ? (COMMAND_DEFINITIONS.find((d) => d.trigger === lower) ?? null)
      : null

    if (newDef?.trigger !== activeCommandDef?.trigger) {
      activeCommandDef = newDef
      // Re-initialize resolvedParams from defaults
      const newParams: ResolvedParams = {}
      for (const field of newDef?.params?.kind === 'form' ? newDef.params.schema.fields : []) {
        if (field.kind === 'bool') {
          newParams[field.name] = field.default ?? false
        }
      }
      resolvedParams = newParams
      // Pre-allocate paramRefs for bind:this to work on first render
      const boolCount = newDef?.params?.kind === 'form'
        ? newDef.params.schema.fields.filter((f) => f.kind === 'bool').length
        : 0
      paramRefs = new Array(boolCount).fill(null)
    }

    // Hide suggestions once a command with its own hint/params UI is fully typed
    if (newDef && !hasPayload && (
      newDef.params?.kind === 'none' ||
      (newDef.params?.kind === 'form' && newDef.params.schema.hint)
    )) {
      suggestions = []
    }
  }

  function handleInput(e: Event) {
    if (!(e.target instanceof HTMLTextAreaElement)) return
    let value = e.target.value
    if (!value.startsWith('/')) {
      value = '/' + value.replace(/^\/+/, '')
    }
    input = value
    updateCommandState()
  }

  function completeCommand(cmd: string) {
    const { payload } = parseCommandAndPayload(input)
    const suffix = payload ? ` ${payload}` : ' '
    input = `/${cmd}${suffix}`
    updateCommandState()
    resizeCliInput(input)
    focusCliInput()
  }

  function handleKeydown(e: KeyboardEvent) {
    const isTouchDevice =
      typeof window !== 'undefined' && 'ontouchstart' in window

    const trimmed = input.trim()
    const isLogicalEmpty = trimmed === '' || trimmed === '/'

    if (isLogicalEmpty) {
      if (e.key === 'Enter' && !e.shiftKey) {
        // Empty Enter: do not send a command.
        // On touch devices, treat this as a dismiss gesture.
        e.preventDefault()
        if (isTouchDevice) {
          cliInputEl?.blur()
        }
        return
      }

      if (e.key === 'Backspace') {
        // Backspace on an empty CLI: close the CLI output panel if open,
        // or dismiss on touch devices.
        if ($cliOutput) {
          e.preventDefault()
          cliOutput.set(null)
          return
        }
        if (isTouchDevice) {
          e.preventDefault()
          cliInputEl?.blur()
          return
        }
      }
    }

    if (e.key === 'Tab') {
      // If param controls exist and user has typed a payload, Tab moves focus there
      if (hasParamControls && hasPayload && !e.shiftKey) {
        e.preventDefault()
        paramRefs[0]?.focus()
        return
      }

      if (!hasPayload && suggestions.length > 0) {
        e.preventDefault()
        const { command } = parseCommandAndPayload(input)
        const isExactKnown = !!command && KNOWN_COMMANDS.includes(command)

        if (!command || !isExactKnown) {
          // No command yet or partial prefix: pick the first suggestion
          completeCommand(suggestions[0]?.trigger ?? '')
          return
        }

        // Exact known command with no payload: cycle through the global, sorted list
        const currentIndex = KNOWN_COMMANDS.findIndex((c) => c === command)
        const nextIndex =
          currentIndex === -1 ? 0 : (currentIndex + 1) % KNOWN_COMMANDS.length
        completeCommand(
          KNOWN_COMMANDS[nextIndex] ?? KNOWN_COMMANDS[0] ?? ''
        )
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (history.length === 0) return
      if (historyIndex === -1) {
        historyIndex = history.length - 1
        input = history[historyIndex] ?? ''
      } else if (historyIndex > 0) {
        historyIndex--
        input = history[historyIndex] ?? ''
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (historyIndex === -1) return
      if (historyIndex < history.length - 1) {
        historyIndex++
        input = history[historyIndex] ?? ''
      } else {
        historyIndex = -1
        input = ''
      }
    }
  }

  function handleBeforeInput(e: InputEvent) {
    // Mobile keyboards often emit line breaks via beforeinput rather than keydown.
    if (busy) return
    if (e.isComposing) return
    if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') {
      e.preventDefault()
      submit()
    }
  }

  async function submit() {
    const raw = input.trim()
    if (raw === '') {
      // Do not run or add empty commands to history.
      if (typeof window !== 'undefined' && 'ontouchstart' in window) {
        cliInputEl?.blur()
      }
      return
    }

    const { command, payload } = parseCommandAndPayload(raw)
    if (!command) {
      return
    }

    if (!KNOWN_COMMANDS.includes(command)) {
      flashInvalid = true
      showInvalid = true
      setTimeout(() => {
        flashInvalid = false
      }, 150)
      focusCliInput()
      return
    }

    pushHistory(raw)
    busy = true
    busyMessage = null
    cliOutput.set(null)
    transactionResult.set(null)
    const handler = resolveHandler(command)

    // Populate the first string field from the textarea payload
    const firstStringField = activeSchema?.fields.find((f) => f.kind === 'string')
    const params: ResolvedParams = firstStringField
      ? { ...resolvedParams, [firstStringField.name]: payload || undefined }
      : resolvedParams

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) {
        busyMessage = message
      },
      onDone: onCliDone,
      resolvedParams: params,
    }

    try {
      const result: CommandResult = await handler(command, payload, ctx)
      if (result.clearInput) {
        input = ''
        updateCommandState()
      }
    } finally {
      busy = false
      // Keep focusing after a run for quick desktop workflows; on mobile
      // Safari this uses preventScroll to avoid jumping the viewport.
      focusCliInput()
    }
  }
</script>

<div class="bottom-bar" data-testid="bottom-bar">
  {#if suggestions.length > 0}
    <div class="cli-suggestions" class:no-wrap={$cliOutput !== null}>
      {#each suggestions as cmd}
        <button
          type="button"
          class="cli-suggestion"
          class:cli-suggestion--cli={cmd.group === 'cli'}
          on:click={() => completeCommand(cmd.trigger)}
        >
          /{cmd.trigger}
        </button>
      {/each}
    </div>
  {/if}
  {#if hasParamControls}
    <div class="command-params">
      {#each boolFields as field, i}
        <label class="param-bool">
          <input
            type="checkbox"
            bind:this={paramRefs[i]}
            checked={!!resolvedParams[field.name]}
            on:change={(e) => {
              resolvedParams = { ...resolvedParams, [field.name]: e.currentTarget.checked }
            }}
            on:keydown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); submit() }
              if (e.key === 'Tab' && !e.shiftKey && i === boolFields.length - 1) {
                e.preventDefault(); cliInputEl?.focus()
              }
              if (e.key === 'Tab' && e.shiftKey && i === 0) {
                e.preventDefault(); cliInputEl?.focus()
              }
            }}
            disabled={busy}
          />
          {field.label}
        </label>
      {/each}
    </div>
  {/if}
  <div class="cli-input-row">
    <div class="cli-input-wrapper">
      <textarea
        bind:this={cliInputEl}
        class="cli-input"
        class:invalid={showInvalid}
        class:flash-invalid={flashInvalid}
        bind:value={input}
        on:input={handleInput}
        on:keydown={handleKeydown}
        on:beforeinput={handleBeforeInput}
        on:focus={() => {
          isFocused = true
          updateCommandState()
        }}
        on:blur={() => {
          isFocused = false
          updateCommandState()
        }}
        rows="1"
        disabled={busy}
        data-testid="cli-input"
      />
      {#if showHint || showParamWarning}
        <div class="cli-input-ghost" aria-hidden="true"><span class="ghost-spacer">{input}</span>&nbsp;<span class="ghost-hint" class:ghost-hint--warn={showParamWarning}>{showHint ? activeHint : 'no parameters'}</span></div>
      {/if}
    </div>
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
