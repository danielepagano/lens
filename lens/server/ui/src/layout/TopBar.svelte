<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { cursor } from '../stores/session'
  import { treeOpen, appMode } from '../stores/ui'
  import HamburgerIcon from '../components/icons/HamburgerIcon.svelte'

  $: parts = $currentAddress ? $currentAddress.split('/') : []
  $: parentAddr = parts.length > 1 ? parts.slice(0, -1).join('/') : null
  $: currentTitle = parts.length > 0 ? parts[parts.length - 1] : null
  $: isCursor = $cursor !== null && $cursor === $currentAddress
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
      <span class="node-title">{currentTitle}{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}</span>
    {/if}
  {/if}
  <div class="mode-switch">
    <button
      class="mode-btn"
      class:active={$appMode === 'narrative'}
      on:click={() => appMode.set('narrative')}
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
