<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { stats } from '../stores/stats'
  import { treeOpen, appMode } from '../stores/ui'
  import HamburgerIcon from '../components/icons/HamburgerIcon.svelte'

  $: parts = $currentAddress ? $currentAddress.split('/') : []
  $: parentAddr = parts.length > 1 ? parts.slice(0, -1).join('/') : null
  $: currentTitle = parts.length > 0 ? parts[parts.length - 1] : null
  $: isCursor = $stats?.cursor !== null && $stats?.cursor === $currentAddress
  $: has_pending = $stats?.has_pending
  $: has_staged = $stats?.has_staged

  function switchToNarrative() {
    appMode.set('narrative')
  }
</script>

<header class="top-bar" data-testid="top-bar">
  <button class="tree-toggle" on:click={() => treeOpen.update(v => !v)} aria-label="Toggle tree">
    <HamburgerIcon size={20} />
  </button>
  <span class="title">Lens</span>
  {#if $appMode === 'narrative'}
    {#if parentAddr}
      <a href="#{parentAddr}" class="parent-link" aria-label="Go up to {parentAddr}">↑ {parts[parts.length - 2]}</a>
    {/if}
    {#if currentTitle}
      <span class="node-title">{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}{currentTitle}</span>
    {/if}
  {/if}
  <div class="mode-switch">
    <span class="tx-status {(!has_pending) && has_staged ? 'staged':''} ">{has_pending ? '*' : (has_staged ? '^' : '')}</span>
    <button
      class="mode-btn"
      class:active={$appMode === 'narrative'}
      on:click={switchToNarrative}
      aria-pressed={$appMode === 'narrative'}
    >Narrative</button>
    <button
      class="mode-btn"
      class:active={$appMode === 'kb'}
      on:click={() => appMode.set('kb')}
      aria-pressed={$appMode === 'kb'}
    >KB</button>
  </div>
</header>
