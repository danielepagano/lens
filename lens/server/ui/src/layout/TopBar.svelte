<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import { treeOpen, kbPanelOpen, selectedKbId, inlineEditMode, inlineEditConfirmTrigger, inlineEditCancelTrigger } from '../stores/ui'
  import { currentProject } from '../stores/project'
  import { get } from 'svelte/store'
  import HamburgerIcon from '../components/icons/HamburgerIcon.svelte'

  $: parts = $currentAddress ? $currentAddress.split('/') : []
  $: parentAddr = parts.length > 1 ? parts.slice(0, -1).join('/') : null
  $: parentHash = parentAddr ? `${$currentProject ?? ''}/${parentAddr}` : null
  $: currentTitle = parts.length > 0 ? parts[parts.length - 1] : null
  $: isCursor = $stats?.cursor !== null && $stats?.cursor === $currentAddress
  $: has_pending = $stats?.has_pending
  $: has_staged = $stats?.has_staged

  function toggleKb() {
    if (get(kbPanelOpen)) {
      kbPanelOpen.set(false)
      treeOpen.set(false)
      const slug = get(currentProject) ?? ''
      const addr = get(currentAddress) || ''
      window.location.hash = slug && addr ? `${slug}/${addr}` : addr
    } else {
      kbPanelOpen.set(true)
      // Auto-open browser if no item is selected yet
      if (!get(selectedKbId)) {
        treeOpen.set(true)
      }
    }
  }
</script>

<header class="top-bar" data-testid="top-bar">
  {#if $inlineEditMode}
    <span class="inline-edit-label">
      {#if $inlineEditMode.appendMode}
        Append text
      {:else}
        Editing lines {$inlineEditMode.startLine}–{$inlineEditMode.endLine}
      {/if}
    </span>
    <div class="mode-switch">
      <button class="mode-btn inline-edit-ok" on:click={() => inlineEditConfirmTrigger.update(n => n + 1)}>OK</button>
      <button class="mode-btn" on:click={() => inlineEditCancelTrigger.update(n => n + 1)}>Cancel</button>
    </div>
  {:else}
    <button class="tree-toggle" on:click={() => treeOpen.update(v => !v)} aria-label="Toggle tree">
      <HamburgerIcon size={20} />
    </button>
    <span class="title">Lens</span>
    {#if parentHash}
      <a href="#{parentHash}" class="parent-link" aria-label="Go up to {parentAddr}">↑ {parts[parts.length - 2]}</a>
    {/if}
    {#if currentTitle}
      <span class="node-title">{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}{currentTitle}</span>
    {/if}
    <div class="mode-switch">
      <span class="tx-status {(!has_pending) && has_staged ? 'staged':''} ">{has_pending ? '*' : (has_staged ? '^' : '')}</span>
      <button
        class="mode-btn kb-toggle-btn"
        class:active={$kbPanelOpen}
        on:click={toggleKb}
        aria-pressed={$kbPanelOpen}
      >KB</button>
    </div>
  {/if}
</header>
