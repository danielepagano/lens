<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { cursor } from '../stores/session'
  import { treeOpen } from '../stores/ui'

  $: parts = $currentAddress ? $currentAddress.split('/') : []
  $: parentAddr = parts.length > 1 ? parts.slice(0, -1).join('/') : null
  $: currentTitle = parts.length > 0 ? parts[parts.length - 1] : null
  $: isCursor = $cursor !== null && $cursor === $currentAddress
</script>

<header class="top-bar" data-testid="top-bar">
  <button class="tree-toggle" on:click={() => treeOpen.update(v => !v)} aria-label="Toggle tree">
    ☰
  </button>
  <span class="title">Lens</span>
  {#if parentAddr}
    <a href="#{parentAddr}" class="parent-link" aria-label="Go up to {parentAddr}">↑ {parts[parts.length - 2]}</a>
  {/if}
  {#if currentTitle}
    <span class="node-title">{currentTitle}{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}</span>
  {/if}
</header>
