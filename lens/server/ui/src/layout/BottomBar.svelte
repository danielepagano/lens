<script lang="ts">
  import type { CommandContext, CommandResult, CommandDefinition, BoolField, SelectField, AutocompleteField, ResolvedParams } from '../commands/common'
  import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../commands/handlers'
  import { cliOutput, transactionResult } from '../stores/ui'
  import type { CommandGroup } from '../commands/common'

  const MAX_HISTORY = 50

  type CommandHint = {
    trigger: string
    group: CommandGroup
    isSubOption?: boolean
    parentCommand?: string
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
  let payloadFirstWord = ''
  let isKnownCommand = true
  let flashInvalid = false
  let showInvalid = false
  let isFocused = false
  let activeCommandDef: CommandDefinition | null = null
  let resolvedParams: ResolvedParams = {}
  let paramRefs: Array<HTMLInputElement | null> = []
  let firstParamRef: HTMLElement | null = null

  function captureFirstParam(node: HTMLElement, isFirst: boolean) {
    if (isFirst) firstParamRef = node
    return { destroy() { if (isFirst) firstParamRef = null } }
  }

  function selectValue(name: string, fallback: string): string {
    const v = resolvedParams[name]
    return typeof v === 'string' ? v : fallback
  }

  function chipValues(name: string): string[] {
    const v = resolvedParams[name]
    return Array.isArray(v) ? v : []
  }

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
  $: selectFields = (activeSchema?.fields.filter((f) => f.kind === 'select') ?? []) as SelectField[]
  $: autocompleteFields = (activeSchema?.fields.filter((f) => f.kind === 'autocomplete') ?? []) as AutocompleteField[]

  $: hasParamControls = (boolFields.length > 0 || selectFields.length > 0 || autocompleteFields.length > 0) && isKnownCommand

  // Sub-option selected = first payload word is a valid sub-option
  $: activeSubOption = activeCommandDef?.subOptions?.find((s) => s.value === payloadFirstWord) ?? null

  // "no parameters" warning: suppress for commands that use sub-options or have a payload hint
  $: showParamWarning = (
    activeCommandDef?.params?.kind === 'none' &&
    !activeCommandDef?.subOptions &&
    hasPayload &&
    isKnownCommand
  )

  // Show payload hint after sub-option is selected
  $: computedHint = activeSubOption && activeCommandDef?.payloadHint
    ? activeCommandDef.payloadHint
    : (activeSchema?.hint ?? activeCommandDef?.hint ?? '')

  $: showHint = !!computedHint && isKnownCommand && (
    !!activeSubOption || (!hasPayload && !activeCommandDef?.subOptions)
  )

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
    payloadFirstWord = payloadPart.split(/\s+/)[0]?.toLowerCase() ?? ''

    isKnownCommand = !hasCommandText || KNOWN_COMMANDS.includes(lower)
    showInvalid = !busy && startsWithSlash && hasCommandText && !isKnownCommand

    // Resolve active command definition
    const newDef = hasCommandText
      ? (COMMAND_DEFINITIONS.find((d) => d.trigger === lower) ?? null)
      : null

    if (newDef?.trigger !== activeCommandDef?.trigger) {
      activeCommandDef = newDef
      const newParams: ResolvedParams = {}
      for (const field of newDef?.params?.kind === 'form' ? newDef.params.schema.fields : []) {
        if (field.kind === 'bool') {
          newParams[field.name] = field.default ?? false
        } else if (field.kind === 'select') {
          newParams[field.name] = field.options[0]?.value ?? ''
        } else if (field.kind === 'autocomplete' && field.repeatable) {
          newParams[field.name] = []
        }
      }
      resolvedParams = newParams
      const boolCount = newDef?.params?.kind === 'form'
        ? newDef.params.schema.fields.filter((f) => f.kind === 'bool').length
        : 0
      paramRefs = new Array(boolCount).fill(null)
    }

    if (!isFocused) {
      suggestions = []
      return
    }

    // Sub-option suggestions for commands like /pin
    if (newDef?.subOptions && hasCommandText && isKnownCommand) {
      const firstWord = payloadFirstWord
      const isCompleteOp = newDef.subOptions.some((s) => s.value === firstWord)
      if (!isCompleteOp) {
        // Show sub-options that match the partial first word (or all if empty)
        const matches = firstWord
          ? newDef.subOptions.filter((s) => s.value.startsWith(firstWord))
          : newDef.subOptions
        suggestions = (matches.length > 0 ? matches : newDef.subOptions).map((s) => ({
          trigger: s.value,
          group: newDef.group,
          isSubOption: true,
          parentCommand: lower,
        }))
        return
      }
      // Complete op selected — hide suggestions (hint takes over)
      suggestions = []
      return
    }

    // Standard command suggestions
    if (!hasCommandText && !hasPayload) {
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

  function completeSubOption(parentCommand: string, subValue: string) {
    input = `/${parentCommand} ${subValue} `
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
        e.preventDefault()
        if (isTouchDevice) {
          cliInputEl?.blur()
        }
        return
      }

      if (e.key === 'Backspace') {
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
      // If param controls exist and the command is fully typed, Tab moves focus there
      if (hasParamControls && isKnownCommand && hasCommandText && !e.shiftKey) {
        e.preventDefault()
        firstParamRef?.focus()
        return
      }

      if (suggestions.length > 0 && !e.shiftKey) {
        e.preventDefault()
        const first = suggestions[0]
        if (!first) return

        if (first.isSubOption && first.parentCommand) {
          completeSubOption(first.parentCommand, first.trigger)
          return
        }

        const { command } = parseCommandAndPayload(input)
        const isExactKnown = !!command && KNOWN_COMMANDS.includes(command)

        if (!command || !isExactKnown) {
          completeCommand(first.trigger)
          return
        }

        // Exact known command: cycle through global sorted list
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
      if (typeof window !== 'undefined' && 'ontouchstart' in window) {
        cliInputEl?.blur()
      }
      return
    }

    const { command, payload } = parseCommandAndPayload(raw)
    if (!command) return

    if (!KNOWN_COMMANDS.includes(command)) {
      flashInvalid = true
      showInvalid = true
      setTimeout(() => { flashInvalid = false }, 150)
      focusCliInput()
      return
    }

    pushHistory(raw)
    busy = true
    busyMessage = null
    cliOutput.set(null)
    transactionResult.set(null)
    const handler = resolveHandler(command)

    const firstStringField = activeSchema?.fields.find((f) => f.kind === 'string')
    const params: ResolvedParams = firstStringField
      ? { ...resolvedParams, [firstStringField.name]: payload || undefined }
      : resolvedParams

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) { busyMessage = message },
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
          class:cli-suggestion--narrative={cmd.group === 'narrative'}
          on:click={() => cmd.isSubOption && cmd.parentCommand
            ? completeSubOption(cmd.parentCommand, cmd.trigger)
            : completeCommand(cmd.trigger)}
        >
          {cmd.isSubOption ? cmd.trigger : `/${cmd.trigger}`}
        </button>
      {/each}
    </div>
  {/if}
  {#if hasParamControls}
    <div class="command-params">
      {#each selectFields as field, i}
        <div class="param-select-wrap">
          <select
            class="param-select"
            use:captureFirstParam={i === 0 && autocompleteFields.length === 0 && boolFields.length === 0}
            value={selectValue(field.name, field.options[0]?.value ?? '')}
            on:change={(e) => { resolvedParams = { ...resolvedParams, [field.name]: e.currentTarget.value } }}
            on:keydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
            disabled={busy}
          >
            {#each field.options as opt}
              <option value={opt.value}>{opt.label}</option>
            {/each}
          </select>
        </div>
      {/each}

      {#each autocompleteFields as field, i}
        <div class="param-ac-wrap">
          {#if field.repeatable}
            <div class="param-ac-chips">
              {#each chipValues(field.name) as chip}
                <span class="param-ac-chip">
                  {chip}
                  <button
                    type="button"
                    class="param-ac-chip-remove"
                    on:click={() => {
                      const v = chipValues(field.name)
                      resolvedParams = { ...resolvedParams, [field.name]: v.filter((c) => c !== chip) }
                    }}
                    disabled={busy}
                  >×</button>
                </span>
              {/each}
            </div>
          {/if}
          <div class="param-ac-input-wrap">
            <input
              type="text"
              class="param-ac-input"
              placeholder={field.hint ?? (field.optional ? `${field.name} (optional)` : field.name)}
              use:captureFirstParam={i === 0}
              disabled={busy}
            />
          </div>
        </div>
      {/each}

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
        <div class="cli-input-ghost" aria-hidden="true"><span class="ghost-spacer">{input}</span>&nbsp;<span class="ghost-hint" class:ghost-hint--warn={showParamWarning}>{showHint ? computedHint : 'no parameters'}</span></div>
      {/if}
    </div>
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
