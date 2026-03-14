<script lang="ts">
  import type { CommandContext, CommandResult, CommandDefinition } from '../commands/common'
  import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../commands/handlers'
  import { parseCliInput, buildArgs } from '../commands/parser'
  import type { ParseState } from '../commands/parser'
  import { getCommandSuggestions, getSuggestions, type Suggestion, type DataSources } from '../features/cli/CliAutocomplete'
  import CliSuggestions from '../features/cli/CliSuggestions.svelte'
  import { cliOutput, transactionResult, treeRefreshTrigger } from '../stores/ui'
  import { stats } from '../stores/stats'
  import { getKbItems, getTree } from '../services/api'
  import type { TreeNode } from '../services/api'

  const MAX_HISTORY = 50

  export let onCliDone: (() => Promise<void>) | undefined = undefined

  let input = ''
  let busy = false
  let busyMessage: string | null = null
  let cliInputEl: HTMLTextAreaElement | null = null
  let history: string[] = []
  let historyIndex = -1
  let suggestions: Suggestion[] = []
  let isKnownCommand = true
  let flashInvalid = false
  let showInvalid = false
  let isFocused = false
  let activeCommandDef: CommandDefinition | null = null
  let currentParseState: ParseState | null = null

  // Data source caches for autocomplete
  let kbKeyCache = new Map<string, string[]>()
  let nodeTreeCache: TreeNode[] | null = null
  let nodeTreeFetchPending = false

  $: {
    void $treeRefreshTrigger
    nodeTreeCache = null
    nodeTreeFetchPending = false
    kbKeyCache = new Map()
  }

  function resizeCliInput(_value: string) {
    if (!cliInputEl) return
    requestAnimationFrame(() => {
      if (!cliInputEl) return
      cliInputEl.style.height = '0px'
      const maxHeightPx = window.innerHeight ? Math.round(window.innerHeight * 0.4) : 240
      const newHeight = Math.min(cliInputEl.scrollHeight + 3, maxHeightPx)
      cliInputEl.style.height = `${newHeight}px`
    })
  }

  $: resizeCliInput(input)

  function focusCliInput() {
    setTimeout(() => {
      if (!cliInputEl) return
      try { cliInputEl.focus({ preventScroll: true }) } catch { cliInputEl.focus() }
    }, 0)
  }

  function pushHistory(command: string) {
    if (!command) return
    history = [...history, command].slice(-MAX_HISTORY)
    historyIndex = -1
  }

  function parseCommandAndPayload(value: string): { command: string | null; payload: string } {
    const trimmed = value.trim()
    if (!trimmed.startsWith('/')) return { command: null, payload: '' }
    const withoutSlash = trimmed.slice(1)
    if (!withoutSlash) return { command: null, payload: '' }
    const parts = withoutSlash.split(/\s+/)
    const command = parts[0]?.toLowerCase() ?? null
    const payload = parts.slice(1).join(' ').trimStart()
    return { command, payload }
  }

  // --- Data sources for autocomplete ---

  function fetchKbKeys(type: string) {
    if (kbKeyCache.has(type)) return
    getKbItems({ type }).then((items) => {
      const keys = items.map((item) => item.id.slice(item.id.indexOf('.') + 1))
      kbKeyCache.set(type, keys)
      kbKeyCache = kbKeyCache // trigger reactivity
      updateCommandState()
    }).catch(() => {
      kbKeyCache.set(type, [])
      kbKeyCache = kbKeyCache
    })
  }

  function fetchNodeTree() {
    if (nodeTreeFetchPending || nodeTreeCache !== null) return
    nodeTreeFetchPending = true
    getTree().then((tree) => {
      nodeTreeCache = tree
      updateCommandState()
    }).catch(() => {
      nodeTreeCache = []
    }).finally(() => {
      nodeTreeFetchPending = false
    })
  }

  function makeDataSources(): DataSources {
    return {
      kbTypes: $stats?.kb_types ?? [],
      kbKeyCache,
      fetchKbKeys,
      nodeTree: nodeTreeCache,
      fetchNodeTree,
      kbKeyThreshold: 10,
      stats: $stats,
    }
  }

  // --- State update ---

  function updateCommandState() {
    const trimmed = input.trim()
    const startsWithSlash = trimmed.startsWith('/')
    const withoutSlash = startsWithSlash ? trimmed.slice(1) : trimmed
    const parts = withoutSlash.split(/\s+/).filter(Boolean)
    const commandPart = parts[0] ?? ''
    const hasCommandText = commandPart.length > 0
    const lower = commandPart.toLowerCase()

    isKnownCommand = !hasCommandText || KNOWN_COMMANDS.includes(lower)
    showInvalid = !busy && startsWithSlash && hasCommandText && !isKnownCommand

    // Resolve definition
    activeCommandDef = hasCommandText
      ? (COMMAND_DEFINITIONS.find((d) => d.trigger === lower) ?? null)
      : null

    // Parse input against definition
    const state = parseCliInput(input, activeCommandDef)
    currentParseState = state

    if (!isFocused) {
      suggestions = []
      return
    }

    // Command-level suggestions
    if (state.phase === 'command') {
      suggestions = getCommandSuggestions(COMMAND_DEFINITIONS, state.currentToken)
      // Hide command suggestions once a known command with a hint is fully typed
      if (activeCommandDef && !input.trim().includes(' ') && activeCommandDef.hint) {
        // Still showing command list while typing partial
      }
      return
    }

    // If command is known but has no definition somehow, no suggestions
    if (!activeCommandDef) {
      suggestions = []
      return
    }

    // Hide command suggestions once we're past the command and there's a hint
    if (activeCommandDef.hint && state.phase === 'positional' && !state.activePayload) {
      suggestions = []
      return
    }

    // Get payload-level suggestions from the autocomplete engine
    suggestions = getSuggestions(state, activeCommandDef, makeDataSources())
  }

  // --- Completion helpers ---

  function completeCommand(cmd: string) {
    const { payload } = parseCommandAndPayload(input)
    input = `/${cmd}${payload ? ` ${payload}` : ' '}`
    updateCommandState()
    focusCliInput()
  }

  function completeSuggestion(sug: Suggestion) {
    switch (sug.kind) {
      case 'command':
        completeCommand(sug.value)
        return
      case 'slug':
        // Replace current token with the slug value and add space
        replaceCurrentToken(sug.value + ' ')
        return
      case 'kb-type':
        // Append the type + dot separator
        replaceCurrentToken(sug.value)
        return
      case 'kb-key':
        // Complete the full kb-id and add space
        replaceCurrentToken(sug.value + ' ')
        return
      case 'flag':
        // Insert the flag and a space
        replaceCurrentToken(sug.value + ' ')
        return
      case 'node':
        // Node address: if has children, append slash; otherwise space
        replaceCurrentToken(sug.value + (sug.nodeHasChildren ? '/' : ' '))
        return
    }
  }

  function replaceCurrentToken(replacement: string) {
    const trimmed = input.trim()
    const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
    const allTokens = withoutSlash.split(/\s+/).filter(Boolean)
    const endsWithSpace = input.endsWith(' ')

    if (endsWithSpace || allTokens.length <= 1) {
      // Append to end
      input = (endsWithSpace ? input : input + ' ') + replacement
    } else {
      // Replace the last token
      const beforeLastToken = input.slice(0, input.lastIndexOf(allTokens[allTokens.length - 1]!))
      input = beforeLastToken + replacement
    }
    updateCommandState()
    focusCliInput()
  }

  // --- Input handlers ---

  function handleInput(e: Event) {
    if (!(e.target instanceof HTMLTextAreaElement)) return
    let value = e.target.value
    if (!value.startsWith('/')) {
      value = '/' + value.replace(/^\/+/, '')
    }
    input = value
    updateCommandState()
  }

  function handleKeydown(e: KeyboardEvent) {
    const isTouchDevice = typeof window !== 'undefined' && 'ontouchstart' in window
    const trimmed = input.trim()
    const isLogicalEmpty = trimmed === '' || trimmed === '/'

    if (isLogicalEmpty) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        if (isTouchDevice) cliInputEl?.blur()
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

    if (e.key === 'Tab' && !e.shiftKey && suggestions.length > 0) {
      e.preventDefault()
      const first = suggestions[0]
      if (!first) return

      // For command suggestions when an exact command is already typed, cycle
      if (first.kind === 'command') {
        const { command } = parseCommandAndPayload(input)
        if (command && KNOWN_COMMANDS.includes(command)) {
          const idx = KNOWN_COMMANDS.findIndex((c) => c === command)
          const next = (idx === -1 ? 0 : (idx + 1) % KNOWN_COMMANDS.length)
          completeCommand(KNOWN_COMMANDS[next] ?? KNOWN_COMMANDS[0] ?? '')
          return
        }
      }

      completeSuggestion(first)
      return
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

  // --- Submit ---

  async function submit() {
    const raw = input.trim()
    if (raw === '') {
      if (typeof window !== 'undefined' && 'ontouchstart' in window) cliInputEl?.blur()
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
    const def = COMMAND_DEFINITIONS.find((d) => d.trigger === command) ?? null
    const state = parseCliInput(raw, def)
    const args = buildArgs(state, def)

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) { busyMessage = message },
      onDone: onCliDone,
      args,
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

  // --- Computed hint ---

  $: computedHint = (() => {
    if (!activeCommandDef || !isKnownCommand) return ''
    // Show the hint for whichever payload slot is currently active
    const activeHint = currentParseState?.activePayload?.hint
    if (activeHint) return activeHint
    // Fall back to the command-level hint (shown before any payload is typed)
    const trimmed = input.trim()
    const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
    const hasPayload = withoutSlash.split(/\s+/).filter(Boolean).length > 1
    if (!hasPayload) return activeCommandDef.hint ?? ''
    return ''
  })()

  $: showHint = !!computedHint && isKnownCommand
</script>

<div class="bottom-bar" data-testid="bottom-bar">
  <CliSuggestions
    {suggestions}
    noWrap={$cliOutput !== null}
    onSelect={completeSuggestion}
  />
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
      {#if showHint}
        <div class="cli-input-ghost" aria-hidden="true"><span class="ghost-spacer">{input}</span>&nbsp;<span class="ghost-hint">{computedHint}</span></div>
      {/if}
    </div>
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
