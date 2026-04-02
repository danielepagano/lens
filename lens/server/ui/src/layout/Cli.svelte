<script lang="ts">
  import { tick } from 'svelte'
  import type { CommandContext, CommandResult, CommandDefinition } from '../commands/common'
  import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../commands/handlers'
  import { parseCliInput, buildArgs } from '../commands/parser'
  import type { ParseState } from '../commands/parser'
  import {
    getCommandSuggestions,
    getSuggestions,
    limitCliSuggestions,
    type Suggestion,
    type DataSources,
  } from '../features/cli/CliAutocomplete'
  import CliSuggestions from '../features/cli/CliSuggestions.svelte'
  import { cliOutput, transactionResult, treeRefreshTrigger, linePickMode, linePickSelection, mountCacheRefreshTrigger } from '../stores/ui'
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import { getKbItems, getTree, browseMountDir } from '../services/api'
  import type { TreeNode, MountEntry } from '../services/api'
  import { kbMentionAtCaret, promptDiceExpressionHint } from '../utils/cliCaret'

  const MAX_HISTORY = 50

  export let onCliDone: (() => Promise<void>) | undefined = undefined
  export let navigate: ((addr: string) => Promise<void>) | undefined = undefined

  let input = ''
  let busy = false
  let busyMessage: string | null = null
  let cliInputEl: HTMLTextAreaElement | null = null
  let bottomBarEl: HTMLDivElement | null = null
  let history: string[] = []
  let historyIndex = -1
  let suggestions: Suggestion[] = []
  let isKnownCommand = true
  let flashInvalid = false
  let showInvalid = false
  let isFocused = false
  let activeCommandDef: CommandDefinition | null = null
  let currentParseState: ParseState | null = null
  let lastAutoFilledCommand: string | null = null
  let addressAutoFilled = false
  let sessionFillSuppressed = false
  let lastSessionOperator: string | null = null

  /** Caret end position, kept fresh so chip clicks can find @-mentions after textarea blurs. */
  let cliCaretHi = 0

  function captureCliCaret() {
    if (!cliInputEl) return
    const n = input.length
    cliCaretHi = Math.min(Math.max(cliInputEl.selectionEnd ?? n, cliInputEl.selectionStart ?? n), n)
  }

  /** Snapshot caret on chip pointerdown (before blur can clear textarea selection). */
  function snapshotCaretBeforeChipPointer() {
    if (cliInputEl && document.activeElement === cliInputEl) captureCliCaret()
  }

  // Data source caches for autocomplete
  let kbKeyCache = new Map<string, string[]>()
  let nodeTreeCache: TreeNode[] | null = null
  let nodeTreeFetchPending = false
  let mountDirCache = new Map<string, MountEntry[]>()
  let mountDirFetchPending = new Set<string>()

  $: {
    void $treeRefreshTrigger
    nodeTreeCache = null
    nodeTreeFetchPending = false
    kbKeyCache = new Map()
  }

  $: {
    void $mountCacheRefreshTrigger
    mountDirCache = new Map()
    mountDirFetchPending = new Set()
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

  function inputIsMultiLine(): boolean {
    const el = cliInputEl
    if (!el) return false
    const prev = el.style.height
    el.style.height = '0px'
    const naturalHeight = el.scrollHeight
    el.style.height = prev
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20
    return naturalHeight > lineHeight * 1.5
  }

  $: resizeCliInput(input)

  $: {
    const newOp = $stats?.active_session_operator ?? null
    if (newOp !== lastSessionOperator) {
      lastSessionOperator = newOp
      sessionFillSuppressed = false
      updateCommandState()
    }
  }

  function focusCliInput() {
    if (!cliInputEl) return
    try {
      cliInputEl.focus({ preventScroll: true })
    } catch {
      cliInputEl.focus()
    }
  }

  function pushHistory(command: string) {
    if (!command) return
    history = [...history, command].slice(-MAX_HISTORY)
    historyIndex = -1
  }

  /**
   * Convert a display-format address (e.g. '/', '/chapter-1') to the API-format
   * address that navigate() and $currentAddress use (e.g. 'story', 'story/chapter-1').
   * Returns null if the tree cache isn't loaded yet.
   */
  function displayAddrToNavAddr(displayAddr: string): string | null {
    if (!nodeTreeCache || nodeTreeCache.length === 0) return null
    const root = nodeTreeCache[0]!
    const normalized = displayAddr.replace(/\/+$/g, '')
    if (normalized === '' || normalized === '/') return root.address
    if (normalized.startsWith('/')) return root.address + normalized
    return normalized
  }

  function navAddrToDisplayAddr(navAddr: string): string | null {
    if (!nodeTreeCache || nodeTreeCache.length === 0) return null
    const root = nodeTreeCache[0]!
    if (navAddr === root.address) return '/'
    if (navAddr.startsWith(root.address + '/')) return navAddr.slice(root.address.length)
    return null
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

  function fetchMountDir(path: string) {
    if (mountDirFetchPending.has(path)) return
    mountDirFetchPending.add(path)
    browseMountDir(path).then((entries) => {
      mountDirCache = new Map(mountDirCache).set(path, entries)
      updateCommandState()
    }).catch(() => {
      mountDirCache = new Map(mountDirCache).set(path, [])
    }).finally(() => {
      mountDirFetchPending.delete(path)
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
      stats: $stats,
      mountDirCache,
      fetchMountDir,
    }
  }

  // --- State update ---

  function updateCommandState() {
    const trimmed = input.trim()

    // Session operator auto-fill: when input is empty and cursor is inside a session, pre-select it.
    if ((trimmed === '' || trimmed === '/') && !sessionFillSuppressed) {
      const sessionOp = $stats?.active_session_operator
      if (sessionOp && KNOWN_COMMANDS.includes(sessionOp)) {
        input = '/' + sessionOp + ' '
        updateCommandState()
        return
      }
    }

    const startsWithSlash = trimmed.startsWith('/')
    const withoutSlash = startsWithSlash ? trimmed.slice(1) : trimmed
    const parts = withoutSlash.split(/\s+/).filter(Boolean)
    const commandPart = parts[0] ?? ''
    const hasCommandText = commandPart.length > 0
    const lower = commandPart.toLowerCase()

    isKnownCommand = !hasCommandText || KNOWN_COMMANDS.includes(lower)
    showInvalid = !busy && startsWithSlash && hasCommandText && !isKnownCommand && !KNOWN_COMMANDS.some((c) => c.startsWith(lower))

    // Resolve definition
    activeCommandDef = hasCommandText
      ? (COMMAND_DEFINITIONS.find((d) => d.trigger === lower) ?? null)
      : null

    // Parse input against definition
    const state = parseCliInput(input, activeCommandDef)
    currentParseState = state

    // Reset address auto-fill flag when command changes
    const currentTrigger = activeCommandDef?.trigger ?? null
    if (currentTrigger !== lastAutoFilledCommand) {
      lastAutoFilledCommand = currentTrigger
      addressAutoFilled = false
    }

    // Pre-fill address slot with currently visible node on first entry (not for every command —
    // e.g. /pin --node should stay empty until chosen).
    const autofillAddressFromVisibleNode =
      activeCommandDef?.trigger === 'attach' ||
      activeCommandDef?.trigger === 'edit' ||
      activeCommandDef?.trigger === 'structure-rewind' ||
      activeCommandDef?.trigger === 'structure-rename' ||
      activeCommandDef?.trigger === 'structure-collate' ||
      (activeCommandDef?.trigger === 'media' &&
        (state.completedPositional['action'] as string | undefined) === 'attach')
    if (
      autofillAddressFromVisibleNode &&
      !addressAutoFilled &&
      state.activePayload?.valueType === 'address' &&
      state.currentToken === '' &&
      $currentAddress
    ) {
      fetchNodeTree()
      const displayAddr = navAddrToDisplayAddr($currentAddress)
      if (displayAddr) {
        addressAutoFilled = true
        input = input.trimEnd() + ' ' + displayAddr + ' '
        updateCommandState()
        return
      }
    }

    // Line pick mode: always update from current input so it clears when history is navigated
    const activeType = state.activePayload?.valueType
    if (activeType === 'line' && activeCommandDef) {
      const addrPos = activeCommandDef.positional?.find((p) => p.valueType === 'address')
      const displayAddr = addrPos
        ? (state.completedPositional[addrPos.name] as string | undefined)
        : undefined
      if (displayAddr) {
        fetchNodeTree() // ensure cache is available; triggers updateCommandState() on load
        const navAddr = displayAddrToNavAddr(displayAddr)
        if (navAddr) {
          // Determine if this is the second pick (end line) and which operator's rules apply
          const payloadName = state.activePayload?.name
          const isEndPick = payloadName === 'end'
          const startVal = isEndPick
            ? parseInt(state.completedPositional['start'] as string, 10)
            : undefined
          const trigger = activeCommandDef.trigger
          const mediaAttach =
            trigger === 'media' &&
            (state.completedPositional['action'] as string | undefined) === 'attach'
          const operatorMode: 'edit' | 'collate' | 'attach' | undefined =
            trigger === 'edit'
              ? 'edit'
              : trigger === 'structure-collate'
                ? 'collate'
                : mediaAttach
                  ? 'attach'
                  : undefined

          linePickMode.set({
            address: navAddr,
            startLine: isEndPick && startVal && !isNaN(startVal) ? startVal : undefined,
            operatorMode,
          })
          if (navAddr !== $currentAddress) void navigate?.(navAddr)
        }
        // else: tree not loaded yet — updateCommandState() will rerun once it loads
      } else {
        linePickMode.set(null)
        linePickSelection.set(null)
      }
    } else {
      linePickMode.set(null)
      linePickSelection.set(null)
    }

    if (isFocused && cliInputEl) {
      captureCliCaret()
    }

    if (!isFocused) {
      suggestions = []
      return
    }

    // Command-level suggestions
    if (state.phase === 'command') {
      suggestions = limitCliSuggestions(getCommandSuggestions(COMMAND_DEFINITIONS, state.currentToken))
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
    let suggestionState = state
    if (
      state.phase === 'positional' &&
      cliInputEl &&
      (state.activePayload?.valueType === 'prompt' || state.activePayload?.valueType === 'string')
    ) {
      const el = cliInputEl
      const a = el.selectionStart ?? input.length
      const b = el.selectionEnd ?? input.length
      const hi = Math.max(a, b)
      const mention = kbMentionAtCaret(input, hi)
      suggestionState = {
        ...state,
        currentToken: mention ? mention.token : state.currentToken,
      }
    }
    suggestions = limitCliSuggestions(getSuggestions(suggestionState, activeCommandDef, makeDataSources()))
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
        if (sug.completionSuffix === '-') {
          input = '/' + sug.value + '-'
          updateCommandState()
          focusCliInput()
        } else {
          completeCommand(sug.value)
        }
        return
      case 'slug':
        replaceCurrentToken(sug.value + (sug.completionSuffix ?? ' '))
        return
      case 'kb-type':
        replaceCurrentToken(sug.value)
        return
      case 'kb-key':
        replaceCurrentToken(sug.value + (sug.completionSuffix ?? ' '))
        return
      case 'flag':
        // Insert the flag. If the option defines a default, also insert it so it behaves as typed.
        // (e.g. --module design. keeps kb-id suggestions scoped to design.*)
        if (activeCommandDef?.options && sug.value.startsWith('--')) {
          const optName = sug.value.slice(2)
          const opt = activeCommandDef.options.find((o) => o.name === optName)
          if (opt?.default) {
            const d = opt.default
            const needsTrailingSpace = !d.endsWith('.')
            replaceCurrentToken(`${sug.value} ${d}${needsTrailingSpace ? ' ' : ''}`)
            trySubmitIfCompleteEditReplace()
            return
          }
        }
        replaceCurrentToken(sug.value + ' ')
        trySubmitIfCompleteEditReplace()
        return
      case 'node': {
        const inAddressSlot = currentParseState?.activePayload?.valueType === 'address'
        if (sug.value === '/') {
          replaceCurrentToken(sug.nodeHasChildren ? '/' : '/ ')
        } else {
          replaceCurrentToken(sug.value + (sug.nodeHasChildren ? '/' : ' '))
        }
        if (inAddressSlot) {
          const displayAddr = sug.value.replace(/\/+$/, '') || '/'
          const navAddr = displayAddrToNavAddr(displayAddr)
          if (navAddr && navAddr !== $currentAddress) void navigate?.(navAddr)
        }
        return
      }
      case 'dice-roll':
        replaceCurrentToken(sug.value + (sug.completionSuffix ?? ''))
        return
    }
  }

  function replaceCurrentToken(replacement: string) {
    const state = currentParseState
    const freeformPositional =
      state?.phase === 'positional' &&
      (state.activePayload?.valueType === 'prompt' || state.activePayload?.valueType === 'string')
    if (freeformPositional) {
      const hi = Math.min(Math.max(cliCaretHi, 0), input.length)
      const mention = kbMentionAtCaret(input, hi)
      if (mention) {
        // Replace @token at caret position
        input = input.slice(0, mention.at) + replacement + input.slice(hi)
        const pos = mention.at + replacement.length
        updateCommandState()
        void tick().then(() => {
          focusCliInput()
          cliInputEl?.setSelectionRange(pos, pos)
        })
      } else {
        // Non-mention completions always append to end (flags, etc.)
        const sep = input.endsWith(' ') ? '' : ' '
        input = input + sep + replacement
        const pos = input.length
        updateCommandState()
        void tick().then(() => {
          focusCliInput()
          cliInputEl?.setSelectionRange(pos, pos)
        })
      }
      return
    }

    const trimmed = input.trim()
    const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
    const allTokens = withoutSlash.split(/\s+/).filter(Boolean)
    const endsWithSpace = input.endsWith(' ')

    if (endsWithSpace || allTokens.length <= 1) {
      // Append to end
      input = (endsWithSpace ? input : input + ' ') + replacement
    } else {
      // Replace the last token
      let beforeLastToken = input.slice(0, input.lastIndexOf(allTokens[allTokens.length - 1]!))
      if (replacement.startsWith('-') && beforeLastToken.length > 0 && !beforeLastToken.endsWith(' ')) {
        beforeLastToken += ' '
      }
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
    // Auto-navigate when the user manually drills into an address with /
    if (currentParseState?.activePayload?.valueType === 'address' &&
        currentParseState.currentToken.endsWith('/')) {
      const displayPartial = currentParseState.currentToken.replace(/\/+$/, '') || '/'
      const navAddr = displayAddrToNavAddr(displayPartial)
      if (navAddr && navAddr !== $currentAddress) void navigate?.(navAddr)
    }
  }

  /** Space after ``--replace`` submits ``/edit … --replace`` with no prompt (same as Enter), like line-pick tokens ending with a space. */
  function shouldSpaceSubmitEditReplace(candidateInput: string): boolean {
    const def = COMMAND_DEFINITIONS.find((d) => d.trigger === 'edit')
    if (!def) return false
    if (!candidateInput.trim().startsWith('/')) return false
    const state = parseCliInput(candidateInput, def)
    const args = buildArgs(state, def)
    if (args.options['replace'] !== true) return false
    const prompt = args.positional['prompt'] as string | undefined
    if (prompt !== undefined && String(prompt).trim() !== '') return false
    const addr = args.positional['address']
    const start = args.positional['start']
    const end = args.positional['end']
    if (addr === undefined || start === undefined || end === undefined) return false
    const sn = parseInt(String(start), 10)
    const en = parseInt(String(end), 10)
    if (!Number.isFinite(sn) || !Number.isFinite(en)) return false
    return true
  }

  /** Space after ``--manual`` submits ``/write --manual`` with no prompt (opens append editor). */
  function shouldSpaceSubmitWriteManual(candidateInput: string): boolean {
    const def = COMMAND_DEFINITIONS.find((d) => d.trigger === 'write')
    if (!def) return false
    if (!candidateInput.trim().startsWith('/')) return false
    const state = parseCliInput(candidateInput, def)
    const args = buildArgs(state, def)
    if (args.options['manual'] !== true) return false
    const prompt = args.positional['prompt'] as string | undefined
    if (prompt !== undefined && String(prompt).trim() !== '') return false
    return true
  }

  function trySubmitIfCompleteEditReplace() {
    if (shouldSpaceSubmitEditReplace(input) || shouldSpaceSubmitWriteManual(input)) {
      void submit()
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    const isTouchDevice = typeof window !== 'undefined' && 'ontouchstart' in window
    const trimmed = input.trim()
    const isLogicalEmpty = trimmed === '' || trimmed === '/'

    // Backspace on the session auto-filled command clears to empty and suppresses re-fill.
    if (e.key === 'Backspace' && !sessionFillSuppressed) {
      const sessionOp = $stats?.active_session_operator
      if (sessionOp && (trimmed === '/' + sessionOp || trimmed === '/' + sessionOp + ' ')) {
        e.preventDefault()
        input = ''
        sessionFillSuppressed = true
        updateCommandState()
        return
      }
    }

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

    if (
      e.key === ' ' &&
      !busy &&
      !e.ctrlKey &&
      !e.metaKey &&
      !e.altKey &&
      !e.isComposing
    ) {
      const el = cliInputEl
      if (el) {
        const start = el.selectionStart ?? input.length
        const end = el.selectionEnd ?? input.length
        const candidate = input.slice(0, start) + ' ' + input.slice(end)
        if (shouldSpaceSubmitEditReplace(candidate) || shouldSpaceSubmitWriteManual(candidate)) {
          e.preventDefault()
          input = candidate
          updateCommandState()
          void submit()
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
      if (inputIsMultiLine()) return
      e.preventDefault()
      if (history.length === 0) return
      if (historyIndex === -1) {
        historyIndex = history.length - 1
        input = history[historyIndex] ?? ''
      } else if (historyIndex > 0) {
        historyIndex--
        input = history[historyIndex] ?? ''
      }
      updateCommandState()
      return
    }
    if (e.key === 'ArrowDown') {
      if (inputIsMultiLine()) return
      e.preventDefault()
      if (historyIndex === -1) {
        input = ''
      } else if (historyIndex < history.length - 1) {
        historyIndex++
        input = history[historyIndex] ?? ''
      } else {
        historyIndex = -1
        input = ''
      }
      updateCommandState()
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
    linePickMode.set(null)
    linePickSelection.set(null)
    cliOutput.set(null)
    transactionResult.set(null)

    const handler = resolveHandler(command)
    const def = COMMAND_DEFINITIONS.find((d) => d.trigger === command) ?? null
    const state = parseCliInput(raw, def)
    const args = buildArgs(state, def)

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) { busyMessage = message },
      onDone: onCliDone,
      navigate,
      args,
    }

    try {
      const result: CommandResult = await handler(command, payload, ctx)
      if (result.clearInput) {
        input = ''
        sessionFillSuppressed = false
        updateCommandState()
      }
    } finally {
      busy = false
      await tick()
      focusCliInput()
    }
  }

  // --- Computed hint ---

  // Inject a picked line number into the CLI input
  $: if ($linePickSelection !== null) {
    const n = $linePickSelection
    linePickSelection.set(null)
    replaceCurrentToken(String(n) + ' ')
  }

  $: computedHint = (() => {
    if (!activeCommandDef || !isKnownCommand) return ''
    // While typing a @roll expression in a prompt slot, show a persistent dice hint.
    // The hint covers two phases:
    //   1. currentToken === '@roll'  — user is still on the @roll token itself
    //   2. The word immediately before currentToken in the input is '@roll' — user
    //      has pressed space and is now typing the expression.
    if (currentParseState?.activePayload?.valueType === 'prompt' && currentParseState.phase === 'positional') {
      if (cliInputEl) {
        const a = cliInputEl.selectionStart ?? input.length
        const b = cliInputEl.selectionEnd ?? input.length
        if (promptDiceExpressionHint(input, Math.max(a, b))) return 'dice expression'
      } else {
        const token = currentParseState.currentToken
        if (token === '@roll') return 'dice expression'
        const inputTrimmed = input.trimEnd()
        const beforeCurrent = token
          ? inputTrimmed.slice(0, inputTrimmed.length - token.length).trimEnd()
          : inputTrimmed
        if ((beforeCurrent.split(/\s+/).pop() ?? '') === '@roll') return 'dice expression'
      }
    }
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

  $: cliInputAutocomplete = (() => {
    const s = currentParseState
    if (!s?.activePayload) return 'off'
    const vt = s.activePayload.valueType
    if (vt !== 'string' && vt !== 'prompt') return 'off'
    if (s.phase === 'positional' || s.phase === 'option-value') return 'on'
    return 'off'
  })()
</script>

<div class="bottom-bar" data-testid="bottom-bar" bind:this={bottomBarEl}>
  <CliSuggestions
    {suggestions}
    noWrap={$cliOutput !== null}
    onBeforeSelect={snapshotCaretBeforeChipPointer}
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
        on:keyup={(e) => {
          if (busy) return
          if (
            e.key === 'ArrowLeft' ||
            e.key === 'ArrowRight' ||
            e.key === 'Home' ||
            e.key === 'End' ||
            e.key === 'PageUp' ||
            e.key === 'PageDown'
          ) {
            updateCommandState()
          }
        }}
        on:click={() => {
          if (!busy) updateCommandState()
        }}
        on:select={() => {
          if (!busy) updateCommandState()
        }}
        on:beforeinput={handleBeforeInput}
        on:focus={() => {
          isFocused = true
          updateCommandState()
        }}
        on:blur={(e) => {
          const next = e.relatedTarget
          if (next instanceof Node && bottomBarEl?.contains(next)) {
            return
          }
          isFocused = false
          updateCommandState()
        }}
        rows="1"
        disabled={busy}
        autocomplete={cliInputAutocomplete}
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
