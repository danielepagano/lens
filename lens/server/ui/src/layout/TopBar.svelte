<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import {
    treeOpen,
    kbPanelOpen,
    selectedKbId,
    kbDetailId,
    inlineEditMode,
    inlineEditConfirmTrigger,
    inlineEditCancelTrigger,
  } from '../stores/ui'
  import { currentProject } from '../stores/project'
  import { get } from 'svelte/store'
  import HamburgerIcon from '../components/icons/HamburgerIcon.svelte'
  import SceneModesDialog from './SceneModesDialog.svelte'
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
  import ReleaseNotification from '../features/release/ReleaseNotification.svelte'

  let { navigate }: { navigate?: (addr: string) => Promise<void> } = $props()

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

  let modesDialogOpen = $state(false)

  function toggleKb() {
    if (get(kbPanelOpen)) {
      kbPanelOpen.set(false)
      treeOpen.set(false)
      const slug = get(currentProject) ?? ''
      const addr = get(currentAddress) || ''
      window.location.hash = slug && addr ? `${slug}/${addr}` : addr
    } else {
      kbPanelOpen.set(true)
      const slug = get(currentProject) ?? ''
      const addr = get(currentAddress) || ''
      const kb = get(selectedKbId)
      const detail = get(kbDetailId)
      if (kb && slug && addr) {
        let hash = `${slug}/${addr}?kb=${encodeURIComponent(kb)}`
        if (detail) {
          hash += `&kb-detail=${encodeURIComponent(detail)}`
        }
        window.location.hash = hash
      }
      if (!kb) {
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
    {#if $stats?.tts_available || $stats?.has_mount}
      <button
        type="button"
        class="mode-btn scene-modes-btn"
        aria-label="Scene modes"
        title="Scene modes"
        onclick={() => (modesDialogOpen = true)}
      >Modes</button>
      <SceneModesDialog open={modesDialogOpen} onClose={() => (modesDialogOpen = false)} />
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
      <span class="node-title" role="link" tabindex="0" onclick={() => navigate?.($currentAddress ?? '')} onkeydown={(e) => e.key === 'Enter' && navigate?.($currentAddress ?? '')}
        >{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}{currentTitle}</span
      >
    {/if}
    <div class="mode-switch">
      <span class={['tx-status', { staged: !hasPending && hasStaged }]}
        >{hasPending ? '*' : hasStaged ? '^' : ''}</span
      >
      <ReleaseNotification />
      {#if $currentAddress}
        <button type="button" class="mode-btn scene-entry-btn" onclick={openScene}>Scene</button>
      {/if}
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

  .scene-modes-btn {
    flex-shrink: 0;
    font-size: 1rem;
    padding: 0.12rem 0.4rem;
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
