<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import {
    treeOpen,
    kbPanelOpen,
    selectedKbId,
    inlineEditMode,
    inlineEditConfirmTrigger,
    inlineEditCancelTrigger,
  } from '../stores/ui'
  import { currentProject } from '../stores/project'
  import { get } from 'svelte/store'
  import HamburgerIcon from '../components/icons/HamburgerIcon.svelte'
  import { parsedHash } from '../stores/parsedHash'
  import {
    vnModeFromParsed,
    vnPlayback,
    vnImageExplore,
  } from '../stores/visualNovel'
  import {
    enterVisualNovel,
    exitVisualNovel,
    setVisualNovelHash,
    resolveVisualNovelIndex,
    resolveVisualNovelTtsSettings,
  } from '../utils/vnNavigate'
  import { vnCursorCliSlotEligible } from '../utils/vnCursorCli'
  import { navigateVnLogicalStep, vnLogicalStepCount } from '../utils/vnPlaybackNav'
  import type { VnTtsSettings } from '../utils/vnTypes'
  import { readVnSession, writeVnSession } from '../utils/vnSessionStorage'

  const parts = $derived($currentAddress ? $currentAddress.split('/') : [])
  const parentAddr = $derived(parts.length > 1 ? parts.slice(0, -1).join('/') : null)
  const parentHash = $derived(parentAddr ? `${$currentProject ?? ''}/${parentAddr}` : null)
  const currentTitle = $derived(parts.length > 0 ? parts[parts.length - 1] : null)
  const isCursor = $derived($stats?.cursor !== null && $stats?.cursor === $currentAddress)
  const hasPending = $derived($stats?.has_pending ?? false)
  const hasStaged = $derived($stats?.has_staged ?? false)

  const vnActive = $derived(vnModeFromParsed($parsedHash, $currentProject, $currentAddress))
  const vnNavItems = $derived($vnPlayback?.items ?? [])
  const vnCursorCli = $derived(
    vnActive && vnNavItems.length > 0 && vnCursorCliSlotEligible($stats, $currentAddress, vnNavItems)
  )
  const vnStepCount = $derived(vnNavItems.length > 0 ? vnLogicalStepCount(vnNavItems, vnCursorCli) : 0)
  const vnIx = $derived(
    vnActive && $currentProject && $currentAddress
      ? resolveVisualNovelIndex($parsedHash, $currentProject, $currentAddress)
      : 0
  )
  const vnTts = $derived(vnActive ? resolveVisualNovelTtsSettings($parsedHash) : null)
  const vnProgressDenom = $derived(vnStepCount)
  const vnProgressNum = $derived(vnProgressDenom > 0 ? Math.min(vnIx + 1, vnProgressDenom) : 0)
  const vnPrevDisabled = $derived(
    vnNavItems.length < 1 || navigateVnLogicalStep(vnNavItems, vnIx, -1, vnCursorCli) === vnIx
  )
  const vnNextDisabled = $derived(
    vnNavItems.length < 1 || navigateVnLogicalStep(vnNavItems, vnIx, 1, vnCursorCli) === vnIx
  )
  const vnLastIx = $derived(vnStepCount > 0 ? vnStepCount - 1 : 0)
  const vnLastDisabled = $derived(vnNavItems.length < 1 || vnIx === vnLastIx)

  function applyVnTts(next: VnTtsSettings) {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (!slug || !addr) return
    const ix = resolveVisualNovelIndex(get(parsedHash), slug, addr)
    setVisualNovelHash(slug, addr, ix, next)
    const prev = readVnSession()
    if (prev?.projectSlug === slug && prev?.nodeAddress === addr) {
      writeVnSession({
        version: 2,
        projectSlug: slug,
        nodeAddress: addr,
        logicalStep: ix,
        settings: { ...next },
      })
    }
  }

  function toggleSpeak() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (cur.speak) {
      applyVnTts({ speak: false, autoAdvance: false, renderNew: false })
    } else {
      applyVnTts({ ...cur, speak: true })
    }
  }

  function toggleAutoAdvance() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (!cur.speak) return
    applyVnTts({ ...cur, autoAdvance: !cur.autoAdvance })
  }

  function toggleRenderNew() {
    const cur = resolveVisualNovelTtsSettings(get(parsedHash))
    if (!cur.speak) return
    applyVnTts({ ...cur, renderNew: !cur.renderNew })
  }

  function toggleKb() {
    if (get(kbPanelOpen)) {
      kbPanelOpen.set(false)
      treeOpen.set(false)
      const slug = get(currentProject) ?? ''
      const addr = get(currentAddress) || ''
      window.location.hash = slug && addr ? `${slug}/${addr}` : addr
    } else {
      kbPanelOpen.set(true)
      if (!get(selectedKbId)) {
        treeOpen.set(true)
      }
    }
  }

  function openScene() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (!slug || !addr) return
    kbPanelOpen.set(false)
    selectedKbId.set(null)
    enterVisualNovel(slug, addr)
  }

  function vnPrev() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    const items = get(vnPlayback)?.items ?? []
    if (!slug || !addr || items.length < 1) return
    const ph = get(parsedHash)
    const next = navigateVnLogicalStep(items, vnIx, -1, vnCursorCliSlotEligible(get(stats), addr, items))
    setVisualNovelHash(slug, addr, next, resolveVisualNovelTtsSettings(ph))
  }

  function vnFirst() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    const items = get(vnPlayback)?.items ?? []
    if (!slug || !addr || items.length < 1) return
    const ph = get(parsedHash)
    setVisualNovelHash(slug, addr, 0, resolveVisualNovelTtsSettings(ph))
  }

  function vnNext() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    const items = get(vnPlayback)?.items ?? []
    if (!slug || !addr || items.length < 1) return
    const ph = get(parsedHash)
    const next = navigateVnLogicalStep(items, vnIx, 1, vnCursorCliSlotEligible(get(stats), addr, items))
    setVisualNovelHash(slug, addr, next, resolveVisualNovelTtsSettings(ph))
  }

  function vnLast() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    const items = get(vnPlayback)?.items ?? []
    if (!slug || !addr || items.length < 1) return
    const ph = get(parsedHash)
    const eligible = vnCursorCliSlotEligible(get(stats), addr, items)
    const lastIx = Math.max(0, vnLogicalStepCount(items, eligible) - 1)
    setVisualNovelHash(slug, addr, lastIx, resolveVisualNovelTtsSettings(ph))
  }

  function vnExit() {
    const slug = get(currentProject)
    const addr = get(currentAddress)
    if (!slug || !addr) return
    const ph = get(parsedHash)
    exitVisualNovel(slug, addr, vnIx, resolveVisualNovelTtsSettings(ph))
  }

  function confirmInlineEdit() {
    inlineEditConfirmTrigger.update((count) => count + 1)
  }

  function cancelInlineEdit() {
    inlineEditCancelTrigger.update((count) => count + 1)
  }

  function toggleTree() {
    treeOpen.update((open) => !open)
  }
