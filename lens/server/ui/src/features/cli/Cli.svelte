<script lang="ts">
  import { tick, onMount } from 'svelte'
  import type { Attachment } from 'svelte/attachments'
  import { get } from 'svelte/store'
  import type { CommandDefinition } from '../../commands/common'
  import type { ParseState } from '../../commands/parser'
  import type { Suggestion } from './CliAutocomplete'
  import CliSuggestions from './CliSuggestions.svelte'
  import CliHistoryDrawer from './CliHistoryDrawer.svelte'
  import CliInputField from './CliInputField.svelte'
  import { CliDataSources } from './cliDataSources'
  import { runCliCommandState } from './cliStateRunner'
  import {
    buildSubmitDeps,
    buildSuggestionApplyDeps,
    handleCliBeforeInput,
    handleCliBlur,
    handleCliFocus,
    handleCliInputKeydown,
    handleCliInputKeyup,
    handleCliSuggestionChipClick,
    handleCliTextInput,
    type CliComponentRefs,
  } from './cliComponentHandlers'
  import { isFocusCliShortcut } from './cliKeyboard'
  import { submitCliCommand } from './cliSubmit'
  import { setupCliLifecycle } from './cliLifecycle'
  import { computeCliHint, computeCliInputAttrs, scheduleCliResize, setupIosViewportHandler } from './cliInputHints'
  import { cliHistory, cliOutput, linePickMode, linePickSelection, guideModalCommand } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { stats } from '../../stores/stats'

  type Props = {
    onCliDone?: () => Promise<void>
    navigate?: (addr: string) => Promise<void>
    syncLocation?: (addr: string) => void
  }

  let { onCliDone = undefined, navigate = undefined, syncLocation = undefined }: Props = $props()

  let input = $state('')
  let busy = $state(false)
  let busyMessage = $state<string | null>(null)
  let suggestions = $state.raw<Suggestion[]>([])
  let isKnownCommand = $state(true)
  let flashInvalid = $state(false)
  let showInvalid = $state(false)
  let activeCommandDef = $state.raw<CommandDefinition | null>(null)
  let currentParseState = $state.raw<ParseState | null>(null)
  let cliCaretHi = $state(0)

  let historyOpen = $state(false)
  let cliInputEl: HTMLTextAreaElement | null = null
  let isFocused = false
  let lastAutoFilledCommand: string | null = null
  let addressAutoFilled = false
  let sessionFillSuppressed = false
  let lastSessionOperator: string | null = null
  let prevCliNavAddress: string | null | undefined = undefined
  let pendingCliCaretHi: number | null = null
  let lastProject: string | null = null

  const dataSources = new CliDataSources()

  function captureCliCaret() {
    if (pendingCliCaretHi !== null) {
      cliCaretHi = Math.min(Math.max(pendingCliCaretHi, 0), input.length)
      return
    }
    if (!cliInputEl) return
    const n = input.length
    cliCaretHi = Math.min(Math.max(cliInputEl.selectionEnd ?? n, cliInputEl.selectionStart ?? n), n)
  }

  function snapshotCaretBeforeChipPointer() {
    if (cliInputEl && document.activeElement === cliInputEl) captureCliCaret()
  }

  const attachCliInputEl: Attachment<HTMLTextAreaElement> = (element) => {
    cliInputEl = element
    return () => {
      if (cliInputEl === element) cliInputEl = null
    }
  }

  function resizeCliInput() {
    if (!cliInputEl) return
    requestAnimationFrame(() => {
      if (!cliInputEl) return
      cliInputEl.style.height = '0px'
      const maxHeightPx = window.innerHeight ? Math.round(window.innerHeight * 0.4) : 240
      cliInputEl.style.height = `${Math.min(cliInputEl.scrollHeight + 3, maxHeightPx)}px`
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

  function focusCliInput() {
    if (!cliInputEl) return
    try {
      cliInputEl.focus({ preventScroll: true })
    } catch {
      cliInputEl.focus()
    }
  }

  function updateCommandState() {
    scheduleCliResize(resizeCliInput)
    const bundle = runCliCommandState(
      {
        input,
        isKnownCommand,
        showInvalid,
        activeCommandDef,
        currentParseState,
        suggestions,
        addressAutoFilled,
        lastAutoFilledCommand,
      },
      {
        busy,
        isFocused,
        sessionFillSuppressed,
        cliCaretHi,
        hasCliInputEl: cliInputEl !== null,
        captureCliCaret,
        dataSources,
        onUpdate: updateCommandState,
        linePickDeps: {
          setLinePickMode: (mode) => linePickMode.set(mode),
          setLinePickSelection: (line) => linePickSelection.set(line),
          navigate,
        },
        getStats: () => get(stats),
        getCurrentAddress: () => get(currentAddress),
      },
    )
    input = bundle.input
    isKnownCommand = bundle.isKnownCommand
    showInvalid = bundle.showInvalid
    activeCommandDef = bundle.activeCommandDef
    currentParseState = bundle.currentParseState
    suggestions = bundle.suggestions
    addressAutoFilled = bundle.addressAutoFilled
    lastAutoFilledCommand = bundle.lastAutoFilledCommand
  }

  function createRefs(): CliComponentRefs {
    return {
      getInput: () => input,
      setInput: (value) => {
        input = value
      },
      getActiveCommandDef: () => activeCommandDef,
      getCurrentParseState: () => currentParseState,
      getCliCaretHi: () => cliCaretHi,
      setCliCaretHi: (pos) => {
        cliCaretHi = pos
      },
      setPendingCliCaretHi: (pos) => {
        pendingCliCaretHi = pos
      },
      getBusy: () => busy,
      setBusy: (value) => {
        busy = value
      },
      setBusyMessage: (value) => {
        busyMessage = value
      },
      setFlashInvalid: (value) => {
        flashInvalid = value
      },
      setShowInvalid: (value) => {
        showInvalid = value
      },
      getSessionFillSuppressed: () => sessionFillSuppressed,
      setSessionFillSuppressed: (value) => {
        sessionFillSuppressed = value
      },
      getSuggestions: () => suggestions,
      getCliInputEl: () => cliInputEl,
      dataSources,
      updateCommandState,
      focusCliInput,
      inputIsMultiLine,
      navigate,
      onCliDone,
      syncLocation,
      submit,
    }
  }

  async function submit() {
    await submitCliCommand(buildSubmitDeps(createRefs()))
  }

  onMount(() => {
    const teardownLifecycle = setupCliLifecycle({
      getInput: () => input,
      setInput: (value) => {
        input = value
      },
      dataSources,
      updateCommandState,
      focusCliInput,
      resizeCliInput,
      suggestionApplyDeps: () => buildSuggestionApplyDeps(createRefs()),
      getLastProject: () => lastProject,
      setLastProject: (project) => {
        lastProject = project
      },
      getLastSessionOperator: () => lastSessionOperator,
      setLastSessionOperator: (op) => {
        lastSessionOperator = op
      },
      setSessionFillSuppressed: (value) => {
        sessionFillSuppressed = value
      },
      setLastAutoFilledCommand: (cmd) => {
        lastAutoFilledCommand = cmd
      },
      getPrevCliNavAddress: () => prevCliNavAddress,
      setPrevCliNavAddress: (addr) => {
        prevCliNavAddress = addr
      },
    })
    const teardownViewport = setupIosViewportHandler()
    void tick().then(() => resizeCliInput())
    return () => {
      teardownLifecycle()
      teardownViewport()
    }
  })

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

  const computedHint = $derived(
    computeCliHint(input, cliCaretHi, activeCommandDef, isKnownCommand, currentParseState),
  )
  const showHint = $derived(Boolean(computedHint) && isKnownCommand)
  const inputAttrs = $derived(computeCliInputAttrs(currentParseState))

  const guideKey = $derived(
    activeCommandDef
      ? activeCommandDef.trigger
      : '__general'
  )

  function openGuide() {
    guideModalCommand.set(guideKey)
  }
</script>

<svelte:window onkeydowncapture={globalKeydownFocusCli} />

<div class="bottom-bar" data-testid="bottom-bar">
  <CliSuggestions
    {suggestions}
    noWrap={$cliOutput !== null}
    onBeforeSelect={snapshotCaretBeforeChipPointer}
    onSelect={(suggestion) => handleCliSuggestionChipClick(suggestion, createRefs())}
  />
  <CliHistoryDrawer
    open={historyOpen}
    history={$cliHistory}
    onSelect={(entry) => {
      input = entry
      historyOpen = false
      updateCommandState()
      focusCliInput()
    }}
    onClear={() => {
      input = ''
      historyOpen = false
      updateCommandState()
      focusCliInput()
    }}
    onClose={() => historyOpen = false}
  />
  <div class="cli-bar-row">
    <button
      type="button"
      class={['cli-history-btn', { active: historyOpen }]}
      onclick={() => historyOpen = !historyOpen}
      aria-label="Command history"
      title="History"
    >↓</button>
    <div class="cli-bar-input-wrap">
      <CliInputField
      bind:input
      {showInvalid}
      {flashInvalid}
      {busy}
      {busyMessage}
      {showHint}
      {computedHint}
      autocomplete={inputAttrs.autocomplete}
      autocorrect={inputAttrs.autocorrect}
      autocapitalize={inputAttrs.autocapitalize}
      spellcheck={inputAttrs.spellcheck}
      attachInputEl={attachCliInputEl}
      onInput={(event) => handleCliTextInput(event, createRefs())}
      onKeydown={(event) => handleCliInputKeydown(event, createRefs())}
      onKeyup={(event) => handleCliInputKeyup(event, createRefs())}
      onSelectionRefresh={() => {
        if (!busy) updateCommandState()
      }}
      onBeforeInput={(event) => handleCliBeforeInput(event, createRefs())}
      onFocus={() => {
        historyOpen = false
        handleCliFocus(createRefs(), (value) => {
          isFocused = value
        })
      }}
      onBlur={(event) => handleCliBlur(event, createRefs(), (value) => {
        isFocused = value
      })}
    /></div>
    <button
      type="button"
      class="cli-guide-btn"
      onclick={openGuide}
      aria-label="Show guide"
      title="Guide"
    >?</button>
  </div>
</div>

<style>
  .cli-bar-row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .cli-bar-input-wrap {
    flex: 1;
    min-width: 0;
  }

  .cli-history-btn,
  .cli-guide-btn {
    flex-shrink: 0;
    background: none;
    border: 1px solid var(--pico-muted-border-color);
    font-size: 0.85rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    color: var(--pico-muted-color);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    transition: color 0.15s, border-color 0.15s;
  }

  .cli-guide-btn {
    border-radius: 50%;
    width: 1.6rem;
    height: 1.6rem;
    margin-bottom: 0.3rem;
  }

  .cli-history-btn {
    margin-top: 0rem;
    margin-bottom: 0.4rem;    
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 4px;
  }

  .cli-history-btn:hover,
  .cli-guide-btn:hover {
    color: var(--pico-color);
    border-color: var(--pico-color);
  }

  .cli-history-btn.active {
    color: var(--pico-color);
    border-color: var(--pico-color);
    background: var(--pico-muted-border-color);
  }
</style>
