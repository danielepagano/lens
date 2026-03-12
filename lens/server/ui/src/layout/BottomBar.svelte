<script lang="ts">
  import type { CommandContext, CommandResult } from '../commands/handlers'
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

  function resizeCliInput(_value: string) {
    if (!cliInputEl) return
    cliInputEl.style.height = '0px'
    const maxHeightPx = window.innerHeight ? Math.round(window.innerHeight * 0.4) : 240
    const newHeight = Math.min(cliInputEl.scrollHeight, maxHeightPx)
    cliInputEl.style.height = `${newHeight}px`
  }

  $: resizeCliInput(input)

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

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) {
        busyMessage = message
      },
      onDone: onCliDone,
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
  <div class="cli-input-row">
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
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