</script>

<header class={['top-bar', { 'vn-mode': vnActive && !$vnImageExplore }]} data-testid="top-bar">
  {#if $inlineEditMode}
    <span class="inline-edit-label">
      {#if $inlineEditMode.appendMode}
        Append text
      {:else}
        Editing lines {$inlineEditMode.startLine}–{$inlineEditMode.endLine}
      {/if}
    </span>
    <div class="mode-switch">
      <button class="mode-btn inline-edit-ok" onclick={confirmInlineEdit}
        >OK</button
      >
      <button class="mode-btn" onclick={cancelInlineEdit}>Cancel</button>
    </div>
  {:else if vnActive && !$vnImageExplore}
    <button
      type="button"
      class="vn-nav-btn"
      aria-label="First beat"
      disabled={vnNavItems.length < 1 || vnIx === 0}
      onclick={vnFirst}>«</button
    >
    <button
      type="button"
      class="vn-nav-btn"
      aria-label="Previous beat"
      disabled={vnPrevDisabled}
      onclick={vnPrev}>◀</button
    >
    <span class="vn-progress" data-testid="vn-progress"
      >{vnProgressDenom > 0 ? vnProgressNum : 0} / {vnProgressDenom}</span
    >
    <button
      type="button"
      class="vn-nav-btn"
      aria-label="Next beat"
      disabled={vnNextDisabled}
      onclick={vnNext}>▶</button
    >
    <button
      type="button"
      class="vn-nav-btn"
      aria-label="Last beat"
      disabled={vnLastDisabled}
      onclick={vnLast}>»</button
    >
    {#if $stats?.tts_available && vnTts}
      <button
        type="button"
        class={['mode-btn', 'vn-tts-toggle', { active: vnTts.speak }]}
        aria-pressed={vnTts.speak}
        aria-label="Text-to-speech in Scene"
        onclick={toggleSpeak}
      >TTS</button
      >
      {#if vnTts.speak}
        <button
          type="button"
          class={['mode-btn', 'vn-tts-toggle', 'vn-tts-icon-btn', { active: vnTts.autoAdvance }]}
          aria-pressed={vnTts.autoAdvance}
          aria-label="Auto-advance when speech ends"
          title="Auto-advance when speech ends"
          onclick={toggleAutoAdvance}
        >
          <svg class="vn-tts-icon-svg" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M5 5v14l8.5-7L5 5zm9 0v14l8.5-7L14 5z" />
          </svg>
        </button>
        <button
          type="button"
          class={[
            'mode-btn',
            'vn-tts-toggle',
            'vn-tts-icon-btn',
            'vn-tts-record-btn',
            { active: vnTts.renderNew },
          ]}
          aria-pressed={vnTts.renderNew}
          aria-label="Generate speech for uncached lines and pre-render the next chunk"
          title="Generate speech for uncached lines and pre-render the next chunk"
          onclick={toggleRenderNew}
        >
          <svg class="vn-tts-icon-svg" viewBox="0 0 24 24" aria-hidden="true">
            {#if vnTts.renderNew}
              <circle cx="12" cy="12" r="6.5" fill="currentColor" />
            {:else}
              <circle
                cx="12"
                cy="12"
                r="6.25"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              />
            {/if}
          </svg>
        </button>
      {/if}
    {/if}
    <button type="button" class="vn-exit-btn" aria-label="Exit scene mode" onclick={vnExit}>✕</button>
  {:else}
    <button class="tree-toggle" onclick={toggleTree} aria-label="Toggle tree">
      <HamburgerIcon size={20} />
    </button>
    <span class="title">Lens</span>
    {#if parentHash}
      <a href="#{parentHash}" class="parent-link" aria-label="Go up to {parentAddr}"
        >↑ {parts[parts.length - 2]}</a
      >
    {/if}
    {#if currentTitle}
      <span class="node-title"
        >{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}{currentTitle}</span
      >
    {/if}
    <div class="mode-switch">
      {#if $currentAddress}
        <button type="button" class="mode-btn scene-entry-btn" onclick={openScene}>Scene</button>
      {/if}
      <span class={['tx-status', { staged: !hasPending && hasStaged }]}
        >{hasPending ? '*' : hasStaged ? '^' : ''}</span
      >
      <button
        class={['mode-btn', 'kb-toggle-btn', { active: $kbPanelOpen }]}
        onclick={toggleKb}
        aria-pressed={$kbPanelOpen}>KB</button
      >
    </div>
  {/if}
</header>

<style>
  .vn-nav-btn {
    background: none;
    border: 1px solid var(--pico-muted-border-color, #444);
    border-radius: 6px;
    padding: 0.25rem 0.55rem;
    cursor: pointer;
    margin-bottom: 0px;
    font-size: 0.85rem;
    color: inherit;
    flex-shrink: 0;
  }

  .vn-nav-btn:hover:not(:disabled) {
    background: var(--pico-secondary-hover-background);
  }

  .vn-nav-btn:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .vn-progress {
    font-size: 0.85rem;
    opacity: 0.85;
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  .vn-tts-toggle {
    flex-shrink: 0;
    font-size: 0.72rem;
    padding: 0.12rem 0.4rem;
  }

  .vn-tts-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.18rem;
    min-width: 1.85rem;
    min-height: 1.65rem;
    line-height: 0;
  }

  .vn-tts-icon-svg {
    width: 1.05rem;
    height: 1.05rem;
    display: block;
  }

  .vn-tts-record-btn {
    color: #e84855;
    border-color: rgba(232, 72, 85, 0.55);
  }

  .vn-tts-record-btn:not(.active) {
    background: rgba(232, 72, 85, 0.12);
  }

  .vn-tts-record-btn.active {
    background: rgba(232, 72, 85, 0.38);
    border-color: #e84855;
    color: #ff6b76;
  }

  .vn-tts-record-btn:not(.active):hover {
    background: rgba(232, 72, 85, 0.2);
    color: #ff5c6a;
  }

  .vn-tts-record-btn.active:hover {
    background: rgba(232, 72, 85, 0.48);
  }

  .vn-exit-btn {
    background: none;
    border: none;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 0.2rem 0.5rem;
    opacity: 0.75;
    margin-bottom: 0px;
    min-height: 34px;
    flex-shrink: 0;
    line-height: 1;
    margin-left: auto;
    color: inherit;
  }

  .vn-exit-btn:hover {
    opacity: 1;
  }
</style>
