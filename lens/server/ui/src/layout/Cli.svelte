<script lang="ts">
  import { tick, onMount } from 'svelte'
  import { SvelteMap, SvelteSet } from 'svelte/reactivity'
  import type { Attachment } from 'svelte/attachments'
  import type { HTMLTextareaAttributes } from 'svelte/elements'
  import { get } from 'svelte/store'
  import type { CommandContext, CommandResult, CommandDefinition } from '../commands/common'
  import { COMMAND_DEFINITIONS, KNOWN_COMMANDS, resolveHandler } from '../commands/handlers'
  import { parseCliInput, buildArgs } from '../commands/parser'
  import type { ParseState } from '../commands/parser'
  import {
    getCommandSuggestions,
    getSuggestions,
    limitCliSuggestions,
    filterCommandDefinitionsForViewingNode,
    type Suggestion,
    type DataSources,
  } from '../features/cli/CliAutocomplete'
  import CliSuggestions from '../features/cli/CliSuggestions.svelte'
  import {
    cliInputRequest,
    cliOutput,
    cliHistory,
    cliHistoryIndex,
    transactionResult,
    treeRefreshTrigger,
    linePickMode,
    linePickSelection,
    mountCacheRefreshTrigger,
    scrollContentToBottom,
  } from '../stores/ui'
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import { currentProject } from '../stores/project'
  import { parsedHash } from '../stores/parsedHash'
  import { vnModeFromParsed, vnPlayback, vnCursorCliOpSnapshot } from '../stores/visualNovel'
  import {
    exitVisualNovel,
    resolveVisualNovelIndex,
    resolveVisualNovelTtsSettings,
  } from '../utils/vnNavigate'
  import { playbackTailTextId } from '../utils/vnCursorCli'
  import { vnNavigableIndices } from '../utils/vnPlaybackNav'
  import { getKbItems, getTree, browseMountDir } from '../services/api'
  import type { TreeNode, MountEntry } from '../services/api'
  import {
    kbMentionAtCaret,
    promptDiceExpressionHint,
    promptNodeMentionLinePickAtCaret,
  } from '../utils/cliCaret'

  type Props = {
    onCliDone?: () => Promise<void>
    navigate?: (addr: string) => Promise<void>
    syncLocation?: (addr: string) => void
  }

  const MAX_HISTORY = 50
  /** Command token after `/`; with the CLI's leading slash this spells `/@cursor`, same as `lens.core.address._CURSOR_REF`. */
  const GO_CURSOR_CHIP = '@cursor'

  let {
    onCliDone = undefined,
    navigate = undefined,
    syncLocation = undefined,
  }: Props = $props()

  let input = $state('')
  let busy = $state(false)
  let busyMessage = $state<string | null>(null)
  let suggestions = $state.raw<Suggestion[]>([])
  let isKnownCommand = $state(true)
  let flashInvalid = $state(false)
  let showInvalid = $state(false)
  let activeCommandDef = $state.raw<CommandDefinition | null>(null)
  let currentParseState = $state.raw<ParseState | null>(null)
  /** Caret end position, kept fresh so chip clicks can find @-mentions after textarea blurs. */
  let cliCaretHi = $state(0)

  let cliInputEl: HTMLTextAreaElement | null = null
  let isFocused = false
  let lastAutoFilledCommand: string | null = null
  let addressAutoFilled = false
  let sessionFillSuppressed = false
  let lastSessionOperator: string | null = null
  /** `undefined` = initial; used to detect navigation away from the narrative cursor. */
  let prevCliNavAddress: string | null | undefined = undefined
  /** One-cycle caret override for programmatic token replacement before DOM selection catches up. */
  let pendingCliCaretHi: number | null = null
  let lastProject: string | null = null

  let kbKeyCache = new SvelteMap<string, string[]>()
  let nodeTreeCache: TreeNode[] | null = null
  let nodeTreeFetchPending = false
  let mountDirCache = new SvelteMap<string, MountEntry[]>()
  let mountDirFetchPending = new SvelteSet<string>()

  function captureCliCaret() {
    if (pendingCliCaretHi !== null) {
      cliCaretHi = Math.min(Math.max(pendingCliCaretHi, 0), input.length)
      return
    }
    if (!cliInputEl) return
    const n = input.length
    cliCaretHi = Math.min(Math.max(cliInputEl.selectionEnd ?? n, cliInputEl.selectionStart ?? n), n)
  }

  /** Snapshot caret on chip pointerdown (before blur can clear textarea selection). */
  function snapshotCaretBeforeChipPointer() {
    if (cliInputEl && document.activeElement === cliInputEl) captureCliCaret()
  }

  const attachCliInputEl: Attachment<HTMLTextAreaElement> = (element) => {
    cliInputEl = element
    return () => {
      if (cliInputEl === element) {
        cliInputEl = null
      }
    }
  }

  function resetTreeCaches() {
    nodeTreeCache = null
    nodeTreeFetchPending = false
    kbKeyCache = new SvelteMap()
  }

  function resetMountCaches() {
    mountDirCache = new SvelteMap()
    mountDirFetchPending = new SvelteSet()
  }

  function resizeCliInput() {
    if (!cliInputEl) return
    requestAnimationFrame(() => {
      if (!cliInputEl) return
      cliInputEl.style.height = '0px'
      const maxHeightPx = window.innerHeight ? Math.round(window.innerHeight * 0.4) : 240
      const newHeight = Math.min(cliInputEl.scrollHeight + 3, maxHeightPx)
      cliInputEl.style.height = `${newHeight}px`
    })
  }

  function scheduleResize() {
    void tick().then(() => resizeCliInput())
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

  function handleSessionOperatorChange(newOp: string | null) {
    if (newOp !== lastSessionOperator) {
      lastSessionOperator = newOp
      sessionFillSuppressed = false
      updateCommandState()
    }
  }

  function handleProjectChange(project: string | null) {
    if (project !== lastProject) {
      if (lastProject !== null) {
        input = ''
        sessionFillSuppressed = false
        lastAutoFilledCommand = null
        scheduleResize()
      }
      lastProject = project
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

  function isFocusCliShortcut(event: KeyboardEvent): boolean {
    if (event.code !== 'Backquote') return false
    if (!event.ctrlKey || event.metaKey || event.altKey) return false
    if (event.shiftKey) return false
    return true
  }

  function globalKeydownFocusCli(event: KeyboardEvent) {
    if (busy || event.defaultPrevented || event.isComposing) return
    if (!isFocusCliShortcut(event)) return
    const target = event.target
    if (target instanceof HTMLElement && target.closest('dialog[open]')) return
    event.preventDefault()
    event.stopPropagation()
    focusCliInput()
    updateCommandState()
  }

  function clearAppViewportOverride() {
    const app = document.getElementById('app')
    if (!app) return
    app.style.height = ''
    app.style.marginTop = ''
  }

  /** Keep the bottom bar visible when the iOS virtual keyboard opens.
   *  Safari shrinks the visual viewport but leaves the layout viewport
   *  unchanged, so a flex-based bottom bar ends up hidden behind the
   *  keyboard. We shrink the shell to the visible viewport height. */
  function handleViewportResize() {
    const vv = window.visualViewport
    if (!vv) return
    const visibleHeight = vv.height
    const app = document.getElementById('app')
    if (!app) return
    const delta = window.innerHeight - visibleHeight - vv.offsetTop
    if (delta > 50) {
      app.style.height = `${visibleHeight}px`
      app.style.marginTop = `${vv.offsetTop}px`
      window.scrollTo(0, 0)
      return
    }
    clearAppViewportOverride()
  }

  function handleNavigationTracking(addr: string | null, nextStats = get(stats)) {
    const cursorAddr = nextStats?.cursor ?? null
    const sessionOp = nextStats?.active_session_operator
    if (prevCliNavAddress !== undefined && cursorAddr !== null && sessionOp) {
      const leftCursor = prevCliNavAddress === cursorAddr && addr !== null && addr !== cursorAddr
      if (leftCursor && cliContainsOnlySessionOperator(sessionOp)) {
        input = '/'
        sessionFillSuppressed = false
        updateCommandState()
        scheduleResize()
      }
    }
    prevCliNavAddress = addr
  }

  onMount(() => {
    const unsubscribe = cliInputRequest.subscribe((value) => {
      if (value === null) return
      input = value
      cliInputRequest.set(null)
      void tick().then(() => {
        updateCommandState()
        focusCliInput()
        resizeCliInput()
      })
    })
    const unsubscribeTreeRefresh = treeRefreshTrigger.subscribe(() => {
      resetTreeCaches()
    })
    const unsubscribeMountRefresh = mountCacheRefreshTrigger.subscribe(() => {
      resetMountCaches()
    })
    const unsubscribeProject = currentProject.subscribe((project) => {
      handleProjectChange(project)
    })
    const unsubscribeStats = stats.subscribe((nextStats) => {
      handleSessionOperatorChange(nextStats?.active_session_operator ?? null)
      handleNavigationTracking(get(currentAddress), nextStats)
    })
    const unsubscribeAddress = currentAddress.subscribe((addr) => {
      handleNavigationTracking(addr, get(stats))
    })
    const unsubscribeLinePickSelection = linePickSelection.subscribe((selectedLine) => {
      if (selectedLine === null) return
      linePickSelection.set(null)
      replaceCurrentToken(String(selectedLine) + ' ')
    })

    const vv = window.visualViewport
    vv?.addEventListener('resize', handleViewportResize)
    vv?.addEventListener('scroll', handleViewportResize)
    void tick().then(() => resizeCliInput())

    return () => {
      unsubscribe()
      unsubscribeTreeRefresh()
      unsubscribeMountRefresh()
      unsubscribeProject()
      unsubscribeStats()
      unsubscribeAddress()
      unsubscribeLinePickSelection()
      vv?.removeEventListener('resize', handleViewportResize)
      vv?.removeEventListener('scroll', handleViewportResize)
      clearAppViewportOverride()
    }
  })

  function pushHistory(command: string) {
    if (!command) return
    cliHistory.update((history) => [...history, command].slice(-MAX_HISTORY))
    cliHistoryIndex.set(-1)
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

  /** When off the narrative cursor, show the @cursor chip for empty input or while typing a matching prefix. */
  function goCursorChipMatchesToken(commandToken: string): boolean {
    const prefix = commandToken.toLowerCase()
    if (prefix === '') return true
    if (GO_CURSOR_CHIP.startsWith(prefix)) return true
    if (GO_CURSOR_CHIP.slice(1).startsWith(prefix)) return true
    return false
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

  function cliContainsOnlySessionOperator(sessionOp: string): boolean {
    const { command, payload } = parseCommandAndPayload(input)
    return command === sessionOp.toLowerCase() && payload.trim() === ''
  }

  function fetchKbKeys(type: string) {
    if (kbKeyCache.has(type)) return
    getKbItems({ type })
      .then((items) => {
        const keys = items.map((item) => item.id.slice(item.id.indexOf('.') + 1))
        kbKeyCache = new SvelteMap(kbKeyCache).set(type, keys)
        updateCommandState()
      })
      .catch(() => {
        kbKeyCache = new SvelteMap(kbKeyCache).set(type, [])
      })
  }

  function fetchMountDir(path: string) {
    if (mountDirFetchPending.has(path)) return
    mountDirFetchPending = new SvelteSet(mountDirFetchPending).add(path)
    browseMountDir(path)
      .then((entries) => {
        mountDirCache = new SvelteMap(mountDirCache).set(path, entries)
        updateCommandState()
      })
      .catch(() => {
        mountDirCache = new SvelteMap(mountDirCache).set(path, [])
      })
      .finally(() => {
        const nextPending = new SvelteSet(mountDirFetchPending)
        nextPending.delete(path)
        mountDirFetchPending = nextPending
      })
  }

  function fetchNodeTree() {
    if (nodeTreeFetchPending || nodeTreeCache !== null) return
    nodeTreeFetchPending = true
    getTree()
      .then((tree) => {
        nodeTreeCache = tree
        updateCommandState()
      })
      .catch(() => {
        nodeTreeCache = []
      })
      .finally(() => {
        nodeTreeFetchPending = false
      })
  }

  function makeDataSources(): DataSources {
    const cursorAddr = $stats?.cursor ?? null
    const viewingAtProjectCursor = cursorAddr === null || $currentAddress === cursorAddr
    return {
      kbTypes: $stats?.kb_types ?? [],
      kbKeyCache,
      fetchKbKeys,
      nodeTree: nodeTreeCache,
      fetchNodeTree,
      stats: $stats,
      mountDirCache,
      fetchMountDir,
      viewingAtProjectCursor,
    }
  }

  function updateCommandState() {
    scheduleResize()
    const trimmed = input.trim()

    const cursorAddr = $stats?.cursor ?? null
    const viewingAtProjectCursor = cursorAddr === null || $currentAddress === cursorAddr
    const viewingOffCursorNode = cursorAddr !== null && $currentAddress !== cursorAddr

    if ((trimmed === '' || trimmed === '/') && !sessionFillSuppressed && !viewingOffCursorNode) {
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

    isKnownCommand = !hasCommandText || KNOWN_COMMANDS.includes(lower) || goCursorChipMatchesToken(lower)
    showInvalid =
      !busy &&
      startsWithSlash &&
      hasCommandText &&
      !isKnownCommand &&
      !KNOWN_COMMANDS.some((command) => command.startsWith(lower)) &&
      !goCursorChipMatchesToken(lower)

    activeCommandDef = hasCommandText
      ? (COMMAND_DEFINITIONS.find((definition) => definition.trigger === lower) ?? null)
      : null

    const state = parseCliInput(input, activeCommandDef)
    currentParseState = state
    if (isFocused && cliInputEl) {
      captureCliCaret()
    }

    const currentTrigger = activeCommandDef?.trigger ?? null
    if (currentTrigger !== lastAutoFilledCommand) {
      lastAutoFilledCommand = currentTrigger
      addressAutoFilled = false
    }

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

    const activeType = state.activePayload?.valueType
    if (activeType === 'line' && activeCommandDef) {
      const addrPos = activeCommandDef.positional?.find((payload) => payload.valueType === 'address')
      const displayAddr = addrPos
        ? (state.completedPositional[addrPos.name] as string | undefined)
        : undefined
      if (displayAddr) {
        fetchNodeTree()
        const navAddr = displayAddrToNavAddr(displayAddr)
        if (navAddr) {
          const payloadName = state.activePayload?.name
          const isEndPick = payloadName === 'end'
          const startVal = isEndPick
            ? parseInt(state.completedPositional['start'] as string, 10)
            : undefined
          const trigger = activeCommandDef.trigger
          const mediaAttach =
            trigger === 'media' &&
            (state.completedPositional['action'] as string | undefined) === 'attach'
          const operatorMode: 'edit' | 'attach' | undefined =
            trigger === 'edit' ? 'edit' : mediaAttach ? 'attach' : undefined

          linePickMode.set({
            address: navAddr,
            startLine: isEndPick && startVal && !isNaN(startVal) ? startVal : undefined,
            operatorMode,
          })
          if (navAddr !== $currentAddress) void navigate?.(navAddr)
        }
      } else {
        linePickMode.set(null)
        linePickSelection.set(null)
      }
    } else if (activeType === 'prompt' || activeType === 'string') {
      const mentionPick = promptNodeMentionLinePickAtCaret(input, cliCaretHi)
      if (mentionPick) {
        if (mentionPick.endLine !== undefined) {
          linePickMode.set(null)
          linePickSelection.set(null)
          return
        }
        fetchNodeTree()
        const navAddr = displayAddrToNavAddr(mentionPick.address)
        if (navAddr) {
          linePickMode.set({
            address: navAddr,
            startLine: mentionPick.startLine,
            operatorMode: undefined,
          })
          if (navAddr !== $currentAddress) void navigate?.(navAddr)
        }
      } else {
        linePickMode.set(null)
        linePickSelection.set(null)
      }
    } else {
      linePickMode.set(null)
      linePickSelection.set(null)
    }

    if (!isFocused) {
      suggestions = []
      return
    }

    if (state.phase === 'command') {
      const defsForView = filterCommandDefinitionsForViewingNode(
        COMMAND_DEFINITIONS,
        viewingAtProjectCursor
      )
      let commandSuggestions = getCommandSuggestions(defsForView, state.currentToken)
      if (viewingOffCursorNode && cursorAddr && goCursorChipMatchesToken(state.currentToken)) {
        const goCursor: Suggestion = {
          label: '@cursor',
          value: '@cursor',
          kind: 'go-cursor',
          group: 'cli',
        }
        commandSuggestions = [goCursor, ...commandSuggestions]
      }
      suggestions = limitCliSuggestions(commandSuggestions)
      return
    }

    if (!activeCommandDef) {
      suggestions = []
      return
    }

    if (activeCommandDef.hint && state.phase === 'positional' && !state.activePayload) {
      suggestions = []
      return
    }

    let suggestionState = state
    if (
      state.phase === 'positional' &&
      cliInputEl &&
      (state.activePayload?.valueType === 'prompt' || state.activePayload?.valueType === 'string')
    ) {
      const mention = kbMentionAtCaret(input, cliCaretHi)
      suggestionState = {
        ...state,
        currentToken: mention ? mention.token : state.currentToken,
      }
    }

    suggestions = limitCliSuggestions(
      getSuggestions(suggestionState, activeCommandDef, makeDataSources())
    )
  }

  function completeCommand(command: string) {
    const { payload } = parseCommandAndPayload(input)
    input = `/${command}${payload ? ` ${payload}` : ' '}`
    updateCommandState()
    focusCliInput()
  }

  function commandHasNoCliParameters(definition: CommandDefinition | undefined): boolean {
    if (!definition) return false
    return (definition.positional?.length ?? 0) === 0 && (definition.options?.length ?? 0) === 0
  }

  /** Chip click/tap only: run immediately when picking a zero-arity command or @cursor. Tab still uses completeSuggestion. */
  function suggestionChipRunsImmediately(suggestion: Suggestion): boolean {
    if (suggestion.kind === 'go-cursor') return true
    if (suggestion.kind !== 'command') return false
    if (suggestion.completionSuffix !== ' ') return false
    const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === suggestion.value)
    return commandHasNoCliParameters(definition)
  }

  function handleSuggestionChipClick(suggestion: Suggestion) {
    if (busy) return
    if (suggestionChipRunsImmediately(suggestion)) {
      input = suggestion.kind === 'go-cursor' ? `/${GO_CURSOR_CHIP}` : `/${suggestion.value}`
      updateCommandState()
      void tick().then(() => void submit())
      return
    }
    completeSuggestion(suggestion)
  }

  function completeSuggestion(suggestion: Suggestion) {
    switch (suggestion.kind) {
      case 'go-cursor':
        completeCommand(GO_CURSOR_CHIP)
        return
      case 'command':
        if (suggestion.completionSuffix === '-') {
          input = '/' + suggestion.value + '-'
          updateCommandState()
          focusCliInput()
        } else {
          completeCommand(suggestion.value)
        }
        return
      case 'slug':
        replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '))
        return
      case 'kb-type':
        replaceCurrentToken(suggestion.value)
        return
      case 'kb-key':
        replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '))
        return
      case 'flag':
        if (activeCommandDef?.options && suggestion.value.startsWith('--')) {
          const optionName = suggestion.value.slice(2)
          const option = activeCommandDef.options.find((item) => item.name === optionName)
          if (option?.default) {
            const defaultValue = option.default
            const needsTrailingSpace = !defaultValue.endsWith('.')
            replaceCurrentToken(
              `${suggestion.value} ${defaultValue}${needsTrailingSpace ? ' ' : ''}`
            )
            trySubmitIfCompleteEditReplace()
            return
          }
        }
        replaceCurrentToken(suggestion.value + ' ')
        trySubmitIfCompleteEditReplace()
        return
      case 'node': {
        const inAddressSlot = currentParseState?.activePayload?.valueType === 'address'
        if (suggestion.value === '/') {
          replaceCurrentToken(suggestion.nodeHasChildren ? '/' : '/ ')
        } else {
          replaceCurrentToken(suggestion.value + (suggestion.nodeHasChildren ? '/' : ' '))
        }
        if (inAddressSlot) {
          const displayAddr = suggestion.value.replace(/\/+$/, '') || '/'
          const navAddr = displayAddrToNavAddr(displayAddr)
          if (navAddr && navAddr !== $currentAddress) void navigate?.(navAddr)
        }
        return
      }
      case 'dice-roll':
      case 'time-now':
        replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ''))
        return
      case 'var-prefix':
        replaceCurrentToken(suggestion.value)
        return
      case 'var-key':
        replaceCurrentToken(suggestion.value + (suggestion.completionSuffix ?? ' '))
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
        let mentionEnd = mention.at
        while (mentionEnd < input.length && !/\s/.test(input[mentionEnd]!)) mentionEnd += 1
        input = input.slice(0, mention.at) + replacement + input.slice(mentionEnd)
        const pos = mention.at + replacement.length
        pendingCliCaretHi = pos
        cliCaretHi = pos
        updateCommandState()
        void tick().then(() => {
          focusCliInput()
          cliInputEl?.setSelectionRange(pos, pos)
          cliCaretHi = pos
          pendingCliCaretHi = null
        })
      } else {
        const separator = input.endsWith(' ') ? '' : ' '
        input = input + separator + replacement
        const pos = input.length
        pendingCliCaretHi = pos
        cliCaretHi = pos
        updateCommandState()
        void tick().then(() => {
          focusCliInput()
          cliInputEl?.setSelectionRange(pos, pos)
          cliCaretHi = pos
          pendingCliCaretHi = null
        })
      }
      return
    }

    const trimmed = input.trim()
    const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
    const allTokens = withoutSlash.split(/\s+/).filter(Boolean)
    const endsWithSpace = input.endsWith(' ')

    if (endsWithSpace || allTokens.length <= 1) {
      input = (endsWithSpace ? input : input + ' ') + replacement
    } else {
      let beforeLastToken = input.slice(0, input.lastIndexOf(allTokens[allTokens.length - 1]!))
      if (replacement.startsWith('-') && beforeLastToken.length > 0 && !beforeLastToken.endsWith(' ')) {
        beforeLastToken += ' '
      }
      input = beforeLastToken + replacement
    }
    updateCommandState()
    pendingCliCaretHi = null
    focusCliInput()
  }

  function handleInput(event: Event) {
    if (!(event.target instanceof HTMLTextAreaElement)) return
    let value = event.target.value
    if (!value.startsWith('/')) {
      value = '/' + value.replace(/^\/+/, '')
    }
    input = value
    updateCommandState()
    if (
      currentParseState?.activePayload?.valueType === 'address' &&
      currentParseState.currentToken.endsWith('/')
    ) {
      const displayPartial = currentParseState.currentToken.replace(/\/+$/, '') || '/'
      const navAddr = displayAddrToNavAddr(displayPartial)
      if (navAddr && navAddr !== $currentAddress) void navigate?.(navAddr)
    }
  }

  /** Space after ``--replace`` submits ``/edit … --replace`` with no prompt (same as Enter), like line-pick tokens ending with a space. */
  function shouldSpaceSubmitEditReplace(candidateInput: string): boolean {
    const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === 'edit')
    if (!definition) return false
    if (!candidateInput.trim().startsWith('/')) return false
    const state = parseCliInput(candidateInput, definition)
    const args = buildArgs(state, definition)
    if (args.options['replace'] !== true) return false
    const prompt = args.positional['prompt'] as string | undefined
    if (prompt !== undefined && String(prompt).trim() !== '') return false
    const addr = args.positional['address']
    const start = args.positional['start']
    const end = args.positional['end']
    if (addr === undefined || start === undefined || end === undefined) return false
    const startNumber = parseInt(String(start), 10)
    const endNumber = parseInt(String(end), 10)
    if (!Number.isFinite(startNumber) || !Number.isFinite(endNumber)) return false
    return true
  }

  /** Space after ``--manual`` submits ``/write --manual`` with no prompt (opens append editor). */
  function shouldSpaceSubmitWriteManual(candidateInput: string): boolean {
    const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === 'write')
    if (!definition) return false
    if (!candidateInput.trim().startsWith('/')) return false
    const state = parseCliInput(candidateInput, definition)
    const args = buildArgs(state, definition)
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

  function handleKeydown(event: KeyboardEvent) {
    const isTouchDevice = typeof window !== 'undefined' && 'ontouchstart' in window
    const trimmed = input.trim()
    const isLogicalEmpty = trimmed === '' || trimmed === '/'

    if (event.key === 'Backspace' && !sessionFillSuppressed) {
      const sessionOp = $stats?.active_session_operator
      if (sessionOp && (trimmed === '/' + sessionOp || trimmed === '/' + sessionOp + ' ')) {
        event.preventDefault()
        input = ''
        sessionFillSuppressed = true
        let leftSceneCliBeat = false
        const slug = get(currentProject)
        const addr = get(currentAddress)
        if (slug && addr) {
          const ph = get(parsedHash)
          const items = get(vnPlayback)?.items ?? []
          if (
            vnModeFromParsed(ph, slug, addr) &&
            items.length > 0 &&
            resolveVisualNovelIndex(ph, slug, addr) === vnNavigableIndices(items).length
          ) {
            exitVisualNovel(
              slug,
              addr,
              vnNavigableIndices(items).length,
              resolveVisualNovelTtsSettings(ph)
            )
            leftSceneCliBeat = true
          }
        }
        updateCommandState()
        if (leftSceneCliBeat) {
          void tick().then(() => {
            cliInputRequest.set('')
            scrollContentToBottom.update((count) => count + 1)
          })
        } else {
          void tick().then(() => focusCliInput())
        }
        return
      }
    }

    if (isLogicalEmpty) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        if (isTouchDevice) cliInputEl?.blur()
        return
      }
      if (event.key === 'Backspace') {
        if ($cliOutput) {
          event.preventDefault()
          cliOutput.set(null)
          return
        }
        if (isTouchDevice) {
          event.preventDefault()
          cliInputEl?.blur()
          return
        }
      }
    }

    if (
      event.key === ' ' &&
      !busy &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !event.isComposing
    ) {
      const el = cliInputEl
      if (el) {
        const start = el.selectionStart ?? input.length
        const end = el.selectionEnd ?? input.length
        const candidate = input.slice(0, start) + ' ' + input.slice(end)
        if (shouldSpaceSubmitEditReplace(candidate) || shouldSpaceSubmitWriteManual(candidate)) {
          event.preventDefault()
          input = candidate
          updateCommandState()
          void submit()
          return
        }
      }
    }

    if (event.key === 'Tab' && !event.shiftKey && suggestions.length > 0) {
      event.preventDefault()
      const first = suggestions[0]
      if (!first) return
      if (first.kind === 'command') {
        const { command } = parseCommandAndPayload(input)
        if (command && KNOWN_COMMANDS.includes(command)) {
          const idx = KNOWN_COMMANDS.findIndex((item) => item === command)
          const next = idx === -1 ? 0 : (idx + 1) % KNOWN_COMMANDS.length
          completeCommand(KNOWN_COMMANDS[next] ?? KNOWN_COMMANDS[0] ?? '')
          return
        }
      }
      completeSuggestion(first)
      return
    }

    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
      return
    }

    if (event.key === 'ArrowUp') {
      if (inputIsMultiLine()) return
      event.preventDefault()
      if ($cliHistory.length === 0) return
      if ($cliHistoryIndex === -1) {
        cliHistoryIndex.set($cliHistory.length - 1)
        input = $cliHistory[$cliHistory.length - 1] ?? ''
      } else if ($cliHistoryIndex > 0) {
        cliHistoryIndex.set($cliHistoryIndex - 1)
        input = $cliHistory[$cliHistoryIndex - 1] ?? ''
      }
      updateCommandState()
      return
    }

    if (event.key === 'ArrowDown') {
      if (inputIsMultiLine()) return
      event.preventDefault()
      if ($cliHistoryIndex === -1) {
        input = ''
      } else if ($cliHistoryIndex < $cliHistory.length - 1) {
        cliHistoryIndex.set($cliHistoryIndex + 1)
        input = $cliHistory[$cliHistoryIndex + 1] ?? ''
      } else {
        cliHistoryIndex.set(-1)
        input = ''
      }
      updateCommandState()
    }
  }

  function handleKeyup(event: KeyboardEvent) {
    if (busy) return
    if (
      event.key === 'ArrowLeft' ||
      event.key === 'ArrowRight' ||
      event.key === 'Home' ||
      event.key === 'End' ||
      event.key === 'PageUp' ||
      event.key === 'PageDown'
    ) {
      updateCommandState()
    }
  }

  function handleSelectionRefresh() {
    if (!busy) updateCommandState()
  }

  function handleBeforeInput(event: InputEvent) {
    if (busy) return
    if (event.isComposing) return
    if (event.inputType === 'insertLineBreak' || event.inputType === 'insertParagraph') {
      event.preventDefault()
      void submit()
    }
  }

  function handleFocus() {
    isFocused = true
    updateCommandState()
  }

  function handleBlur(event: FocusEvent) {
    const next = event.relatedTarget
    const container = (event.currentTarget as HTMLTextAreaElement | null)?.closest('.bottom-bar')
    if (next instanceof Node && container?.contains(next)) {
      return
    }
    isFocused = false
    updateCommandState()
  }

  async function submit() {
    const raw = input.trim()
    if (raw === '') {
      if (typeof window !== 'undefined' && 'ontouchstart' in window) cliInputEl?.blur()
      return
    }

    const { command, payload } = parseCommandAndPayload(raw)
    if (!command) return

    if (command === GO_CURSOR_CHIP) {
      if (payload.trim() !== '') {
        flashInvalid = true
        showInvalid = true
        setTimeout(() => {
          flashInvalid = false
        }, 150)
        focusCliInput()
        return
      }
      const cursor = get(stats)?.cursor
      if (!cursor || !navigate) {
        flashInvalid = true
        showInvalid = true
        setTimeout(() => {
          flashInvalid = false
        }, 150)
        focusCliInput()
        return
      }
      pushHistory(raw)
      try {
        await navigate(cursor)
        scrollContentToBottom.update((count) => count + 1)
        input = ''
        sessionFillSuppressed = false
        updateCommandState()
      } catch (error) {
        console.error('Navigation failed:', error)
      }
      await tick()
      focusCliInput()
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
    linePickMode.set(null)
    linePickSelection.set(null)
    cliOutput.set(null)
    transactionResult.set(null)

    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (slug && addr && (command === 'play' || command === 'chat')) {
      const ph = get(parsedHash)
      const items = get(vnPlayback)?.items ?? []
      if (
        vnModeFromParsed(ph, slug, addr) &&
        items.length > 0 &&
        resolveVisualNovelIndex(ph, slug, addr) === vnNavigableIndices(items).length
      ) {
        vnCursorCliOpSnapshot.set({
          address: addr,
          itemCount: items.length,
          lastTextId: playbackTailTextId(items),
        })
      }
    }

    const handler = resolveHandler(command)
    const definition = COMMAND_DEFINITIONS.find((item) => item.trigger === command) ?? null
    const state = parseCliInput(raw, definition)
    const args = buildArgs(state, definition)

    const ctx: CommandContext = {
      setBusyMessage(message: string | null) {
        busyMessage = message
      },
      onDone: onCliDone,
      navigate,
      syncLocation,
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
      busyMessage = null
      await tick()
      focusCliInput()
    }
  }

  const computedHint = $derived.by(() => {
    if (!activeCommandDef || !isKnownCommand) return ''
    if (
      currentParseState?.activePayload?.valueType === 'prompt' &&
      currentParseState.phase === 'positional' &&
      promptDiceExpressionHint(input, cliCaretHi)
    ) {
      return 'dice expression'
    }
    const activeHint = currentParseState?.activePayload?.hint
    if (activeHint) return activeHint
    const trimmed = input.trim()
    const withoutSlash = trimmed.startsWith('/') ? trimmed.slice(1) : trimmed
    const hasPayload = withoutSlash.split(/\s+/).filter(Boolean).length > 1
    if (!hasPayload) return activeCommandDef.hint ?? ''
    return ''
  })

  const showHint = $derived(Boolean(computedHint) && isKnownCommand)
  const cliInputAutocomplete = $derived.by((): HTMLTextareaAttributes['autocomplete'] => {
    const state = currentParseState
    if (!state?.activePayload) return 'off'
    const valueType = state.activePayload.valueType
    if (valueType !== 'string' && valueType !== 'prompt') return 'off'
    if (state.phase === 'positional' || state.phase === 'option-value') return 'on'
    return 'off'
  })
  const cliInputPromptAssistEnabled = $derived.by(() => {
    const state = currentParseState
    if (!state?.activePayload) return false
    if (state.activePayload.valueType !== 'prompt') return false
    return state.phase === 'positional' || state.phase === 'option-value'
  })
  const cliInputAutocorrect = $derived.by((): HTMLTextareaAttributes['autocorrect'] =>
    cliInputPromptAssistEnabled ? 'on' : 'off'
  )
  const cliInputAutocapitalize = $derived.by((): HTMLTextareaAttributes['autocapitalize'] =>
    cliInputPromptAssistEnabled ? 'sentences' : 'off'
  )
  const cliInputSpellcheck = $derived(cliInputPromptAssistEnabled)
</script>

<svelte:window onkeydowncapture={globalKeydownFocusCli} />

<div class="bottom-bar" data-testid="bottom-bar">
  <CliSuggestions
    {suggestions}
    noWrap={$cliOutput !== null}
    onBeforeSelect={snapshotCaretBeforeChipPointer}
    onSelect={handleSuggestionChipClick}
  />
  <div class="cli-input-row">
    <div class="cli-input-wrapper">
      <textarea
        {@attach attachCliInputEl}
        class={['cli-input', { invalid: showInvalid, 'flash-invalid': flashInvalid }]}
        bind:value={input}
        oninput={handleInput}
        onkeydown={handleKeydown}
        onkeyup={handleKeyup}
        onclick={handleSelectionRefresh}
        onselect={handleSelectionRefresh}
        onbeforeinput={handleBeforeInput}
        onfocus={handleFocus}
        onblur={handleBlur}
        rows="1"
        disabled={busy}
        autocomplete={cliInputAutocomplete}
        autocorrect={cliInputAutocorrect}
        autocapitalize={cliInputAutocapitalize}
        spellcheck={cliInputSpellcheck}
        data-testid="cli-input"
      ></textarea>
      {#if showHint}
        <div class="cli-input-ghost" aria-hidden="true"><span class="ghost-spacer">{input}</span>&nbsp;<span class="ghost-hint">{computedHint}</span></div>
      {/if}
    </div>
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
